"""
Stream processor - async telemetry ingestion pipeline.
Consumes MQTT messages, validates, batches, and routes to downstream consumers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Callable, Coroutine

import orjson

from edge_platform.config import PlatformConfig
from edge_platform.models.telemetry import TelemetryMessage, TelemetryPayload

logger = logging.getLogger(__name__)

# Type for downstream consumers
Consumer = Callable[[TelemetryMessage], Coroutine[Any, Any, None]]


class StreamProcessor:
    """
    Async stream processor for telemetry data.
    
    Features:
    - Bounded async queue with backpressure
    - Batch processing for efficiency
    - Validation and filtering
    - Multiple downstream consumers
    - Rate limiting
    - Metrics collection
    """

    def __init__(self, config: PlatformConfig, max_queue_size: int = 100):
        self._config = config
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue_size)
        self._consumers: list[Consumer] = []
        self._running = False
        self._worker_task: asyncio.Task | None = None
        self._batch_buffer: deque[TelemetryMessage] = deque(maxlen=config.inference.batch_size)
        
        # Metrics
        self._messages_received = 0
        self._messages_processed = 0
        self._messages_dropped = 0
        self._errors = 0
        self._last_message_time: float = 0

    def add_consumer(self, consumer: Consumer) -> None:
        """Register a downstream consumer for processed telemetry."""
        self._consumers.append(consumer)

    async def start(self) -> None:
        """Start the stream processor worker."""
        self._running = True
        self._worker_task = asyncio.create_task(self._process_loop())
        logger.info("Stream processor started (queue_size=%d)", self._queue.maxsize)

    async def stop(self) -> None:
        """Stop the stream processor gracefully."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info(
            "Stream processor stopped. Processed=%d, Dropped=%d, Errors=%d",
            self._messages_processed,
            self._messages_dropped,
            self._errors,
        )

    async def ingest(self, topic: str, payload: dict[str, Any]) -> None:
        """
        Ingest a raw MQTT message into the processing queue.
        Drops messages if queue is full (backpressure).
        """
        self._messages_received += 1
        
        try:
            self._queue.put_nowait({"topic": topic, "payload": payload})
        except asyncio.QueueFull:
            self._messages_dropped += 1
            if self._messages_dropped % 100 == 0:
                logger.warning(
                    "Stream queue full, dropped %d messages total",
                    self._messages_dropped,
                )

    async def _process_loop(self) -> None:
        """Main processing loop - consumes from queue and dispatches."""
        while self._running:
            try:
                # Get message with timeout to allow graceful shutdown
                try:
                    raw = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # Parse and validate
                message = self._parse_message(raw)
                if message is None:
                    logger.warning("Failed to parse message from queue")
                    continue
                
                # Dispatch to all consumers
                await self._dispatch(message)
                
                self._messages_processed += 1
                self._last_message_time = time.time()
                
                if self._messages_processed % 10 == 1:
                    logger.info("Stream processed %d messages (queue=%d)",
                                self._messages_processed, self._queue.qsize())
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._errors += 1
                logger.error("Stream processing error: %s", e, exc_info=True)

    def _parse_message(self, raw: dict[str, Any]) -> TelemetryMessage | None:
        """Parse and validate a raw message into a TelemetryMessage."""
        try:
            payload = raw.get("payload", {})
            topic = raw.get("topic", "")
            
            # Extract device_id from MQTT topic: iiot/device/{device_id}/telemetry
            device_id = payload.get("device_id")
            if not device_id:
                parts = topic.split("/")
                # Look for "device" segment and take the next part as device_id
                for i, part in enumerate(parts):
                    if part == "device" and i + 1 < len(parts):
                        device_id = parts[i + 1]
                        break
                if not device_id:
                    device_id = "UNKNOWN"
            
            # Handle both flat and nested telemetry formats
            if "telemetry" in payload:
                telemetry_data = payload["telemetry"]
            else:
                # Payload IS the telemetry (flat sensor data like {"temperature":65.2,"vibration":2.8})
                telemetry_data = {
                    k: v for k, v in payload.items()
                    if k not in ("timestamp", "device_id", "site_id", "sequence", "metadata")
                }
            
            telemetry = TelemetryPayload(**telemetry_data)
            
            # Compute vibration magnitude if not provided
            if telemetry.vibration and telemetry.vibration.magnitude is None:
                telemetry.vibration.compute_magnitude()
            
            message = TelemetryMessage(
                timestamp=payload.get("timestamp", int(time.time())),
                device_id=device_id,
                site_id=payload.get("site_id", self._config.site_id),
                telemetry=telemetry,
                sequence=payload.get("sequence"),
                metadata=payload.get("metadata"),
            )
            
            return message
            
        except Exception as e:
            self._errors += 1
            logger.debug("Failed to parse telemetry message: %s", e)
            return None

    async def _dispatch(self, message: TelemetryMessage) -> None:
        """Dispatch a validated message to all registered consumers."""
        for consumer in self._consumers:
            try:
                await consumer(message)
            except Exception as e:
                logger.error("Consumer error: %s", e, exc_info=True)

    def get_stats(self) -> dict[str, Any]:
        """Get processor statistics."""
        return {
            "queue_size": self._queue.qsize(),
            "queue_max": self._queue.maxsize,
            "messages_received": self._messages_received,
            "messages_processed": self._messages_processed,
            "messages_dropped": self._messages_dropped,
            "errors": self._errors,
            "consumers": len(self._consumers),
            "last_message_time": self._last_message_time,
        }
