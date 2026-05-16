-- Omni Real-time Analytics Engine (Flink SQL)

-- 1. Create Source Table (Linked to Redpanda Topic)
CREATE TABLE execution_results (
    command_id STRING,
    status STRING,
    occurred_at TIMESTAMP(3),
    telemetry MAP<STRING, STRING>,
    WATERMARK FOR occurred_at AS occurred_at - INTERVAL '5' SECOND
) WITH (
    'connector' = 'kafka',
    'topic' = 'outreach.results',
    'properties.bootstrap.servers' = 'localhost:9092',
    'format' = 'json'
);

-- 2. Create Real-time Aggregates (The Lungs)
CREATE VIEW daily_performance AS
SELECT 
    TUMBLE_START(occurred_at, INTERVAL '1' DAY) as window_start,
    status,
    COUNT(*) as total_events
FROM execution_results
GROUP BY TUMBLE(occurred_at, INTERVAL '1' DAY), status;

-- 3. Sink to DragonflyDB for the UI
-- (Using the Redis/Dragonfly connector)
CREATE TABLE dashboard_metrics (
    window_start TIMESTAMP(3),
    status STRING,
    total_events BIGINT,
    PRIMARY KEY (window_start, status) NOT ENFORCED
) WITH (
    'connector' = 'redis',
    'host' = 'localhost',
    'port' = '6379',
    'command' = 'HSET'
);

INSERT INTO dashboard_metrics
SELECT * FROM daily_performance;
