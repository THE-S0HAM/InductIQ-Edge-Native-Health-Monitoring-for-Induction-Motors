# InduxSense — AI-Powered Induction Motor Monitoring System

### Industrial IoT Edge Monitoring Platform

> Real-time sensor telemetry, AI-based fault detection, and cloud-synced dashboard — built for Raspberry Pi.

---

## What is InduxSense?

InduxSense is an edge-native Industrial IoT platform that collects sensor data from physical hardware (motors, pumps, machines), runs AI inference locally on a Raspberry Pi, and streams live data to a web dashboard backed by AWS DynamoDB.

Built as a final-year engineering project to demonstrate end-to-end IIoT architecture — from GPIO sensors to cloud storage to a live browser dashboard.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Raspberry Pi (Edge)                   │
│                                                          │
│  DHT11 ──┐                                               │
│  ADXL345 ┼──► Sensor Collector ──► MQTT Broker          │
│  MQ2 ────┘         │                    │               │
│  KY-038 ──         │                    ▼               │
│                     │           Stream Processor         │
│                     │                  │                 │
│                     │           AI Inference Pipeline    │
│                     │           (fault detection, RUL)   │
│                     │                  │                 │
│                     ▼                  ▼                 │
│              DynamoDB Push ◄──── Platform Core           │
│              (every 5s)         FastAPI + WebSocket      │
└─────────────────────────────────────────────────────────┘
                    │
                    ▼
           AWS DynamoDB (cloud)
                    │
                    ▼
         Browser Dashboard (polls every 3s)
         Live charts, AI status, alerts
```

---

## Hardware

| Component | Purpose | Interface |
|-----------|---------|-----------|
| Raspberry Pi 3B+ | Edge compute | — |
| DHT11 | Temperature + Humidity | GPIO D4 |
| ADXL345 | 3-axis Vibration | I2C |
| MQ2 | Smoke / Gas detection | GPIO 11 |
| KY-038 | Sound detection | GPIO 17 |

---

## Features

- **Live sensor dashboard** — temperature, humidity, vibration, current, smoke, sound
- **AI inference pipeline** — statistical anomaly → ML fault classification → predictive RUL
- **AWS DynamoDB sync** — sensor data pushed to cloud every 5 seconds
- **WebSocket streaming** — real-time push to browser
- **Alert engine** — threshold-based alerts with severity levels
- **Edge health monitor** — CPU, RAM, disk, temperature of the Pi
- **SQLite hot store** — local data persistence for history and AI features
- **One-command startup** — `python run.py` handles everything

---

## Quick Start

### Prerequisites

- Raspberry Pi 3B+ running Raspberry Pi OS (64-bit)
- Python 3.11+
- Mosquitto MQTT broker: `sudo apt install mosquitto mosquitto-clients`
- AWS account with DynamoDB access

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/your-username/InduxSense.git
cd InduxSense

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate

# 3. Configure environment
cp .env.example .env
nano .env   # fill in your API key and AWS credentials

# 4. Start Mosquitto
sudo systemctl start mosquitto

# 5. Run
python run.py
```

Dashboard opens at: **http://localhost:8420**

---

## Configuration

All configuration is via environment variables in `.env`:

```env
EDGE_API_KEY=your-strong-api-key-here
AWS_ACCESS_KEY_ID=your-access-key-id
AWS_SECRET_ACCESS_KEY=your-secret-access-key
AWS_DEFAULT_REGION=us-east-1
```

See `.env.example` for all available options.

---

## AWS DynamoDB Setup

The platform auto-creates the `edge_telemetry_live` table on first run.

Your IAM user needs this policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:CreateTable",
      "dynamodb:DescribeTable"
    ],
    "Resource": "arn:aws:dynamodb:*:*:table/edge_telemetry_live"
  }]
}
```

---

## Project Structure

```
InduxSense/
├── run.py                        # One-click launcher
├── edge_platform/
│   ├── sensors/collector.py      # GPIO sensor reading + MQTT publish
│   ├── mqtt/client.py            # Async MQTT client
│   ├── stream/processor.py       # Message queue + validation
│   ├── ai/pipeline.py            # Multi-stage AI inference
│   ├── cloud/dynamo_store.py     # DynamoDB push/pull
│   ├── api/
│   │   ├── app.py                # FastAPI application
│   │   ├── routes/               # REST + WebSocket endpoints
│   │   └── templates/dashboard.html  # Live dashboard UI
│   ├── storage/sqlite_store.py   # Local SQLite hot store
│   ├── health/monitor.py         # Edge device health
│   └── events/alert_engine.py    # Alert generation
├── config/platform.yaml          # Platform configuration
├── tests/                        # Unit tests
└── deploy/                       # systemd service files
```

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Live dashboard |
| `GET /api/v1/cloud/telemetry/current` | Latest readings from DynamoDB |
| `GET /api/v1/telemetry/current` | Latest readings from memory |
| `GET /api/v1/health/edge` | Pi CPU/RAM/disk/temp |
| `GET /api/v1/inference/{device_id}` | Latest AI inference result |
| `GET /api/v1/alerts` | Active alerts |
| `WS /ws/telemetry` | Real-time WebSocket stream |

All endpoints require `X-API-Key` header (set in `.env`).

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Edge runtime | Python 3.11, asyncio |
| Web framework | FastAPI + Uvicorn |
| Messaging | Mosquitto + aiomqtt |
| Local storage | SQLite (WAL mode) |
| Cloud storage | AWS DynamoDB |
| AI/ML | scikit-learn |
| Dashboard | ECharts, vanilla JS |
| Deployment | systemd, Docker |

---

## License

This project is for **educational purposes only**.

```
Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software for personal, educational, and non-commercial use only.

Commercial use, redistribution, or use in production systems is not permitted
without explicit written permission from the author.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
```

---

*Built as a Third Year Engineering project — Industrial IoT (IIoT) domain.*
