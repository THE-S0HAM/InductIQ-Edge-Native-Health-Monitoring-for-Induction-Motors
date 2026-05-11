# -*- coding: utf-8 -*-
"""
Sensor data collector for Raspberry Pi 3B+.
Reads from physical sensors and publishes structured JSON to MQTT.

Hardware (tested and working):
  - DHT11: Temperature + Humidity on GPIO D4 (adafruit_dht)
  - ADXL345: 3-axis vibration via I2C (adafruit_adxl34x)
  - MQ2: Smoke/gas detection on GPIO 11 (RPi.GPIO)
  - Microphone (KY-038): Sound detection on GPIO 17 (RPi.GPIO)

Pin Wiring (BCM):
  - DHT11 data   -> GPIO 4  (Pin 7)
  - ADXL345 SDA  -> GPIO 2  (Pin 3)
  - ADXL345 SCL  -> GPIO 3  (Pin 5)
  - MQ2 DO       -> GPIO 11 (Pin 23)
  - KY-038 DO    -> GPIO 17 (Pin 11)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Check if we're in simulation mode (for dev on non-Pi machines)
SIMULATION_MODE = os.environ.get("EDGE_SIMULATION", "false").lower() == "true"

# ── Last Known Values Cache (fallback when sensors fail) ─────
_last_readings: dict[str, Any] = {
    "temperature": 25.0,
    "humidity": 50.0,
    "vib_x": 0.0,
    "vib_y": 0.0,
    "vib_z": 0.0,
    "current": 0.0,
    "sound": False,
    "smoke": False,
}

# ── Sensor Device Singletons ─────────────────────────────────
_dht_device = None
_vibration_device = None
_gpio_initialized = False


def _init_gpio():
    """Initialize RPi.GPIO once."""
    global _gpio_initialized
    if _gpio_initialized or SIMULATION_MODE:
        return
    try:
        import RPi.GPIO as GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(11, GPIO.IN)   # MQ2
        GPIO.setup(17, GPIO.IN)   # Microphone
        _gpio_initialized = True
        logger.info("GPIO initialized (MQ2=11, MIC=17)")
    except Exception as e:
        logger.error("GPIO init failed: %s", e)


def get_temp_humidity() -> tuple[float | None, float | None]:
    """Read temperature (C) and humidity (%) from DHT11 on GPIO D4."""
    global _dht_device

    if SIMULATION_MODE:
        import random
        return round(random.uniform(20, 95), 1), round(random.uniform(30, 95), 1)

    if _dht_device is None:
        try:
            import board
            import adafruit_dht
            _dht_device = adafruit_dht.DHT11(board.D4, use_pulseio=False)
            logger.info("DHT11 initialized on GPIO D4")
        except Exception as e:
            logger.error("DHT11 init failed: %s", e)
            return None, None

    # Retry up to 5 times (DHT11 is unreliable)
    for _ in range(5):
        try:
            temp = _dht_device.temperature
            hum = _dht_device.humidity
            if temp is not None and hum is not None:
                _last_readings["temperature"] = float(temp)
                _last_readings["humidity"] = float(hum)
                return float(temp), float(hum)
        except RuntimeError:
            time.sleep(2.0)
            continue
        except Exception as e:
            logger.error("DHT11 error: %s", e)
            _dht_device = None
            break

    return None, None


def get_vibration() -> tuple[float, float, float]:
    """Read vibration X/Y/Z (m/s2) from ADXL345 via I2C."""
    global _vibration_device

    if SIMULATION_MODE:
        import random
        return (
            round(random.uniform(-3, 3), 4),
            round(random.uniform(-3, 3), 4),
            round(random.uniform(-3, 3), 4),
        )

    try:
        if _vibration_device is None:
            import board
            import busio
            import adafruit_adxl34x
            i2c = busio.I2C(board.SCL, board.SDA)
            _vibration_device = adafruit_adxl34x.ADXL345(i2c)
            logger.info("ADXL345 initialized on I2C")

        x, y, z = _vibration_device.acceleration
        _last_readings["vib_x"] = x
        _last_readings["vib_y"] = y
        _last_readings["vib_z"] = z
        return float(x), float(y), float(z)
    except Exception as e:
        logger.warning("ADXL345 read failed: %s", e)
        _vibration_device = None
        return _last_readings["vib_x"], _last_readings["vib_y"], _last_readings["vib_z"]


def get_smoke() -> bool:
    """Read smoke/gas from MQ2 on GPIO 11. Returns True if smoke detected."""
    if SIMULATION_MODE:
        import random
        return random.choice([True, False])

    _init_gpio()
    try:
        import RPi.GPIO as GPIO
        # MQ2: 0 = gas detected, 1 = clean
        val = GPIO.input(11)
        result = val == 0
        _last_readings["smoke"] = result
        return result
    except Exception:
        return _last_readings["smoke"]


def get_sound() -> bool:
    """Read sound from KY-038 microphone on GPIO 17. Returns True if sound detected."""
    if SIMULATION_MODE:
        import random
        return random.choice([True, False])

    _init_gpio()
    try:
        import RPi.GPIO as GPIO
        val = GPIO.input(17)
        result = bool(val)
        _last_readings["sound"] = result
        return result
    except Exception:
        return _last_readings["sound"]


def get_current() -> float:
    """Read current (A). Requires ADC — returns 0.0 if not connected."""
    if SIMULATION_MODE:
        import random
        return round(random.uniform(2.0, 14.0), 3)
    # ACS712 needs ADC (MCP3008) — not connected yet
    return 0.0


def read_all_sensors() -> dict[str, Any]:
    """
    Read all sensors and return structured telemetry dict.
    This is the main function called by the collector loop.
    """
    temp, hum = get_temp_humidity()
    if temp is None:
        temp = _last_readings["temperature"]
    if hum is None:
        hum = _last_readings["humidity"]

    vib_x, vib_y, vib_z = get_vibration()
    magnitude = round(math.sqrt(vib_x**2 + vib_y**2 + vib_z**2), 3)

    smoke = get_smoke()
    sound = get_sound()
    current = get_current()

    return {
        "timestamp": int(time.time()),
        "device_id": os.environ.get("EDGE_DEVICE_ID", "MOTOR_001"),
        "telemetry": {
            "temperature": round(temp, 1),
            "humidity": round(hum, 1),
            "current": round(current, 3),
            "vibration": {
                "x": round(vib_x, 4),
                "y": round(vib_y, 4),
                "z": round(vib_z, 4),
                "magnitude": magnitude,
            },
            "smoke": smoke,
            "sound": sound,
        },
    }


class SensorCollector:
    """Aggregates sensor readings and publishes to MQTT at fixed intervals."""

    def __init__(
        self,
        device_id: str = "MOTOR_001",
        site_id: str = "SITE_001",
        interval_seconds: float = 5.0,
    ):
        self.device_id = device_id
        self.site_id = site_id
        self.interval = interval_seconds
        self._running = False
        self._read_count = 0

    def initialize_all(self) -> dict[str, bool]:
        """Initialize all sensors. Returns status per sensor."""
        os.environ["EDGE_DEVICE_ID"] = self.device_id
        status = {}

        # DHT11
        t, h = get_temp_humidity()
        status["dht11"] = t is not None

        # ADXL345
        try:
            vx, vy, vz = get_vibration()
            status["adxl345"] = not (vx == 0 and vy == 0 and vz == 0)
        except Exception:
            status["adxl345"] = False

        # MQ2
        try:
            get_smoke()
            status["mq2"] = _gpio_initialized or SIMULATION_MODE
        except Exception:
            status["mq2"] = False

        # Microphone
        try:
            get_sound()
            status["microphone"] = _gpio_initialized or SIMULATION_MODE
        except Exception:
            status["microphone"] = False

        active = sum(1 for v in status.values() if v)
        logger.info("Sensors initialized: %d/4 active", active)
        return status

    async def publish_loop(self, mqtt_host: str = "localhost", mqtt_port: int = 1883) -> None:
        """Read sensors, publish to MQTT, and push to DynamoDB + live store."""
        import aiomqtt
        from edge_platform.api.routes.live_store import update_reading
        from edge_platform.cloud.dynamo_store import put_telemetry

        topic = f"iiot/site/{self.site_id}/device/{self.device_id}/telemetry"
        self._running = True

        logger.info("Sensor collector: device=%s, interval=%.1fs, topic=%s", self.device_id, self.interval, topic)

        async with aiomqtt.Client(hostname=mqtt_host, port=mqtt_port) as client:
            while self._running:
                try:
                    reading = read_all_sensors()
                    reading["device_id"] = self.device_id
                    telemetry = reading.get("telemetry", {})
                    timestamp = reading.get("timestamp", int(time.time()))

                    # 1. Publish to MQTT (for stream processor / other subscribers)
                    payload = json.dumps(reading)
                    await client.publish(topic, payload=payload, qos=1)

                    # 2. Push directly to in-memory live store (for local dashboard)
                    try:
                        update_reading(self.device_id, timestamp, telemetry)
                    except Exception:
                        pass

                    # 3. Push directly to DynamoDB (for cloud dashboard)
                    try:
                        put_telemetry(self.device_id, timestamp, telemetry)
                    except Exception as e:
                        if self._read_count % 12 == 0:
                            logger.warning("DynamoDB push: %s", e)

                    self._read_count += 1

                    if self._read_count % 12 == 0:
                        logger.info("Published %d readings (MQTT + DynamoDB)", self._read_count)
                except Exception as e:
                    logger.error("Sensor publish error: %s", e)

                await asyncio.sleep(self.interval)

    def stop(self):
        self._running = False

    def cleanup(self):
        """Release GPIO."""
        if SIMULATION_MODE:
            return
        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup()
        except Exception:
            pass
