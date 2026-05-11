#!/usr/bin/env python3
"""
Standalone sensor collection service.
Reads DHT11, ADXL345, MQ2, Microphone and publishes to MQTT.

Usage:
    python -m edge_platform.sensors.run_sensors
    python edge_platform/sensors/run_sensors.py

Env vars:
    EDGE_DEVICE_ID   (default: MOTOR_001)
    EDGE_SITE_ID     (default: SITE_001)
    EDGE_MQTT_HOST   (default: localhost)
    EDGE_MQTT_PORT   (default: 1883)
    EDGE_INTERVAL    (default: 5)
    EDGE_SIMULATION  (default: false) — set to "true" for dev without hardware
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from edge_platform.sensors.collector import SensorCollector


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    device_id = os.environ.get("EDGE_DEVICE_ID", "MOTOR_001")
    site_id = os.environ.get("EDGE_SITE_ID", "SITE_001")
    mqtt_host = os.environ.get("EDGE_MQTT_HOST", "localhost")
    mqtt_port = int(os.environ.get("EDGE_MQTT_PORT", "1883"))
    interval = float(os.environ.get("EDGE_INTERVAL", "5"))

    print("=" * 50)
    print("  Sensor Collector — Raspberry Pi 3B+")
    print("=" * 50)
    print(f"  Device:   {device_id}")
    print(f"  Broker:   {mqtt_host}:{mqtt_port}")
    print(f"  Interval: {interval}s")
    print(f"  Topic:    iiot/site/{site_id}/device/{device_id}/telemetry")
    print("=" * 50)

    collector = SensorCollector(device_id=device_id, site_id=site_id, interval_seconds=interval)
    status = collector.initialize_all()

    print()
    for sensor, ok in status.items():
        print(f"  [{'OK' if ok else 'FAIL'}] {sensor}")
    print()

    if not any(status.values()):
        print("ERROR: No sensors detected. Check wiring or set EDGE_SIMULATION=true")
        sys.exit(1)

    try:
        asyncio.run(collector.publish_loop(mqtt_host=mqtt_host, mqtt_port=mqtt_port))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        collector.cleanup()


if __name__ == "__main__":
    main()
