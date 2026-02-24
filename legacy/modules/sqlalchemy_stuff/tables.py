from clickhouse_sqlalchemy import engines, types
from sqlalchemy import Column
from modules.sqlalchemy_stuff.engine import Base
from settings import settings


class DataCompressionBenchmarkResults(Base):
    # ---------------------------  Metadata  ----------------------------
    __tablename__ = settings.DATA_COMPRESSION_BENCHMARK_RESULTS_TABLE
    __table_args__ = (engines.MergeTree(order_by="benchmark_id"),)

    id = Column(types.String, primary_key=True)
    benchmark_id = Column(types.Int32, primary_key=True)
    source_db_name = Column(types.String)
    source_table_name = Column(types.String)
    tested_table_ddl = Column(types.String)
    source_table_ddl = Column(types.String)
    is_source_table_copy = Column(types.Boolean)
    total_n_rows_in_tested_table = Column(types.Int)
    total_n_rows_in_source_table = Column(types.Int)
    measured_percentiles = Column(types.Array(types.Int))

    # ---------------------------  Insert test results  ----------------------------
    insert_test_n_rows = Column(types.Int32)
    tested_table_insert_time_ms_measurements = Column(types.Array(types.Float))
    source_table_insert_time_ms_measurements = Column(types.Array(types.Float))
    tested_table_insert_time_ms_measurements_percentiles = Column(types.Array(types.Float))
    source_table_insert_time_ms_measurements_percentiles = Column(types.Array(types.Float))
    tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs = Column(types.Array(types.Float))
    tested_table_insert_rows_per_second_measurements = Column(types.Array(types.Float))
    source_table_insert_rows_per_second_measurements = Column(types.Array(types.Float))
    tested_table_insert_rows_per_second_measurements_percentiles = Column(types.Array(types.Float))
    source_table_insert_rows_per_second_measurements_percentiles = Column(types.Array(types.Float))
    tested_table_insert_bytes_per_second_measurements = Column(types.Array(types.Float))
    tested_table_insert_bytes_per_second_measurements_readable = Column(types.Array(types.String))
    source_table_insert_bytes_per_second_measurements = Column(types.Array(types.Float))
    source_table_insert_bytes_per_second_measurements_readable = Column(types.Array(types.String))
    tested_table_insert_bytes_per_second_measurements_percentiles = Column(types.Array(types.Float))
    tested_table_insert_bytes_per_second_measurements_percentiles_readable = Column(types.Array(types.String))
    source_table_insert_bytes_per_second_measurements_percentiles = Column(types.Array(types.Float))
    source_table_insert_bytes_per_second_measurements_percentiles_readable = Column(types.Array(types.String))

    # ---------------------------  Select test results  ----------------------------
    tested_table_select_test_query = Column(types.String)
    source_table_select_test_query = Column(types.String)
    tested_table_select_time_ms_measurements = Column(types.Array(types.Float))
    source_table_select_time_ms_measurements = Column(types.Array(types.Float))
    tested_table_select_time_ms_measurements_percentiles = Column(types.Array(types.Float))
    source_table_select_time_ms_measurements_percentiles = Column(types.Array(types.Float))
    tested_table_select_time_ms_measurements_percentiles_speed_up_coefs = Column(types.Array(types.Float))
    tested_table_select_rows_per_second_measurements = Column(types.Array(types.Float))
    source_table_select_rows_per_second_measurements = Column(types.Array(types.Float))
    tested_table_select_rows_per_second_measurements_percentiles = Column(types.Array(types.Float))
    source_table_select_rows_per_second_measurements_percentiles = Column(types.Array(types.Float))
    tested_table_select_bytes_per_second_measurements = Column(types.Array(types.Float))
    tested_table_select_bytes_per_second_measurements_readable = Column(types.Array(types.String))
    source_table_select_bytes_per_second_measurements = Column(types.Array(types.Float))
    source_table_select_bytes_per_second_measurements_readable = Column(types.Array(types.String))
    tested_table_select_bytes_per_second_measurements_percentiles = Column(types.Array(types.Float))
    tested_table_select_bytes_per_second_measurements_percentiles_readable = Column(types.Array(types.String))
    source_table_select_bytes_per_second_measurements_percentiles = Column(types.Array(types.Float))
    source_table_select_bytes_per_second_measurements_percentiles_readable = Column(types.Array(types.String))

    # ---------------------------  Compression results  ----------------------------
    tested_table_consumed_compressed_size_bytes_by_each_column = Column(types.String)
    source_table_consumed_compressed_size_bytes_by_each_column = Column(types.String)
    tested_table_consumed_compressed_size_bytes_overall = Column(types.Float)
    tested_table_consumed_compressed_size_bytes_overall_readable = Column(types.String)
    source_table_consumed_compressed_size_bytes_overall = Column(types.Float)
    source_table_consumed_compressed_size_bytes_overall_readable = Column(types.String)
    tested_table_compression_overall_coef = Column(types.Float)
    tested_table_compression_by_each_column_coef = Column(types.String)
    source_table_n_rows_in_size_test = Column(types.Int)
    tested_table_n_rows_in_size_test = Column(types.Int)


