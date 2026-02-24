from enum import Enum
from typing import List, Optional, Set
from pydantic import BaseModel, Field


class TableData(BaseModel):
    db_name: str
    table_name: str


class DatabaseCol(BaseModel):
    name: Optional[str] = ""
    datatype: Optional[str] = ""
    codec: Optional[str] = ""
    other_params: Optional[str] = ""


class TableColSizeInfo(BaseModel):
    name: str = ""
    datatype: str = ""
    size_compressed_bytes: int = -1
    size_compressed_bytes_readable: str = ""


class IndexSizeInfo(BaseModel):
    size_compressed_bytes: int = -1
    size_compressed_bytes_readable: str = ""


class PermutationTactics(Enum):
    """
    PRODUCT_PERMUTATIONS - для подстановки всех возможных перестановок в столбцах определенного типа данных
    UNIFORM_PERMUTATION - для подстановки 1 одинаковой перестановки в столбцах определенного типа данных
    """
    PRODUCT_PERMUTATIONS = "PRODUCT_PERMUTATIONS"
    UNIFORM_PERMUTATION = "UNIFORM_PERMUTATION"


class DataTypeAlternatives(BaseModel):
    alternatives: List[DatabaseCol]
    allowed_cols_names: Set[str] = Field(default_factory=lambda: {"*"})
    data_type_permutation_mode: PermutationTactics


class OneTableVariantBenchmarkResult(BaseModel):
    consumed_compressed_space_by_each_column: List[TableColSizeInfo] = []
    consumed_compressed_space_mbytes_overall: float = -1
    insert_time_results: List[float] = []
    table_ddl: str = ""
    original_db_name: str = ""
    original_table_name: str = ""
    tested_table_n_rows_in_size_test: int = -1


class IndexParams(BaseModel):
    n_gram_size: int = -1
    bloom_filter_size_in_bytes: int = -1
    num_hashes: int = -1
    granularity: int = -1
    additional_settings_at_ddl_end: str = ""


class IndexType(Enum):
    NGRAMBF_V1 = "ngrambf_v1"
    TOKENBF_v1 = "tokenbf_v1"
    FULL_TEXT = "full_text"


class IndexBenchmarkResultModel(BaseModel):
    benchmark_id: int
    source_db_name: str
    source_table_name: str
    tested_table_ddl: str
    source_table_ddl: str
    is_source_table_copy: bool
    index_params: str
    total_n_rows_in_tested_table: int
    total_n_rows_in_source_table: int
    # Insert test results
    insert_test_n_rows: int
    tested_table_insert_time_ms_measurements: List[float]
    source_table_insert_time_ms_measurements: List[float]
    tested_table_insert_time_ms_measurements_percentiles: List[float]
    source_table_insert_time_ms_measurements_percentiles: List[float]
    tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs: List[float]
    tested_table_insert_rows_per_second_measurements: List[float]
    source_table_insert_rows_per_second_measurements: List[float]
    tested_table_insert_rows_per_second_measurements_percentiles: List[float]
    source_table_insert_rows_per_second_measurements_percentiles: List[float]
    tested_table_insert_bytes_per_second_measurements: List[float]
    tested_table_insert_bytes_per_second_measurements_readable: List[str]
    source_table_insert_bytes_per_second_measurements: List[float]
    source_table_insert_bytes_per_second_measurements_readable: List[str]
    tested_table_insert_bytes_per_second_measurements_percentiles: List[float]
    tested_table_insert_bytes_per_second_measurements_percentiles_readable: List[str]
    source_table_insert_bytes_per_second_measurements_percentiles: List[float]
    source_table_insert_bytes_per_second_measurements_percentiles_readable: List[str]
    # Select test results
    tested_table_select_test_query: str
    source_table_select_test_query: str
    tested_table_select_time_ms_measurements: List[float]
    source_table_select_time_ms_measurements: List[float]
    tested_table_select_time_ms_measurements_percentiles: List[float]
    source_table_select_time_ms_measurements_percentiles: List[float]
    tested_table_select_time_ms_measurements_percentiles_speed_up_coefs: List[float]
    # Indexes results
    tested_table_cols_sizes: str
    tested_table_indexes_sizes: str
    tested_table_indexes_sizes_percent_from_col_size: str


