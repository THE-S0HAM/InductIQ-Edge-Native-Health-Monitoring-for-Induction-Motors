"""
SQLite hot storage for recent telemetry, alerts, and device state.
Optimized for SD-card longevity with WAL mode and bounded writes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import aiosqlite
import orjson

from edge_platform.config import SQLiteConfig

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
-- Telemetry readings (circular buffer, last 24h)
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    device_id TEXT NOT NULL,
    sensor_type TEXT NOT NULL,
    value_json TEXT NOT NULL,
    quality INTEGER DEFAULT 100,
    created_at INTEGER DEFAULT (strftime('%s','now'))
);

-- AI inference results
CREATE TABLE IF NOT EXISTS inference_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    device_id TEXT NOT NULL,
    fault_class TEXT,
    confidence REAL,
    health_score REAL,
    scores_json TEXT,
    rul_hours REAL,
    model_version TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now'))
);

-- Active alerts
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT UNIQUE,
    timestamp INTEGER NOT NULL,
    device_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    message TEXT,
    metadata_json TEXT,
    acknowledged INTEGER DEFAULT 0,
    resolved INTEGER DEFAULT 0,
    resolved_at INTEGER,
    created_at INTEGER DEFAULT (strftime('%s','now'))
);

-- Device registry
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    device_type TEXT,
    name TEXT,
    location TEXT,
    firmware_version TEXT,
    config_json TEXT,
    calibration_json TEXT,
    sensors_json TEXT,
    last_heartbeat INTEGER,
    status TEXT DEFAULT 'unknown',
    registered_at INTEGER DEFAULT (strftime('%s','now'))
);

-- Edge health snapshots
CREATE TABLE IF NOT EXISTS edge_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    cpu_percent REAL,
    ram_percent REAL,
    disk_percent REAL,
    temperature REAL,
    mqtt_latency_ms REAL,
    process_count INTEGER
);

-- Events log
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT,
    timestamp INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    device_id TEXT,
    source TEXT,
    data_json TEXT,
    correlation_id TEXT
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_telemetry_device_time ON telemetry(device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_time ON telemetry(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_inference_device_time ON inference_results(device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity, resolved, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_device ON alerts(device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_edge_health_time ON edge_health(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_type_time ON events(event_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_device ON events(device_id, timestamp DESC);
"""


