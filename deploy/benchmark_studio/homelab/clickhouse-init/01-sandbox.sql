CREATE DATABASE IF NOT EXISTS benchmark_sandbox;
CREATE USER IF NOT EXISTS benchmark_writer IDENTIFIED WITH no_password;
GRANT CREATE TABLE, DROP TABLE, INSERT, SELECT ON benchmark_sandbox.* TO benchmark_writer;
