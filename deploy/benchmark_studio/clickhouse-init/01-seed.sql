CREATE DATABASE IF NOT EXISTS default;
CREATE TABLE IF NOT EXISTS default.benchmark_events (event_date Date, event_id UInt64, country LowCardinality(String), payload String) ENGINE = MergeTree ORDER BY (event_date, event_id);
INSERT INTO default.benchmark_events SELECT toDate('2026-09-01') + (number % 14), number, arrayElement(['RU','KZ','BY'], (number % 3) + 1), concat('event-', toString(number)) FROM numbers(10000);
CREATE USER IF NOT EXISTS readonly IDENTIFIED WITH no_password;
GRANT SELECT ON default.* TO readonly;
CREATE DATABASE IF NOT EXISTS benchmark_sandbox;
CREATE USER IF NOT EXISTS benchmark_writer IDENTIFIED WITH no_password;
GRANT CREATE TABLE, DROP TABLE, INSERT, SELECT ON benchmark_sandbox.* TO benchmark_writer;
GRANT SELECT ON default.benchmark_events TO benchmark_writer;
