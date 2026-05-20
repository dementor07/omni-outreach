-- Omni Real-time Analytics Engine (Flink SQL)
--
-- Reads ExecutionResult envelopes off Redpanda, runs tumbling windows over
-- them, and sinks the rolled-up counters into Postgres (table flink_metrics_*).
-- The /analytics router reads those tables directly — no Dragonfly hop needed
-- because Postgres is already in the read path and Flink SQL has a first-class
-- JDBC connector (Bahir's Redis bridge isn't a SQL DynamicTableFactory).

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

-- 3. Per-channel hourly throughput (channel mix widget).
CREATE VIEW hourly_channel_mix AS
SELECT
    DATE_FORMAT(TUMBLE_START(occurred_at, INTERVAL '1' HOUR), 'yyyy-MM-dd HH') AS window_hour,
    channel,
    status,
    COUNT(*) AS total_events
FROM execution_results
GROUP BY TUMBLE(occurred_at, INTERVAL '1' HOUR), channel, status;

-- 4. Postgres sinks. Tables created by alembic migration 016.
--    Upsert mode (PRIMARY KEY) means re-emitted windows overwrite.
CREATE TABLE flink_metrics_daily (
    window_day    STRING,
    status        STRING,
    total_events  BIGINT,
    PRIMARY KEY (window_day, status) NOT ENFORCED
) WITH (
    'connector'          = 'jdbc',
    'url'                = 'jdbc:postgresql://db:5432/outreach',
    'table-name'         = 'flink_metrics_daily',
    'username'           = 'outreach',
    'password'           = 'OmniOutreach2026',
    'driver'             = 'org.postgresql.Driver',
    'sink.buffer-flush.max-rows' = '50',
    'sink.buffer-flush.interval' = '2s'
);

CREATE TABLE flink_metrics_channel_mix (
    window_hour   STRING,
    channel       STRING,
    status        STRING,
    total_events  BIGINT,
    PRIMARY KEY (window_hour, channel, status) NOT ENFORCED
) WITH (
    'connector'          = 'jdbc',
    'url'                = 'jdbc:postgresql://db:5432/outreach',
    'table-name'         = 'flink_metrics_channel_mix',
    'username'           = 'outreach',
    'password'           = 'OmniOutreach2026',
    'driver'             = 'org.postgresql.Driver',
    'sink.buffer-flush.max-rows' = '50',
    'sink.buffer-flush.interval' = '2s'
);

INSERT INTO flink_metrics_daily
SELECT window_day, status, total_events FROM daily_performance;

INSERT INTO flink_metrics_channel_mix
SELECT window_hour, channel, status, total_events FROM hourly_channel_mix;
