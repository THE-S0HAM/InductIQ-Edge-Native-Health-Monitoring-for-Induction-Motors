"""
DynamoDB cloud store for sensor telemetry.
Pi pushes latest readings here; dashboard fetches from here.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Table name
TABLE_NAME = "edge_telemetry_live"


def get_dynamodb_resource():
    """Get DynamoDB resource using default credentials (env vars or IAM role)."""
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region)


def get_dynamodb_client():
    """Get DynamoDB client."""
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    return boto3.client("dynamodb", region_name=region)


def create_table_if_not_exists():
    """Create the DynamoDB table if it doesn't exist."""
    client = get_dynamodb_client()

    try:
        client.describe_table(TableName=TABLE_NAME)
        logger.info("DynamoDB table '%s' already exists", TABLE_NAME)
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    logger.info("Creating DynamoDB table '%s'...", TABLE_NAME)
    client.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "device_id", "KeyType": "HASH"},   # Partition key
            {"AttributeName": "timestamp", "KeyType": "RANGE"},   # Sort key
        ],
        AttributeDefinitions=[
            {"AttributeName": "device_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "N"},
        ],
        BillingMode="PAY_PER_REQUEST",  # On-demand — no capacity planning
    )

    # Wait for table to be active
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=TABLE_NAME)
    logger.info("DynamoDB table '%s' created", TABLE_NAME)


def put_telemetry(device_id: str, timestamp: int, telemetry: dict[str, Any]) -> bool:
    """
    Write a single telemetry reading to DynamoDB.
    Called by the Pi every time sensor data is collected.
    """
    try:
        table = get_dynamodb_resource().Table(TABLE_NAME)

        # Flatten vibration for DynamoDB (no nested dicts with floats)
        item: dict[str, Any] = {
            "device_id": device_id,
            "timestamp": timestamp,
            "temperature": _to_decimal(telemetry.get("temperature")),
            "humidity": _to_decimal(telemetry.get("humidity")),
            "current": _to_decimal(telemetry.get("current")),
            "smoke": telemetry.get("smoke", False),
            "sound": telemetry.get("sound", False),
            # TTL: auto-delete after 1 hour (keeps table small)
            "ttl": timestamp + 3600,
        }

        # Vibration as nested map
        vib = telemetry.get("vibration")
        if vib and isinstance(vib, dict):
            item["vib_x"] = _to_decimal(vib.get("x"))
            item["vib_y"] = _to_decimal(vib.get("y"))
            item["vib_z"] = _to_decimal(vib.get("z"))
            item["vib_magnitude"] = _to_decimal(vib.get("magnitude"))

        # Remove None values
        item = {k: v for k, v in item.items() if v is not None}

        table.put_item(Item=item)
        return True

    except Exception as e:
        logger.error("DynamoDB put_item failed: %s", e)
        return False


def get_latest_reading(device_id: str) -> dict[str, Any] | None:
    """
    Get the most recent telemetry reading for a device.
    Used by the dashboard API endpoint.
    """
    try:
        table = get_dynamodb_resource().Table(TABLE_NAME)

        response = table.query(
            KeyConditionExpression="device_id = :did",
            ExpressionAttributeValues={":did": device_id},
            ScanIndexForward=False,  # Descending (latest first)
            Limit=1,
        )

        items = response.get("Items", [])
        if not items:
            return None

        item = items[0]
        return _item_to_telemetry(item)

    except Exception as e:
        logger.error("DynamoDB query failed: %s", e)
        return None


def get_recent_readings(device_id: str, seconds: int = 300) -> list[dict[str, Any]]:
    """
    Get readings from the last N seconds for a device.
    Used for chart history on dashboard load.
    """
    try:
        table = get_dynamodb_resource().Table(TABLE_NAME)
        cutoff = int(time.time()) - seconds

        response = table.query(
            KeyConditionExpression="device_id = :did AND #ts >= :cutoff",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={
                ":did": device_id,
                ":cutoff": cutoff,
            },
            ScanIndexForward=True,  # Ascending (oldest first for charts)
        )

        return [_item_to_telemetry(item) for item in response.get("Items", [])]

    except Exception as e:
        logger.error("DynamoDB query failed: %s", e)
        return []


def get_all_devices_latest() -> dict[str, Any]:
    """
    Get latest reading for all known devices.
    Scans for unique device_ids and gets their latest.
    """
    devices = {}
    for device_id in ["MOTOR_001", "MOTOR_002", "PUMP_001"]:
        reading = get_latest_reading(device_id)
        if reading:
            devices[device_id] = {
                "status": "live" if (time.time() - reading["timestamp"]) < 30 else "stale",
                "timestamp": reading["timestamp"],
                "age_seconds": round(time.time() - reading["timestamp"], 1),
                "telemetry": reading["telemetry"],
            }
        else:
            devices[device_id] = {"status": "offline", "telemetry": {}}

    return {
        "timestamp": int(time.time()),
        "devices": devices,
        "device_count": len(devices),
        "live_count": sum(1 for d in devices.values() if d.get("status") == "live"),
    }


def _to_decimal(value) -> Any:
    """Convert float to Decimal-safe string for DynamoDB."""
    if value is None:
        return None
    from decimal import Decimal
    return Decimal(str(round(value, 4)))


def _item_to_telemetry(item: dict) -> dict[str, Any]:
    """Convert a DynamoDB item back to telemetry format."""
    telemetry: dict[str, Any] = {}

    if "temperature" in item:
        telemetry["temperature"] = float(item["temperature"])
    if "humidity" in item:
        telemetry["humidity"] = float(item["humidity"])
    if "current" in item:
        telemetry["current"] = float(item["current"])
    if "smoke" in item:
        telemetry["smoke"] = bool(item["smoke"])
    if "sound" in item:
        telemetry["sound"] = bool(item["sound"])

    # Reconstruct vibration
    if "vib_x" in item:
        telemetry["vibration"] = {
            "x": float(item.get("vib_x", 0)),
            "y": float(item.get("vib_y", 0)),
            "z": float(item.get("vib_z", 0)),
            "magnitude": float(item.get("vib_magnitude", 0)),
        }

    return {
        "timestamp": int(item["timestamp"]),
        "device_id": item["device_id"],
        "telemetry": telemetry,
    }
