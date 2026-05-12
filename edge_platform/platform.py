"""
Platform orchestrator.
Wires all components together and manages the application lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from typing import Any

import orjson

from edge_platform.ai.pipeline import InferencePipeline
from edge_platform.api.routes.websocket import broadcast_alert, broadcast_inference, broadcast_telemetry
from edge_platform.api.routes.live_store import update_reading
from edge_platform.cloud.dynamo_store import put_telemetry as dynamo_put
from edge_platform.config import PlatformConfig, get_config
from edge_platform.events.alert_engine import AlertEngine
from edge_platform.events.correlator import EventCorrelator
from edge_platform.features.extractor import FeatureExtractor
from edge_platform.health.monitor import EdgeHealthMonitor
from edge_platform.models.events import Alert
from edge_platform.models.telemetry import TelemetryMessage
from edge_platform.mqtt.client import MQTTClient
from edge_platform.mqtt.topics import TopicBuilder
from edge_platform.storage.archiver import DataArchiver
from edge_platform.storage.sqlite_store import SQLiteStore
from edge_platform.stream.processor import StreamProcessor

logger = logging.getLogger(__name__)


class EdgePlatform:
    """
    Main platform orchestrator.
    
    Manages the lifecycle of all components and wires them together:
    MQTT → Stream Processor → Feature Extractor → AI Pipeline → Events → Alerts
    """

    def __init__(self, config: PlatformConfig):
        self.config = config
        self.topics = TopicBuilder(prefix="iiot", site_id=config.site_id)
        
        # Core components
        self.mqtt_client = MQTTClient(config.mqtt)
        self.storage = SQLiteStore(config.storage.sqlite)
        self.stream_processor = StreamProcessor(config)
        self.feature_extractor = FeatureExtractor(config.inference)
        self.inference_pipeline = InferencePipeline(config.inference, self.feature_extractor)
        self.event_correlator = EventCorrelator()
        self.alert_engine = AlertEngine(config.alerts)
        self.health_monitor = EdgeHealthMonitor(config.health)
        self.archiver = DataArchiver(
            config.storage.sqlite.path,
            config.storage.parquet,
            config.retention,
        )
        
        # Scheduler tasks
        self._scheduler_tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        """Start all platform components in correct order."""
        logger.info("=" * 60)
        logger.info("  InductIQ Platform v%s", self.config.version)
        logger.info("  Site: %s", self.config.site_id)
        logger.info("=" * 60)
        
        self._running = True
        
        # 1. Initialize storage
        await self.storage.initialize()
        logger.info("✓ Storage initialized")
        
        # 2. Initialize AI pipeline
        await self.inference_pipeline.initialize()
        logger.info("✓ AI pipeline initialized")
        
        # 3. Wire stream processor consumers
        self.stream_processor.add_consumer(self._on_telemetry)
        await self.stream_processor.start()
        logger.info("✓ Stream processor started")
        
        # 4. Start MQTT client (connects to broker for real sensor data)
        self.mqtt_client.subscribe(
            self.topics.all_device_telemetry(),
            self.stream_processor.ingest,
        )
        await self.mqtt_client.start()
        logger.info("✓ MQTT client connected — listening for sensor data")
        
        # 5. Start health monitor
        self.health_monitor.set_alert_callback(self._on_health_alert)
        await self.health_monitor.start()
        logger.info("✓ Health monitor started")
        
        # 6. Set up alert callbacks
        self.alert_engine.add_callback(self._on_alert_fired)
        
        # 7. Start scheduled tasks
        self._start_schedulers()
        logger.info("✓ Schedulers started")
        
        logger.info("Platform fully operational")

    async def stop(self) -> None:
        """Gracefully stop all components."""
        logger.info("Platform shutting down...")
        self._running = False
        
        # Cancel schedulers
        for task in self._scheduler_tasks:
            task.cancel()
        
        # Stop components in reverse order
        await self.health_monitor.stop()
        try:
            await self.mqtt_client.stop()
        except Exception:
            pass
        await self.stream_processor.stop()
        await self.storage.close()
        
        logger.info("Platform shutdown complete")

    async def _on_telemetry(self, message: TelemetryMessage) -> None:
        """
        Process a validated telemetry message through the full pipeline.
        This is the main data flow callback.
        """
        telemetry_dict = message.telemetry.model_dump(exclude_none=True)
        logger.info("Processing telemetry: device=%s temp=%.1f",
                    message.device_id, message.telemetry.temperature or 0)

        # 0. Update in-memory live store (instant access for dashboard)
        update_reading(message.device_id, message.timestamp, telemetry_dict)

        # 0b. Push to DynamoDB (cloud store for dashboard)
        try:
            dynamo_put(message.device_id, message.timestamp, telemetry_dict)
        except Exception as e:
            logger.warning("DynamoDB push failed: %s", e)

        # 1. Store telemetry to DB (for history)
        rows = message.to_storage_rows()
        await self.storage.insert_telemetry(rows)

        # 2. Update feature extractor
        self.feature_extractor.update(message)

        # 3. Run AI inference (rate-limited per device)
        result = await self.inference_pipeline.process(message)

        if result:
            # 4. Store inference result
            await self.storage.insert_inference({
                "timestamp": result.timestamp,
                "device_id": result.device_id,
                "fault_class": result.fault_class.value,
                "confidence": result.confidence,
                "health_score": result.health_scores.overall,
                "scores_json": orjson.dumps(result.health_scores.model_dump()).decode(),
                "rul_hours": result.rul_hours,
                "model_version": result.model_version,
            })

            # 5. Correlate events and generate alerts
            alerts = self.event_correlator.correlate_inference(result)
            if alerts:
                fired = await self.alert_engine.process_alerts(alerts)
                for alert in fired:
                    await self.storage.insert_alert({
                        "alert_id": alert.id,
                        "timestamp": alert.timestamp,
                        "device_id": alert.device_id,
                        "severity": alert.severity.value,
                        "alert_type": alert.alert_type.value,
                        "message": alert.message,
                        "metadata_json": orjson.dumps(alert.metadata).decode(),
                    })

            # 6. Broadcast inference to WebSocket clients
            await broadcast_inference(result.model_dump())

        # 7. Broadcast telemetry to WebSocket clients
        await broadcast_telemetry({
            "timestamp": message.timestamp,
            "device_id": message.device_id,
            "telemetry": telemetry_dict,
        })

    async def _on_alert_fired(self, alert: Alert) -> None:
        """Callback when an alert is fired."""
        # Publish to MQTT
        topic = self.topics.device_alerts(alert.device_id)
        await self.mqtt_client.publish(topic, alert.model_dump())
        
        # Broadcast to WebSocket
        await broadcast_alert(alert.model_dump())
        
        # Critical alerts go to dedicated topic
        if alert.severity.value == "CRITICAL":
            await self.mqtt_client.publish(
                self.topics.device_alerts_critical(alert.device_id),
                alert.model_dump(),
            )

    async def _on_health_alert(self, alert: Alert) -> None:
        """Callback for health monitor alerts."""
        fired = await self.alert_engine.process_alerts([alert])
        for a in fired:
            await self.storage.insert_alert({
                "alert_id": a.id,
                "timestamp": a.timestamp,
                "device_id": a.device_id,
                "severity": a.severity.value,
                "alert_type": a.alert_type.value,
                "message": a.message,
                "metadata_json": orjson.dumps(a.metadata).decode(),
            })

    def _start_schedulers(self) -> None:
        """Start periodic background tasks."""
        self._scheduler_tasks.append(
            asyncio.create_task(self._archival_scheduler())
        )
        self._scheduler_tasks.append(
            asyncio.create_task(self._health_storage_scheduler())
        )
        self._scheduler_tasks.append(
            asyncio.create_task(self._cleanup_scheduler())
        )

    async def _archival_scheduler(self) -> None:
        """Periodic data archival (hourly)."""
        while self._running:
            await asyncio.sleep(self.config.retention.cleanup_interval_minutes * 60)
            try:
                stats = await self.archiver.run_archival_cycle()
                if any(v > 0 for v in stats.values()):
                    logger.info("Archival cycle: %s", stats)
            except Exception as e:
                logger.error("Archival error: %s", e)

    async def _health_storage_scheduler(self) -> None:
        """Store health snapshots periodically."""
        while self._running:
            await asyncio.sleep(self.config.health.monitor_interval_seconds)
            try:
                health = self.health_monitor.get_latest_health()
                if health:
                    await self.storage.insert_health({
                        "timestamp": health.timestamp,
                        "cpu_percent": health.cpu_percent,
                        "ram_percent": health.ram_percent,
                        "disk_percent": health.disk_percent,
                        "temperature": health.temperature_celsius,
                        "mqtt_latency_ms": health.mqtt_latency_ms,
                        "process_count": health.process_count,
                    })
            except Exception as e:
                logger.error("Health storage error: %s", e)

    async def _cleanup_scheduler(self) -> None:
        """Periodic cleanup of old data."""
        while self._running:
            await asyncio.sleep(3600)  # Every hour
            try:
                deleted = await self.storage.cleanup_old_data(self.config.retention.hot_hours)
                if deleted > 0:
                    logger.info("Cleaned %d old records from hot storage", deleted)
                
                # Clean stale alerts
                stale = await self.alert_engine.cleanup_stale()
                if stale > 0:
                    logger.info("Cleaned %d stale alerts", stale)
            except Exception as e:
                logger.error("Cleanup error: %s", e)
