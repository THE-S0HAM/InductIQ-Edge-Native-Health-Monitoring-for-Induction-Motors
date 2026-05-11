"""
Data archiver - moves hot data to Parquet cold storage.
Implements tiered retention with compression for SD card longevity.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import aiosqlite
import orjson
import pyarrow as pa
import pyarrow.parquet as pq

from edge_platform.config import ParquetConfig, RetentionConfig

logger = logging.getLogger(__name__)


class DataArchiver:
    """
    Archives hot SQLite data to compressed Parquet files.
    
    Strategy:
    - Hourly: Archive telemetry older than retention window
    - Daily: Compress and merge hourly files
    - Weekly: Roll up into weekly summaries
    
    Optimized for minimal SD card writes via batched operations.
    """

    def __init__(
        self,
        sqlite_path: str,
        parquet_config: ParquetConfig,
        retention_config: RetentionConfig,
    ):
        self.sqlite_path = sqlite_path
        self.config = parquet_config
        self.retention = retention_config
        self._archive_dir = Path(parquet_config.archive_dir)
        self._archive_dir.mkdir(parents=True, exist_ok=True)

    async def archive_telemetry(self) -> int:
        """
        Archive telemetry data older than hot retention to Parquet.
        Returns number of rows archived.
        """
        cutoff = int(time.time()) - (self.retention.hot_hours * 3600)
        
        async with aiosqlite.connect(self.sqlite_path) as db:
            # Read data to archive
            cursor = await db.execute(
                """SELECT timestamp, device_id, sensor_type, value_json, quality
                   FROM telemetry WHERE timestamp < ?
                   ORDER BY timestamp ASC LIMIT ?""",
                (cutoff, self.config.row_group_size),
            )
            rows = await cursor.fetchall()
            
            if not rows:
                return 0
            
            # Convert to Parquet
            timestamps = []
            device_ids = []
            sensor_types = []
            values = []
            qualities = []
            
            for row in rows:
                timestamps.append(row[0])
                device_ids.append(row[1])
                sensor_types.append(row[2])
                values.append(row[3])
                qualities.append(row[4])
            
            table = pa.table({
                "timestamp": pa.array(timestamps, type=pa.int64()),
                "device_id": pa.array(device_ids, type=pa.string()),
                "sensor_type": pa.array(sensor_types, type=pa.string()),
                "value_json": pa.array(values, type=pa.string()),
                "quality": pa.array(qualities, type=pa.int32()),
            })
            
            # Write Parquet file
            date_str = time.strftime("%Y%m%d_%H", time.gmtime(timestamps[0]))
            filename = f"telemetry_{date_str}.parquet"
            filepath = self._archive_dir / "telemetry" / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            
            pq.write_table(
                table,
                str(filepath),
                compression=self.config.compression,
                row_group_size=self.config.row_group_size,
            )
            
            # Delete archived rows from SQLite
            max_ts = timestamps[-1]
            min_id = rows[0][0]  # Using timestamp as proxy
            await db.execute(
                "DELETE FROM telemetry WHERE timestamp <= ? AND timestamp >= ?",
                (max_ts, timestamps[0]),
            )
            await db.commit()
            
            logger.info(
                "Archived %d telemetry rows to %s", len(rows), filename
            )
            return len(rows)

    async def archive_inference(self) -> int:
        """Archive old inference results to Parquet."""
        cutoff = int(time.time()) - (self.retention.hot_hours * 3600)
        
        async with aiosqlite.connect(self.sqlite_path) as db:
            cursor = await db.execute(
                """SELECT timestamp, device_id, fault_class, confidence, 
                          health_score, scores_json, rul_hours, model_version
                   FROM inference_results WHERE timestamp < ?
                   ORDER BY timestamp ASC LIMIT ?""",
                (cutoff, self.config.row_group_size),
            )
            rows = await cursor.fetchall()
            
            if not rows:
                return 0
            
            table = pa.table({
                "timestamp": pa.array([r[0] for r in rows], type=pa.int64()),
                "device_id": pa.array([r[1] for r in rows], type=pa.string()),
                "fault_class": pa.array([r[2] for r in rows], type=pa.string()),
                "confidence": pa.array([r[3] for r in rows], type=pa.float64()),
                "health_score": pa.array([r[4] for r in rows], type=pa.float64()),
                "scores_json": pa.array([r[5] for r in rows], type=pa.string()),
                "rul_hours": pa.array([r[6] for r in rows], type=pa.float64()),
                "model_version": pa.array([r[7] for r in rows], type=pa.string()),
            })
            
            date_str = time.strftime("%Y%m%d_%H", time.gmtime(rows[0][0]))
            filename = f"inference_{date_str}.parquet"
            filepath = self._archive_dir / "inference" / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            
            pq.write_table(table, str(filepath), compression=self.config.compression)
            
            # Delete archived rows
            await db.execute(
                "DELETE FROM inference_results WHERE timestamp < ?", (cutoff,)
            )
            await db.commit()
            
            logger.info("Archived %d inference rows to %s", len(rows), filename)
            return len(rows)

    async def cleanup_old_archives(self) -> int:
        """Remove archive files older than retention policy."""
        cutoff_ts = time.time() - (self.retention.archive_days * 86400)
        removed = 0
        
        for parquet_file in self._archive_dir.rglob("*.parquet"):
            if parquet_file.stat().st_mtime < cutoff_ts:
                parquet_file.unlink()
                removed += 1
        
        if removed > 0:
            logger.info("Removed %d expired archive files", removed)
        
        return removed

    async def get_archive_stats(self) -> dict[str, Any]:
        """Get archive storage statistics."""
        total_size = 0
        file_count = 0
        
        for parquet_file in self._archive_dir.rglob("*.parquet"):
            total_size += parquet_file.stat().st_size
            file_count += 1
        
        return {
            "archive_dir": str(self._archive_dir),
            "file_count": file_count,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "compression": self.config.compression,
        }

    async def run_archival_cycle(self) -> dict[str, int]:
        """Run a complete archival cycle."""
        telemetry_archived = await self.archive_telemetry()
        inference_archived = await self.archive_inference()
        archives_cleaned = await self.cleanup_old_archives()
        
        return {
            "telemetry_archived": telemetry_archived,
            "inference_archived": inference_archived,
            "archives_cleaned": archives_cleaned,
        }
