CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS telemetry (
    ts TIMESTAMPTZ NOT NULL,
    device_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    anomaly INTEGER DEFAULT 0,
    source_file TEXT DEFAULT ''
);

SELECT create_hypertable('telemetry', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_telemetry_device_ts
    ON telemetry (device_id, ts);

CREATE INDEX IF NOT EXISTS idx_telemetry_device_metric_ts
    ON telemetry (device_id, metric, ts);