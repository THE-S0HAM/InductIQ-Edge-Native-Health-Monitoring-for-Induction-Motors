# Architecture Documentation

## System Architecture

### Design Principles

1. **Event-Driven**: All data flows through MQTT pub/sub
2. **Async-First**: No blocking I/O anywhere in the pipeline
3. **Edge-Native**: Designed for constrained hardware from day one
4. **Fault-Tolerant**: Graceful degradation under resource pressure
5. **Storage-Efficient**: Tiered storage with automatic lifecycle
6. **AI-Ready**: Modular inference pipeline with hot-swap models
7. **Schema-Flexible**: Dynamic telemetry without schema migrations

### Data Flow

```
Sensors → MQTT Broker → Stream Processor → Feature Extractor
    → AI Inference → Event Correlator → Alert Engine → Dashboard/API
                                                    → Storage (Hot/Warm/Cold)
```

### Component Responsibilities

#### 1. Sensor Layer (`edge_platform/sensors/`)
- GPIO/I2C/SPI/Modbus sensor drivers
- Adaptive sampling rates
- Local buffering for network resilience
- Sensor health monitoring

#### 2. MQTT Communication (`edge_platform/mqtt/`)
- Mosquitto broker (local)
- Topic hierarchy management
- QoS level management
- Message buffering during disconnects
- Payload serialization (MessagePack for efficiency)

#### 3. Stream Processor (`edge_platform/stream/`)
- Async message consumption
- Bounded queues (backpressure)
- Telemetry validation
- Rate limiting
- Batch aggregation

#### 4. Feature Extraction (`edge_platform/features/`)
- Rolling statistics (mean, std, percentiles)
- Frequency domain features (FFT for vibration)
- Temporal features (trends, rates of change)
- Cross-sensor correlation features

#### 5. AI Inference (`edge_platform/ai/`)
- Stage 1: Statistical anomaly detection (z-score, IQR)
- Stage 2: Fault classification (RandomForest/LightGBM)
- Stage 3: Predictive maintenance (degradation curves, RUL)
- Stage 4: Unknown fault clustering (Isolation Forest)
- Model versioning and hot-reload

#### 6. Event Correlation (`edge_platform/events/`)
- Multi-signal correlation
- Temporal event grouping
- Root cause analysis
- Severity escalation logic

#### 7. Alert Engine (`edge_platform/alerts/`)
- Severity classification (INFO/WARNING/HIGH/CRITICAL)
- Deduplication with cooldown windows
- Escalation chains
- Alert suppression rules
- Notification dispatch

#### 8. Storage Layer (`edge_platform/storage/`)
- Hot: SQLite WAL mode (last 24h)
- Warm: DuckDB analytics (last 7 days)
- Cold: Parquet archives (compressed, rotated)
- Automatic retention policies

#### 9. Dashboard & API (`edge_platform/api/`)
- FastAPI REST endpoints
- WebSocket live telemetry
- HTMX server-rendered pages
- Alpine.js interactivity
- ECharts visualizations

#### 10. Device Registry (`edge_platform/registry/`)
- Dynamic device registration
- Sensor metadata management
- Calibration profiles
- Firmware version tracking
- Heartbeat monitoring

#### 11. Edge Health (`edge_platform/health/`)
- CPU/RAM/Disk monitoring
- Thermal management
- Process watchdog
- MQTT broker health
- Self-healing actions

---

## MQTT Topic Hierarchy

