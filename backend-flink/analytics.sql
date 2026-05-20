-- Omni Real-time Analytics Engine (Flink SQL)
--
-- Drives the live dashboard. Reads ExecutionResult envelopes off Redpanda,
-- aggregates them in 1-day tumbling windows, and writes the counters into
-- Dragonfly (Redis-compatible) so the FastAPI overview endpoints can serve
-- the dashboard in O(1) without scanning Postgres.

-- 1. Source: outreach.results
CREATE TABLE execution_results (
    command_id    STRING,
    task_id       STRING,
    lead_id       STRING,
    campaign_id   STRING,
    channel       STRING,
    status        STRING,
    error         STRING,
    is_retriable  BOOLEAN,
    occurred_at   TIMESTAMP_LTZ(3) METADATA FROM 'timestamp',
    telemetry     MAP<STRING, STRING>,
    WATERMARK FOR occurred_at AS occurred_at - INTERVAL '5' SECOND
) WITH (
    'connector' = 'kafka',
    'topic' = 'outreach.results',
    'properties.bootstrap.servers' = 'redpanda:9092',
    'properties.group.id' = 'flink-sql-analytics',
    'scan.startup.mode' = 'latest-offset',
    'format' = 'json',
    'json.ignore-parse-errors' = 'true'
);

-- 2. Daily per-status aggregate.
CREATE VIEW daily_performance AS
SELECT
    DATE_FORMAT(TUMBLE_START(occurred_at, INTERVAL '1' DAY), 'yyyy-MM-dd') AS window_day,
    status,
    COUNT(*) AS total_events
FROM execution_results
GROUP BY TUMBLE(occurred_at, INTERVAL '1' DAY), status;

-- 3. Per-channel hourly throughput (used by the channel mix widget).
CREATE VIEW hourly_channel_mix AS
SELECT
    DATE_FORMAT(TUMBLE_START(occurred_at, INTERVAL '1' HOUR), 'yyyy-MM-dd HH') AS window_hour,
    channel,
    status,
    COUNT(*) AS total_events
FROM execution_results
GROUP BY TUMBLE(occurred_at, INTERVAL '1' HOUR), channel, status;

-- 4. Dragonfly sink (HSET key = "omni:metrics:daily", field = "<day>:<status>").
CREATE TABLE dashboard_daily (
    window_day    STRING,
    status        STRING,
    total_events  BIGINT,
    PRIMARY KEY (window_day, status) NOT ENFORCED
) WITH (
    'connector'     = 'redis',
    'redis-mode'    = 'single',
    'host'          = 'redis',
    'port'          = '6379',
    'command'       = 'HSET',
    'additional-key'= 'omni:metrics:daily'
);

CREATE TABLE dashboard_channel_mix (
    window_hour   STRING,
    channel       STRING,
    status        STRING,
    total_events  BIGINT,
    PRIMARY KEY (window_hour, channel, status) NOT ENFORCED
) WITH (
    'connector'     = 'redis',
    'redis-mode'    = 'single',
    'host'          = 'redis',
    'port'          = '6379',
    'command'       = 'HSET',
    'additional-key'= 'omni:metrics:channel_mix'
);

INSERT INTO dashboard_daily
SELECT window_day, status, total_events FROM daily_performance;

INSERT INTO dashboard_channel_mix
SELECT window_hour, channel, status, total_events FROM hourly_channel_mix;