class IndexesBenchmarkResults(Base):
    # ---------------------------  Metadata  ----------------------------
    __tablename__ = settings.INDEXES_BENCHMARK_RESULTS_TABLE
    __table_args__ = (engines.MergeTree(order_by="benchmark_id"),)

    id = Column(types.String, primary_key=True)
    benchmark_id = Column(types.Int32)
    source_db_name = Column(types.String)
    source_table_name = Column(types.String)
    tested_table_ddl = Column(types.String)
    source_table_ddl = Column(types.String)
    is_source_table_copy = Column(types.Boolean)
    index_params = Column(types.String)
    total_n_rows_in_tested_table = Column(types.Int)
    total_n_rows_in_source_table = Column(types.Int)
    measured_percentiles = Column(types.Array(types.Int))

    # ---------------------------  Insert test results  ----------------------------
    insert_test_n_rows = Column(types.Int)
    tested_table_insert_time_ms_measurements = Column(types.Array(types.Float))
    source_table_insert_time_ms_measurements = Column(types.Array(types.Float))
    tested_table_insert_time_ms_measurements_percentiles = Column(types.Array(types.Float))
    source_table_insert_time_ms_measurements_percentiles = Column(types.Array(types.Float))
    tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs = Column(types.Array(types.Float))
    tested_table_insert_rows_per_second_measurements = Column(types.Array(types.Float))
    source_table_insert_rows_per_second_measurements = Column(types.Array(types.Float))
    tested_table_insert_rows_per_second_measurements_percentiles = Column(types.Array(types.Float))
    source_table_insert_rows_per_second_measurements_percentiles = Column(types.Array(types.Float))
    tested_table_insert_bytes_per_second_measurements = Column(types.Array(types.Float))
    tested_table_insert_bytes_per_second_measurements_readable = Column(types.Array(types.String))
    source_table_insert_bytes_per_second_measurements = Column(types.Array(types.Float))
    source_table_insert_bytes_per_second_measurements_readable = Column(types.Array(types.String))
    tested_table_insert_bytes_per_second_measurements_percentiles = Column(types.Array(types.Float))
    tested_table_insert_bytes_per_second_measurements_percentiles_readable = Column(types.Array(types.String))

    # ---------------------------  Select test results  ----------------------------
    tested_table_select_test_query = Column(types.String)
    source_table_select_test_query = Column(types.String)
    tested_table_select_time_ms_measurements = Column(types.Array(types.Float))
    source_table_select_time_ms_measurements = Column(types.Array(types.Float))
    tested_table_select_time_ms_measurements_percentiles = Column(types.Array(types.Float))
    source_table_select_time_ms_measurements_percentiles = Column(types.Array(types.Float))
    tested_table_select_time_ms_measurements_percentiles_speed_up_coefs = Column(types.Array(types.Float))

    # ---------------------------  Indexes results  ----------------------------
    tested_table_cols_sizes = Column(types.String)
    tested_table_indexes_sizes = Column(types.String)
    tested_table_indexes_sizes_percent_from_col_size = Column(types.String)


class FullBenchmarkResults(Base):
    # ---------------------------  Metadata  ----------------------------
    __tablename__ = settings.FULL_BENCHMARK_RESULTS_TABLE
    __table_args__ = (engines.MergeTree(order_by="benchmark_id"),)

    id = Column(types.String, primary_key=True)
    benchmark_id = Column(types.Int32)
    source_db_name = Column(types.String)
    source_table_name = Column(types.String)
    data_compression_benchmark_uuid = Column(types.String)
    indexes_benchmark_uuid = Column(types.String)