class DataCompressionBenchmarkResultModel(BaseModel):
    benchmark_id: int
    source_db_name: str
    source_table_name: str
    tested_table_ddl: str
    source_table_ddl: str
    is_source_table_copy: bool
    total_n_rows_in_tested_table: int
    total_n_rows_in_source_table: int
    measured_percentiles: List[int]
    # Insert test results
    insert_test_n_rows: int
    tested_table_insert_time_ms_measurements: List[float]
    source_table_insert_time_ms_measurements: List[float]
    tested_table_insert_time_ms_measurements_percentiles: List[float]
    source_table_insert_time_ms_measurements_percentiles: List[float]
    tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs: List[float]
    tested_table_insert_rows_per_second_measurements: List[float]
    source_table_insert_rows_per_second_measurements: List[float]
    tested_table_insert_rows_per_second_measurements_percentiles: List[float]
    source_table_insert_rows_per_second_measurements_percentiles: List[float]
    tested_table_insert_bytes_per_second_measurements: List[float]
    tested_table_insert_bytes_per_second_measurements_readable: List[str]
    source_table_insert_bytes_per_second_measurements: List[float]
    source_table_insert_bytes_per_second_measurements_readable: List[str]
    tested_table_insert_bytes_per_second_measurements_percentiles: List[float]
    tested_table_insert_bytes_per_second_measurements_percentiles_readable: List[str]
    source_table_insert_bytes_per_second_measurements_percentiles: List[float]
    source_table_insert_bytes_per_second_measurements_percentiles_readable: List[str]
    # Select test results
    tested_table_select_test_query: str
    source_table_select_test_query: str
    tested_table_select_time_ms_measurements: List[float]
    source_table_select_time_ms_measurements: List[float]
    tested_table_select_time_ms_measurements_percentiles: List[float]
    source_table_select_time_ms_measurements_percentiles: List[float]
    tested_table_select_time_ms_measurements_percentiles_speed_up_coefs: List[float]
    tested_table_select_rows_per_second_measurements: List[float]
    source_table_select_rows_per_second_measurements: List[float]
    tested_table_select_rows_per_second_measurements_percentiles: List[float]
    source_table_select_rows_per_second_measurements_percentiles: List[float]
    tested_table_select_bytes_per_second_measurements: List[float]
    tested_table_select_bytes_per_second_measurements_readable: List[str]
    source_table_select_bytes_per_second_measurements: List[float]
    source_table_select_bytes_per_second_measurements_readable: List[str]
    tested_table_select_bytes_per_second_measurements_percentiles: List[float]
    tested_table_select_bytes_per_second_measurements_percentiles_readable: List[str]
    source_table_select_bytes_per_second_measurements_percentiles: List[float]
    source_table_select_bytes_per_second_measurements_percentiles_readable: List[str]
    # Compression results
    tested_table_consumed_compressed_size_bytes_by_each_column: str
    source_table_consumed_compressed_size_bytes_by_each_column: str
    tested_table_consumed_compressed_size_bytes_overall: float
    tested_table_consumed_compressed_size_bytes_overall_readable: str
    source_table_consumed_compressed_size_bytes_overall: float
    source_table_consumed_compressed_size_bytes_overall_readable: str
    tested_table_compression_overall_coef: float
    tested_table_compression_by_each_column_coef: str
    source_table_n_rows_in_size_test: int
    tested_table_n_rows_in_size_test: int


class QuerySummaryModel(BaseModel):
    read_rows: int = -1
    read_bytes: int = -1
    written_rows: int = -1
    written_bytes: int = -1
    elapsed_ns: int = -1


class QueryStats(BaseModel):
    read_bytes_per_second_measurements: List[float] = []
    written_bytes_per_second_measurements: List[float] = []
    read_rows_per_second_measurements: List[float] = []
    written_rows_per_second_measurements: List[float] = []
    elapsed_ns_measurements: List[float] = []
    read_rows_measurements: List[int] = []
    written_rows_measurements: List[int] = []