"""
Async MQTT client for the Edge AI platform.
Handles connection management, message routing, and buffering.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Callable, Coroutine

import aiomqtt
import orjson

from edge_platform.config import MQTTConfig

logger = logging.getLogger(__name__)

# Type alias for message handlers
MessageHandler = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class MQTTClient:
    """
    Async MQTT client with automatic reconnection and message buffering.
    
    Designed for industrial reliability:
    - Automatic reconnection with exponential backoff
    - Message buffering during disconnects
    - Topic-based message routing
    - QoS management
    """

    def __init__(self, config: MQTTConfig):
        self.config = config
        self._client: aiomqtt.Client | None = None
        self._connected = False
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._buffer: deque[tuple[str, bytes]] = deque(maxlen=config.buffer_size)
        self._reconnect_task: asyncio.Task | None = None
        self._listener_task: asyncio.Task | None = None
        self._running = False
        self._last_publish_time: float = 0
        self._publish_count: int = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    async def start(self) -> None:
        """Start the MQTT client and begin listening."""
        self._running = True
        try:
            await self._connect()
        except Exception as e:
            logger.warning("MQTT initial connection failed: %s (will retry in background)", e)
            self._reconnect_task = asyncio.create_task(self._reconnect())
            return
        logger.info(
            "MQTT client started, broker=%s:%d",
            self.config.broker_host,
            self.config.broker_port,
        )

    async def stop(self) -> None:
        """Gracefully stop the MQTT client."""
        self._running = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        self._connected = False
        logger.info("MQTT client stopped")

    async def _connect(self) -> None:
        """Establish connection to MQTT broker."""
        try:
            self._client = aiomqtt.Client(
                hostname=self.config.broker_host,
                port=self.config.broker_port,
                keepalive=self.config.keepalive,
            )
            await self._client.__aenter__()
            self._connected = True
            
            # Subscribe to registered topics
            for topic in self._handlers:
                await self._client.subscribe(topic, qos=self.config.qos)
            
            # Start listener
            self._listener_task = asyncio.create_task(self._listen())
            
            # Flush buffer
            await self._flush_buffer()
            
            logger.info("MQTT connected to %s:%d", self.config.broker_host, self.config.broker_port)
            
        except Exception as e:
            logger.error("MQTT connection failed: %s", e)
            self._connected = False
            if self._running:
                self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        delay = self.config.reconnect_interval
        attempts = 0
        max_delay = 60

        while self._running and not self._connected:
            logger.info("MQTT reconnecting in %ds (attempt %d)...", delay, attempts + 1)
            await asyncio.sleep(delay)
            
            try:
                await self._connect()
                if self._connected:
                    logger.info("MQTT reconnected after %d attempts", attempts + 1)
                    return
            except Exception as e:
                logger.warning("MQTT reconnect failed: %s", e)
            
            attempts += 1
            delay = min(delay * 2, max_delay)

    async def _listen(self) -> None:
        """Listen for incoming messages and route to handlers."""
        try:
            async with self._client.messages() as messages:
                async for message in messages:
                    topic = str(message.topic)
                    try:
                        payload = orjson.loads(message.payload)
                    except (orjson.JSONDecodeError, TypeError):
                        payload = {"raw": message.payload.decode("utf-8", errors="replace")}
                    
                    logger.info("MQTT received: %s", topic)
                    await self._dispatch(topic, payload)
                    
        except aiomqtt.MqttError as e:
            logger.error("MQTT listener error: %s", e)
            self._connected = False
            if self._running:
                self._reconnect_task = asyncio.create_task(self._reconnect())
        except asyncio.CancelledError:
            pass

    async def _dispatch(self, topic: str, payload: dict[str, Any]) -> None:
        """Dispatch message to registered handlers."""
        for pattern, handlers in self._handlers.items():
            if self._topic_matches(pattern, topic):
                for handler in handlers:
                    try:
                        await handler(topic, payload)
                    except Exception as e:
                        logger.error(
                            "Handler error for topic %s: %s", topic, e, exc_info=True
                        )

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        """Register a handler for a topic pattern."""
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)
        logger.debug("Registered handler for topic: %s", topic)

    async def publish(self, topic: str, payload: dict[str, Any], qos: int | None = None) -> None:
        """
        Publish a message. Buffers if disconnected.
        
        Args:
            topic: MQTT topic
            payload: Message payload (will be serialized to JSON)
            qos: QoS level (defaults to config)
        """
        data = orjson.dumps(payload)
        
        if not self._connected or self._client is None:
            self._buffer.append((topic, data))
            return
        
        try:
            await self._client.publish(
                topic,
                payload=data,
                qos=qos or self.config.qos,
            )
            self._last_publish_time = time.time()
            self._publish_count += 1
        except Exception as e:
            logger.warning("MQTT publish failed, buffering: %s", e)
            self._buffer.append((topic, data))

    async def _flush_buffer(self) -> None:
        """Flush buffered messages after reconnection."""
        if not self._buffer:
            return
        
        count = len(self._buffer)
        logger.info("Flushing %d buffered MQTT messages", count)
        
        while self._buffer and self._connected:
            topic, data = self._buffer.popleft()
            try:
                await self._client.publish(topic, payload=data, qos=self.config.qos)
            except Exception as e:
                # Put it back and stop flushing
                self._buffer.appendleft((topic, data))
                logger.warning("Buffer flush interrupted: %s", e)
                break
        
        flushed = count - len(self._buffer)
        if flushed > 0:
            logger.info("Flushed %d/%d buffered messages", flushed, count)

    @staticmethod
    def _topic_matches(pattern: str, topic: str) -> bool:
        """Check if a topic matches a subscription pattern (supports + and #)."""
        pattern_parts = pattern.split("/")
        topic_parts = topic.split("/")
        
        for i, part in enumerate(pattern_parts):
            if part == "#":
                return True
            if i >= len(topic_parts):
                return False
            if part != "+" and part != topic_parts[i]:
                return False
        
        return len(pattern_parts) == len(topic_parts)

    def get_stats(self) -> dict[str, Any]:
        """Get client statistics."""
        return {
            "connected": self._connected,
            "buffer_size": len(self._buffer),
            "publish_count": self._publish_count,
            "last_publish": self._last_publish_time,
            "subscriptions": list(self._handlers.keys()),
        }
