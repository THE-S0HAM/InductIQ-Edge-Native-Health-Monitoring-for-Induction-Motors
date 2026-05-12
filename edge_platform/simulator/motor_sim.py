"""
Industrial motor telemetry simulator.
Generates realistic sensor data for development and testing.
Simulates normal operation, degradation, and fault conditions.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from typing import Any

import orjson

logger = logging.getLogger(__name__)


class MotorSimulator:
    """
    Simulates an industrial motor with realistic telemetry patterns.
    
    Supports:
    - Normal operation with natural variance
    - Gradual degradation over time
    - Fault injection (bearing wear, overheating, etc.)
    - Sensor noise and drift
    """

    def __init__(
        self,
        device_id: str = "MOTOR_001",
        site_id: str = "SITE_001",
        interval_seconds: float = 5.0,
    ):
        self.device_id = device_id
        self.site_id = site_id
        self.interval = interval_seconds
        
        # Base operating parameters
        self._base_temp = 55.0  # °C
        self._base_humidity = 40.0  # %
        self._base_current = 3.5  # A
        self._base_vibration = 1.5  # mm/s
        self._base_rpm = 1750.0
        
        # State
        self._health = 100.0
        self._degradation_rate = 0.001  # per reading
        self._fault_mode: str | None = None
        self._fault_severity = 0.0
        self._time_offset = 0
        self._sequence = 0

    def set_fault(self, fault_type: str, severity: float = 0.5) -> None:
        """Inject a fault condition."""
        self._fault_mode = fault_type
        self._fault_severity = min(max(severity, 0.0), 1.0)
        logger.info("Fault injected: %s (severity=%.2f)", fault_type, severity)

    def clear_fault(self) -> None:
        """Clear fault condition."""
        self._fault_mode = None
        self._fault_severity = 0.0

    def generate_reading(self) -> dict[str, Any]:
        """Generate a single telemetry reading."""
        self._sequence += 1
        self._time_offset += 1
        
        # Apply degradation
        self._health = max(0, self._health - self._degradation_rate)
        
        # Base values with natural variance
        temp = self._base_temp + random.gauss(0, 1.5)
        humidity = self._base_humidity + random.gauss(0, 2.0)
        current = self._base_current + random.gauss(0, 0.2)
        
        # Vibration with slight periodicity
        vib_base = self._base_vibration + 0.3 * math.sin(self._time_offset * 0.1)
        vib_x = vib_base + random.gauss(0, 0.3)
        vib_y = vib_base * 0.9 + random.gauss(0, 0.25)
        vib_z = random.gauss(0, 0.4)
        
        smoke = False
        sound = False
        
        # Apply fault effects
        if self._fault_mode:
            temp, humidity, current, vib_x, vib_y, vib_z, smoke, sound = (
                self._apply_fault(temp, humidity, current, vib_x, vib_y, vib_z)
            )
        
        # Compute vibration magnitude
        vib_magnitude = math.sqrt(vib_x**2 + vib_y**2 + vib_z**2)
        
        return {
            "timestamp": int(time.time()),
            "device_id": self.device_id,
            "site_id": self.site_id,
            "sequence": self._sequence,
            "telemetry": {
                "temperature": round(temp, 2),
                "humidity": round(humidity, 2),
                "current": round(current, 2),
                "vibration": {
                    "x": round(vib_x, 3),
                    "y": round(vib_y, 3),
                    "z": round(vib_z, 3),
                    "magnitude": round(vib_magnitude, 3),
                },
                "smoke": smoke,
                "sound": sound,
            },
        }

    def _apply_fault(
        self, temp, humidity, current, vib_x, vib_y, vib_z
    ) -> tuple:
        """Apply fault effects to sensor readings."""
        s = self._fault_severity
        smoke = False
        sound = False
        
        if self._fault_mode == "bearing_wear":
            vib_x += s * random.uniform(3, 8)
            vib_y += s * random.uniform(2, 6)
            temp += s * random.uniform(5, 15)
            sound = s > 0.6
            
        elif self._fault_mode == "overheating":
            temp += s * random.uniform(15, 40)
            current += s * random.uniform(0.5, 2.0)
            smoke = s > 0.7 and random.random() < 0.3
            
        elif self._fault_mode == "rotor_imbalance":
            # Periodic vibration pattern
            phase = self._time_offset * 0.5
            vib_x += s * 4 * math.sin(phase)
            vib_y += s * 4 * math.cos(phase)
            
        elif self._fault_mode == "shaft_misalignment":
            vib_x += s * random.uniform(2, 5)
            vib_y += s * random.uniform(2, 5)
            temp += s * random.uniform(5, 10)
            
        elif self._fault_mode == "electrical_arcing":
            current += s * random.uniform(2, 8)
            temp += s * random.uniform(3, 10)
            sound = s > 0.4
            
        elif self._fault_mode == "lubrication_failure":
            vib_x += s * random.uniform(1, 4)
            temp += s * random.uniform(8, 20)
            sound = s > 0.5
            
        elif self._fault_mode == "moisture_ingress":
            humidity += s * random.uniform(15, 35)
            current += s * random.uniform(0.3, 1.0)
            
        elif self._fault_mode == "loose_mounting":
            # Random vibration spikes
            if random.random() < s * 0.3:
                vib_x += random.uniform(5, 15)
                vib_z += random.uniform(3, 10)
            sound = s > 0.5
        
        return temp, humidity, current, vib_x, vib_y, vib_z, smoke, sound


async def run_simulator(
    mqtt_host: str = "localhost",
    mqtt_port: int = 1883,
    device_id: str = "MOTOR_001",
    interval: float = 5.0,
    fault_after: int | None = None,
    fault_type: str = "bearing_wear",
) -> None:
    """
    Run the simulator, publishing to MQTT.
    
    Args:
        mqtt_host: MQTT broker host
        mqtt_port: MQTT broker port
        device_id: Device ID to simulate
        interval: Seconds between readings
        fault_after: Inject fault after N readings (None = no fault)
        fault_type: Type of fault to inject
    """
    import aiomqtt
    
    sim = MotorSimulator(device_id=device_id, interval_seconds=interval)
    topic = f"iiot/site/SITE_001/device/{device_id}/telemetry"
    
    logger.info("Starting motor simulator: device=%s, interval=%.1fs", device_id, interval)
    
    async with aiomqtt.Client(hostname=mqtt_host, port=mqtt_port) as client:
        reading_count = 0
        
        while True:
            reading = sim.generate_reading()
            payload = orjson.dumps(reading)
            
            await client.publish(topic, payload=payload, qos=1)
            reading_count += 1
            
            if reading_count % 20 == 0:
                logger.info(
                    "Simulator: %d readings sent (health=%.1f%%)",
                    reading_count, sim._health,
                )
            
            # Inject fault after N readings
            if fault_after and reading_count == fault_after:
                sim.set_fault(fault_type, severity=0.6)
            
            await asyncio.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_simulator(fault_after=50, fault_type="bearing_wear"))