class SQLiteStore:
    """
    Async SQLite storage optimized for Raspberry Pi.
    
    Features:
    - WAL mode for concurrent reads during writes
    - Bounded journal size to limit SD card wear
    - Batch insert support
    - Automatic cleanup of old data
    """

    def __init__(self, config: SQLiteConfig):
        self.config = config
        self._db: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize database connection and schema."""
        db_path = Path(self.config.path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._db = await aiosqlite.connect(str(db_path))
        
        # Optimize for SD card and performance
        if self.config.wal_mode:
            await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(f"PRAGMA journal_size_limit={self.config.journal_size_limit}")
        await self._db.execute(f"PRAGMA cache_size={self.config.cache_size}")
        await self._db.execute(f"PRAGMA busy_timeout={self.config.busy_timeout}")
        await self._db.execute("PRAGMA synchronous=NORMAL")  # Balance durability/speed
        await self._db.execute("PRAGMA temp_store=MEMORY")
        await self._db.execute("PRAGMA mmap_size=67108864")  # 64MB mmap
        
        # Create schema
        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()
        
        logger.info("SQLite store initialized at %s", self.config.path)

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # === Telemetry Operations ===

    async def insert_telemetry(self, rows: list[dict[str, Any]]) -> None:
        """Batch insert telemetry readings."""
        if not rows:
            return
        
        async with self._write_lock:
            await self._db.executemany(
                """INSERT INTO telemetry (timestamp, device_id, sensor_type, value_json, quality)
                   VALUES (:timestamp, :device_id, :sensor_type, :value_json, :quality)""",
                rows,
            )
            await self._db.commit()

    async def get_latest_telemetry(
        self, device_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get latest telemetry for a device."""
        cursor = await self._db.execute(
            """SELECT timestamp, device_id, sensor_type, value_json, quality
               FROM telemetry WHERE device_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (device_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "timestamp": r[0],
                "device_id": r[1],
                "sensor_type": r[2],
                "value": orjson.loads(r[3]),
                "quality": r[4],
            }
            for r in rows
        ]

    async def get_telemetry_range(
        self, device_id: str, start_ts: int, end_ts: int, sensor_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Get telemetry within a time range."""
        query = """SELECT timestamp, sensor_type, value_json, quality
                   FROM telemetry WHERE device_id = ? AND timestamp BETWEEN ? AND ?"""
        params: list[Any] = [device_id, start_ts, end_ts]
        
        if sensor_type:
            query += " AND sensor_type = ?"
            params.append(sensor_type)
        
        query += " ORDER BY timestamp ASC"
        
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        return [
            {
                "timestamp": r[0],
                "sensor_type": r[1],
                "value": orjson.loads(r[2]),
                "quality": r[3],
            }
            for r in rows
        ]

    # === Inference Operations ===

    async def insert_inference(self, result: dict[str, Any]) -> None:
        """Store an inference result."""
        async with self._write_lock:
            await self._db.execute(
                """INSERT INTO inference_results 
                   (timestamp, device_id, fault_class, confidence, health_score, 
                    scores_json, rul_hours, model_version)
                   VALUES (:timestamp, :device_id, :fault_class, :confidence, 
                           :health_score, :scores_json, :rul_hours, :model_version)""",
                result,
            )
            await self._db.commit()

    async def get_latest_inference(self, device_id: str) -> dict[str, Any] | None:
        """Get the most recent inference for a device."""
        cursor = await self._db.execute(
            """SELECT timestamp, device_id, fault_class, confidence, health_score,
                      scores_json, rul_hours, model_version
               FROM inference_results WHERE device_id = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (device_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "timestamp": row[0],
            "device_id": row[1],
            "fault_class": row[2],
            "confidence": row[3],
            "health_score": row[4],
            "scores": orjson.loads(row[5]) if row[5] else {},
            "rul_hours": row[6],
            "model_version": row[7],
        }

    # === Alert Operations ===

    async def insert_alert(self, alert: dict[str, Any]) -> None:
        """Store a new alert."""
        async with self._write_lock:
            await self._db.execute(
                """INSERT OR IGNORE INTO alerts 
                   (alert_id, timestamp, device_id, severity, alert_type, message, metadata_json)
                   VALUES (:alert_id, :timestamp, :device_id, :severity, :alert_type, 
                           :message, :metadata_json)""",
                alert,
            )
            await self._db.commit()

    async def get_active_alerts(
        self, severity: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get active (unresolved) alerts."""
        query = "SELECT * FROM alerts WHERE resolved = 0"
        params: list[Any] = []
        
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor = await self._db.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        async with self._write_lock:
            cursor = await self._db.execute(
                "UPDATE alerts SET acknowledged = 1 WHERE alert_id = ? AND resolved = 0",
                (alert_id,),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def resolve_alert(self, alert_id: str) -> bool:
        """Resolve an alert."""
        async with self._write_lock:
            cursor = await self._db.execute(
                "UPDATE alerts SET resolved = 1, resolved_at = ? WHERE alert_id = ?",
                (int(time.time()), alert_id),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    # === Device Operations ===

    async def upsert_device(self, device: dict[str, Any]) -> None:
        """Register or update a device."""
        async with self._write_lock:
            await self._db.execute(
                """INSERT INTO devices (device_id, site_id, device_type, name, location,
                                       firmware_version, config_json, sensors_json, status)
                   VALUES (:device_id, :site_id, :device_type, :name, :location,
                           :firmware_version, :config_json, :sensors_json, :status)
                   ON CONFLICT(device_id) DO UPDATE SET
                       device_type = excluded.device_type,
                       name = excluded.name,
                       firmware_version = excluded.firmware_version,
                       config_json = excluded.config_json,
                       sensors_json = excluded.sensors_json,
                       status = excluded.status""",
                device,
            )
            await self._db.commit()

    async def update_heartbeat(self, device_id: str) -> None:
        """Update device heartbeat timestamp."""
        async with self._write_lock:
            await self._db.execute(
                "UPDATE devices SET last_heartbeat = ?, status = 'online' WHERE device_id = ?",
                (int(time.time()), device_id),
            )
            await self._db.commit()

    async def get_all_devices(self) -> list[dict[str, Any]]:
        """Get all registered devices."""
        cursor = await self._db.execute("SELECT * FROM devices")
        columns = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    # === Health Operations ===

    async def insert_health(self, health: dict[str, Any]) -> None:
        """Store edge health snapshot."""
        async with self._write_lock:
            await self._db.execute(
                """INSERT INTO edge_health 
                   (timestamp, cpu_percent, ram_percent, disk_percent, temperature, 
                    mqtt_latency_ms, process_count)
                   VALUES (:timestamp, :cpu_percent, :ram_percent, :disk_percent,
                           :temperature, :mqtt_latency_ms, :process_count)""",
                health,
            )
            await self._db.commit()

    # === Retention ===

    async def cleanup_old_data(self, retention_hours: int = 24) -> int:
        """Remove data older than retention period. Returns rows deleted."""
        cutoff = int(time.time()) - (retention_hours * 3600)
        total_deleted = 0
        
        async with self._write_lock:
            for table in ["telemetry", "inference_results", "edge_health", "events"]:
                cursor = await self._db.execute(
                    f"DELETE FROM telemetry WHERE timestamp < ?", (cutoff,)
                )
                total_deleted += cursor.rowcount
            
            # Resolved alerts older than 7 days
            alert_cutoff = int(time.time()) - (7 * 24 * 3600)
            cursor = await self._db.execute(
                "DELETE FROM alerts WHERE resolved = 1 AND resolved_at < ?",
                (alert_cutoff,),
            )
            total_deleted += cursor.rowcount
            
            await self._db.commit()
        
        if total_deleted > 0:
            logger.info("Cleaned up %d old records", total_deleted)
        
        return total_deleted

    async def get_table_counts(self) -> dict[str, int]:
        """Get row counts for all tables (for monitoring)."""
        counts = {}
        for table in ["telemetry", "inference_results", "alerts", "devices", "edge_health", "events"]:
            cursor = await self._db.execute(f"SELECT COUNT(*) FROM {table}")
            row = await cursor.fetchone()
            counts[table] = row[0]
        return counts
