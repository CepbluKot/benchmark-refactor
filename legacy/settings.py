import logging
from typing import Dict, List, Set

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings

from modules.data_type_alternatives import (
    array_map_string_string_alternatives,
    array_string_alternatives,
    map_string_string_alternatives,
    string_alternatives_w_lowcardinality,
)
from modules.interfaces import DataTypeAlternatives


class Settings(BaseSettings):
    LOG_LEVEL: str = "INFO"
    LOG_DEFAULT_FORMAT: str = "%(asctime)s %(levelname)s %(name)s: %(message)s"

    BUILD_DATETIME: str = Field(default="", validation_alias="BUILD_DATETIME")
    GIT_COMMIT: str = Field(default="", validation_alias="GIT_COMMIT")
    GIT_BRANCH: str = Field(default="", validation_alias="GIT_BRANCH")

    CELERY_WORKER_CONCURRENCY: int = Field(default=4, validation_alias="CELERY_WORKER_CONCURRENCY")

    SRC_DATABASE_HOST: str = ""
    SRC_DATABASE_PORT: int = -1
    SRC_DATABASE_USERNAME: SecretStr = Field(..., validation_alias="SRC_DATABASE_USERNAME")
    SRC_DATABASE_PASSWORD: SecretStr = Field(..., validation_alias="SRC_DATABASE_PASSWORD")

    TGT_DATABASE_HOST: str = ""
    TGT_DATABASE_PORT: int = -1
    TGT_DATABASE_USERNAME: SecretStr = Field(..., validation_alias="TGT_DATABASE_USERNAME")
    TGT_DATABASE_PASSWORD: SecretStr = Field(..., validation_alias="TGT_DATABASE_PASSWORD")

    RABBITMQ_HOSTNAME: str = Field(..., validation_alias="RABBITMQ_HOSTNAME")
    RABBITMQ_LOGIN: SecretStr = Field(..., validation_alias="RABBITMQ_LOGIN")
    RABBITMQ_PASSWORD: SecretStr = Field(..., validation_alias="RABBITMQ_PASSWORD")
    RABBITMQ_PORT: int = Field(..., validation_alias="RABBITMQ_PORT")

    BENCHMARK_RESULTS_DATABASE: str = "benchmark_results_database_new_2"
    DATA_COMPRESSION_BENCHMARK_RESULTS_TABLE: str = "data_compression_benchmark_results"
    INDEXES_BENCHMARK_RESULTS_TABLE: str = "indexes_benchmark_results"
    FULL_BENCHMARK_RESULTS_TABLE: str = "full_benchmark_results"

    # General
    DATABASE_NAMES_TO_CHECK: List[str] = ["raw_lm"]
    CHECKED_TABLES_ENGINE_TYPES: List[str] = ["MergeTree", "ReplacingMergeTree"]
    CLICKHOUSE_MANAGER_MAX_POOL_CONNECTIONS: int = 1
    CLICKHOUSE_MANAGER_NUM_POOLS: int = 1
    CLICKHOUSE_MANAGER_MAX_CONCURRENT_STREAMS_PER_PROCESS: int = 1
    MAX_COPY_N_RETRIES: int = 100
    MAX_COPY_RETRY_SLEEP_SEC: int = 10
    MAX_COPY_RETRY_SLEEP_SEC_INCREMENT: int = 2
    MEASURED_PERCENTILES: List[int] = [1, 50, 90, 95, 99, 100]
    TABLES_TO_CHECK: List[str] = ["log_k8s_containers"]
    RPS: int = Field(default=1, validation_alias="RPS")

    # Data compression benchmark
    TEST_DATA_COMPRESSION_DB_POSTFIX: str = "_test_data_compression_db"
    N_INSERT_ROWS_FOR_DATA_COMPRESSION_BENCHMARK: int = 100_000
    INSERT_TIME_TEST_N_MEASUREMENTS_FOR_DATA_COMPRESSION_BENCHMARK: int = 10
    DATA_COMPRESSION_BENCHMARK_TABLES_TO_EXCLUDE: Set[str] = set(["test_kc"])
    DATA_TYPES_POSSIBLE_ALTERNATIVES: Dict[str, DataTypeAlternatives] = {
        "String": string_alternatives_w_lowcardinality,
        "LowCardinality(String)": string_alternatives_w_lowcardinality,
        "Map(LowCardinality(String), String)": map_string_string_alternatives,
        "Array(LowCardinality(String))": array_string_alternatives,
        "Array(Map(LowCardinality(String), String))": array_map_string_string_alternatives,
        "Array(String)": array_string_alternatives,
    }

    # Indexes benchmark
    TEST_INDEXES_DB_POSTFIX: str = "_test_indexes_db"
    N_INSERT_ROWS_FOR_INDEXES_BENCHMARK: int = 100_000
    INSERT_TIME_TEST_N_MEASUREMENTS_FOR_INDEXES_BENCHMARK: int = 1000
    INDEXES_BENCHMARK_TABLES_TO_EXCLUDE: Set[str] = set(["test_kc"])
    SELECT_TIME_TEST_N_MEASUREMENTS_FOR_INDEXES_BENCHMARK: int = 10
    INDEXES_BENCHMARK_INDEXED_COLS_BY_TABLE: Dict[str, List[str]] = {
        "test_db.test_table": ["log"],
    }
    INDEXES_BENCHMARK_TEST_QUERIES_BY_TABLE: Dict[str, str] = {
        "test_db.test_table": "",
    }
    INDEXES_BENCHMARK_SELECT_QUERY_SEND_RECEIVE_TIMEOUT_SEC: int = 60
    N_GRAM_POSSIBLE_SIZES: List[int] = [3, 4, 5]
    BLOOM_FILTER_POSSIBLE_SIZES_IN_BYTES: List[int] = [262144, 131072, 65536, 32768]
    NUM_HASHES_POSSIBLE: List[int] = [1, 3, 7]
    GRANULARITY_POSSIBLE: List[int] = [16, 24, 32]

    # Full benchmark
    N_INSERT_ROWS_FOR_FULL_BENCHMARK: int = 100_000
    INSERT_TIME_TEST_N_MEASUREMENTS_FOR_FULL_BENCHMARK: int = 1000
    FULL_BENCHMARK_USED_DATA_COMPRESSION_BENCHMARK_ID: int = -1
    TOP_N_RESULTS: int = 5
    FULL_BENCHMARK_TOP_N_DATA_COMPRESSION_RESULTS_TABLES_DB_NAME: str = (
        "full_benchmark_top_n_data_compression_results_tables_db"
    )
    FULL_BENCHMARK_PERFORM_PRELIMINARY_DATA_COMPRESSION_BENCHMARK: bool = True
    FULL_BENCHMARK_TABLES_TO_EXCLUDE: Set[str] = set(["test_kc"])

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        env_nested_delimiter = "__"
        extra = "allow"


settings = Settings()
logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format=settings.LOG_DEFAULT_FORMAT,
)