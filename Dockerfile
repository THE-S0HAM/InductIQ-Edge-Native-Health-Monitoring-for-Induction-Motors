# Multi-stage build for Industrial Edge AI Platform
# Optimized for ARM64 (Raspberry Pi) and x86_64

# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gfortran \
    libopenblas-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Build wheels
RUN pip install --upgrade pip wheel setuptools && \
    pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

LABEL maintainer="Edge AI Engineering"
LABEL description="Industrial Edge AI Monitoring Platform"
LABEL version="1.0.0"

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    mosquitto \
    mosquitto-clients \
    libopenblas0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 edgeai

# Copy wheels from builder
COPY --from=builder /build/wheels /wheels

# Install Python packages
RUN pip install --upgrade pip && \
    pip install --no-cache /wheels/* && \
    rm -rf /wheels

# Copy application
COPY --chown=edgeai:edgeai . .

# Create data directories
RUN mkdir -p data/models data/archives/telemetry data/archives/inference data/logs && \
    chown -R edgeai:edgeai data

# Switch to non-root user
USER edgeai

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8420/health || exit 1

# Expose ports
EXPOSE 8420 1883

# Environment
ENV EDGE_CONFIG_PATH=config/platform.yaml
ENV PYTHONUNBUFFERED=1

# Run platform
CMD ["python", "run.py"]