```
iiot/
├── site/{site_id}/
│   ├── device/{device_id}/
│   │   ├── telemetry          # Raw sensor data
│   │   ├── telemetry/batch    # Batched telemetry
│   │   ├── inference          # AI inference results
│   │   ├── inference/fault    # Fault classifications
│   │   ├── inference/rul      # RUL predictions
│   │   ├── alerts             # Alert notifications
│   │   ├── alerts/critical    # Critical alerts only
│   │   ├── health             # Device health status
│   │   ├── health/heartbeat   # Periodic heartbeat
│   │   ├── events             # General events
│   │   ├── events/maintenance # Maintenance events
│   │   ├── config             # Remote configuration
│   │   └── command            # Remote commands
│   ├── gateway/
│   │   ├── health             # Gateway health
│   │   └── discovery          # Device discovery
│   └── fleet/
│       ├── status             # Fleet-wide status
│       └── alerts             # Fleet-wide alerts
└── system/
    ├── health                 # Platform health
    └── config                 # System configuration
```

---

## Database Schema

### SQLite (Hot Storage)

```sql
-- Telemetry readings (circular buffer, last 24h)
CREATE TABLE telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    device_id TEXT NOT NULL,
    sensor_type TEXT NOT NULL,
    value_json TEXT NOT NULL,
    quality INTEGER DEFAULT 100,
    created_at INTEGER DEFAULT (strftime('%s','now'))
);

-- AI inference results
CREATE TABLE inference_results (
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

-- Active alerts
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    device_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    message TEXT,
    metadata_json TEXT,
    acknowledged INTEGER DEFAULT 0,
    resolved INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT (strftime('%s','now'))
);

-- Device registry
CREATE TABLE devices (
    device_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    device_type TEXT,
    firmware_version TEXT,
    config_json TEXT,
    calibration_json TEXT,
    last_heartbeat INTEGER,
    status TEXT DEFAULT 'unknown',
    registered_at INTEGER DEFAULT (strftime('%s','now'))
);

-- Edge health snapshots
CREATE TABLE edge_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    cpu_percent REAL,
    ram_percent REAL,
    disk_percent REAL,
    temperature REAL,
    mqtt_latency_ms REAL,
    process_count INTEGER
);
```

### Indexes

```sql
CREATE INDEX idx_telemetry_device_time ON telemetry(device_id, timestamp DESC);
CREATE INDEX idx_telemetry_time ON telemetry(timestamp DESC);
CREATE INDEX idx_inference_device_time ON inference_results(device_id, timestamp DESC);
CREATE INDEX idx_alerts_severity ON alerts(severity, resolved, timestamp DESC);
CREATE INDEX idx_alerts_device ON alerts(device_id, timestamp DESC);
CREATE INDEX idx_edge_health_time ON edge_health(timestamp DESC);
```

---

## Retention Strategy

| Tier | Storage | Retention | Write Pattern |
|------|---------|-----------|---------------|
| Hot | SQLite | 24 hours | Every reading |
| Warm | DuckDB | 7 days | Hourly aggregates |
| Cold | Parquet | 90 days | Daily archives |
| Archive | Parquet (compressed) | 1 year | Weekly roll-up |

Cleanup runs every hour via async scheduler.

---

## AI Pipeline Design

```
Telemetry Input
      │
      ▼
┌─────────────────┐
│ Feature Extract  │  Rolling stats, FFT, trends
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Stage 1:        │  Z-score, IQR, EWMA
│ Statistical     │  → Quick anomaly flag
└────────┬────────┘
         │ (if anomaly detected)
         ▼
┌─────────────────┐
│ Stage 2:        │  RandomForest / LightGBM
│ Classification  │  → Fault type + confidence
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Stage 3:        │  Degradation curves
│ Predictive      │  → RUL estimation
└────────┬────────┘
         │ (if confidence < threshold)
         ▼
┌─────────────────┐
│ Stage 4:        │  Isolation Forest
│ Unknown Fault   │  → Cluster + escalate
└─────────────────┘
```

---

## Deployment Architecture

```
systemd services:
├── edge-mosquitto.service      # MQTT broker
├── edge-platform.service       # Main platform (FastAPI + workers)
├── edge-health.service         # Health monitor
└── edge-archiver.timer         # Periodic archival
```

All services run under a dedicated `edgeai` user with resource limits.
