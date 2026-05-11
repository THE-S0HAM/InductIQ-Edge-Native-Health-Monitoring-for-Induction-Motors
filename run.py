#!/usr/bin/env python3
"""
Industrial Edge AI Platform - One-Click Launcher
=================================================
Usage:
    python run.py

Dashboard: http://localhost:8420
API docs:  http://localhost:8420/api/docs
"""

import asyncio
import logging
import logging.handlers
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
os.chdir(ROOT)


# ── Setup ────────────────────────────────────────────────────

def install_dependencies():
    """Install Python dependencies if not already present."""
    try:
        import fastapi, uvicorn, pydantic, aiosqlite, orjson, psutil, yaml, numpy, sklearn, dotenv  # noqa: F401
        return
    except ImportError:
        pass

    print("[*] Installing dependencies (first run only)...")
    req_file = ROOT / "requirements.txt"
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q", "--user"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"[ERROR] pip install failed:\n{result.stderr}")
            sys.exit(1)
    print("[✓] Dependencies installed")


def create_directories():
    """Create required data directories."""
    for d in ["data", "data/models", "data/archives/telemetry",
              "data/archives/inference", "data/logs"]:
        (ROOT / d).mkdir(parents=True, exist_ok=True)


def initialize_database():
    """Initialize SQLite database with schema."""
    db_path = ROOT / "data" / "hot.db"
    if db_path.exists():
        return

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            device_id TEXT NOT NULL,
            sensor_type TEXT NOT NULL,
            value_json TEXT NOT NULL,
            quality INTEGER DEFAULT 100,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        );
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
        CREATE INDEX IF NOT EXISTS idx_telemetry_device_time ON telemetry(device_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_telemetry_time ON telemetry(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_inference_device_time ON inference_results(device_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity, resolved, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_alerts_device ON alerts(device_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_edge_health_time ON edge_health(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_events_type_time ON events(event_type, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_events_device ON events(device_id, timestamp DESC);
    """)

    # Pre-register devices
    for dev_id, dev_type, name, location in [
        ("MOTOR_001", "motor", "Main Drive Motor", "Production Line A"),
        ("MOTOR_002", "motor", "Cooling Pump Motor", "Utility Room B"),
        ("PUMP_001", "pump", "Hydraulic Pump", "Press Station C"),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO devices (device_id, site_id, device_type, name, location, status) "
            "VALUES (?, 'SITE_001', ?, ?, ?, 'online')",
            (dev_id, dev_type, name, location),
        )

    conn.commit()
    conn.close()
    print(f"[✓] Database initialized: {db_path}")


def check_mqtt_broker() -> bool:
    """Check if MQTT broker is reachable."""
    host = os.environ.get("EDGE_MQTT_HOST", "localhost")
    port = int(os.environ.get("EDGE_MQTT_PORT", "1883"))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        sock.connect((host, port))
        sock.close()
        print(f"[✓] MQTT broker at {host}:{port}")
        return True
    except (socket.error, socket.timeout):
        sock.close()
        print(f"[✗] MQTT broker not reachable at {host}:{port}")
        print("    Run: sudo systemctl start mosquitto")
        sys.exit(1)


def check_port_available(port: int) -> bool:
    """Check if the API port is free, kill stale process if needed."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        sock.connect(("127.0.0.1", port))
        sock.close()
        # Port is in use — try to kill the old process
        print(f"[!] Port {port} in use — killing stale process...")
        os.system(f"fuser -k {port}/tcp 2>/dev/null || lsof -ti :{port} | xargs kill -9 2>/dev/null")
        time.sleep(1)
        return True
    except (socket.error, socket.timeout):
        sock.close()
        return True


def setup_logging():
    """Configure logging with rotation."""
    log_dir = ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.handlers.RotatingFileHandler(
                str(log_dir / "platform.log"),
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
            ),
        ],
    )
    # Reduce noise from libraries
    for name in ("uvicorn.access", "uvicorn.error", "aiomqtt"):
        logging.getLogger(name).setLevel(logging.WARNING)


# ── Platform Launch ──────────────────────────────────────────

async def run_platform():
    """Main async entry point."""
    sys.path.insert(0, str(ROOT))

    from edge_platform.config import get_config
    from edge_platform.platform import EdgePlatform
    from edge_platform.api.app import create_app
    import uvicorn

    config = get_config()
    logger = logging.getLogger("main")

    # Create platform and app
    platform = EdgePlatform(config)
    app = create_app(config, platform)

    # Start platform (MQTT + storage + AI pipeline)
    await platform.start()

    # Start sensor collector
    sensor_task = None
    try:
        from edge_platform.sensors.collector import SensorCollector

        device_id = os.environ.get("EDGE_DEVICE_ID", "MOTOR_001")
        collector = SensorCollector(
            device_id=device_id,
            site_id=config.site_id,
            interval_seconds=config.sensors.sampling_interval_seconds,
        )
        status = collector.initialize_all()
        active = sum(1 for v in status.values() if v)

        if active > 0:
            sensor_task = asyncio.create_task(
                collector.publish_loop(
                    mqtt_host=config.mqtt.broker_host,
                    mqtt_port=config.mqtt.broker_port,
                )
            )
            logger.info("✓ Sensor collector started (%d/4 sensors active)", active)
        else:
            logger.warning("⚠ No sensors detected — waiting for external MQTT data")
    except ImportError:
        logger.info("Sensor libraries not available — waiting for external MQTT data")
    except Exception as e:
        logger.warning("Sensor init skipped: %s", e)

    # Print banner
    port = config.api.port
    mqtt_topic = f"iiot/site/{config.site_id}/device/+/telemetry"
    print(f"""
{'=' * 60}
  Industrial Edge AI Platform is LIVE
{'=' * 60}

  Dashboard:  http://localhost:{port}
  API Docs:   http://localhost:{port}/api/docs
  Health:     http://localhost:{port}/health
  Live Data:  http://localhost:{port}/api/v1/telemetry/current

  MQTT Broker: {config.mqtt.broker_host}:{config.mqtt.broker_port}
  Subscribed:  {mqtt_topic}

  Press Ctrl+C to stop.
{'=' * 60}
""")

    # Start uvicorn server
    server = uvicorn.Server(uvicorn.Config(
        app,
        host=config.api.host,
        port=port,
        workers=1,
        log_level="warning",
        access_log=False,
    ))

    try:
        await server.serve()
    except asyncio.CancelledError:
        pass
    finally:
        if sensor_task:
            sensor_task.cancel()
            try:
                await sensor_task
            except asyncio.CancelledError:
                pass
        await platform.stop()


# ── Entry Point ──────────────────────────────────────────────

def main():
    """Single entry point — setup and launch."""
    print()
    print("=" * 60)
    print("  Industrial Edge AI Platform - Startup")
    print("=" * 60)
    print()

    install_dependencies()
    create_directories()
    initialize_database()
    check_mqtt_broker()

    # Initialize DynamoDB table
    try:
        from edge_platform.cloud.dynamo_store import create_table_if_not_exists
        create_table_if_not_exists()
        print("[✓] DynamoDB table ready")
    except Exception as e:
        print(f"[!] DynamoDB setup skipped: {e}")
        print("    Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env")

    # Auto-kill stale process on same port
    port = int(os.environ.get("EDGE_API_PORT", "8420"))
    check_port_available(port)

    setup_logging()

    print()
    print("[*] Starting platform...")
    print()

    try:
        asyncio.run(run_platform())
    except KeyboardInterrupt:
        print("\n[*] Shutting down gracefully...")
    except Exception as e:
        print(f"\n[ERROR] Platform crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
