import logging
import re
from typing import List

from modules.interfaces import DatabaseCol, IndexType
from settings import settings

logger = logging.getLogger(__name__)

CLICKHOUSE_KEYWORDS = {
    "mergetree": "MergeTree",
    "replicatedmergetree": "ReplicatedMergeTree",
    "summingmergetree": "SummingMergeTree",
    "replacingmergetree": "ReplacingMergeTree",
    "aggregatingmergetree": "AggregatingMergeTree",
    "collapsingmergetree": "CollapsingMergeTree",
    "lz4": "LZ4",
    "lz4hc": "LZ4HC",
    "zstd": "ZSTD",
    "delta": "Delta",
    "uint8": "UInt8",
    "uint16": "UInt16",
    "uint32": "UInt32",
    "uint64": "UInt64",
    "int8": "Int8",
    "int16": "Int16",
    "int32": "Int32",
    "int64": "Int64",
    "float32": "Float32",
    "float64": "Float64",
    "datetime": "DateTime",
    "datetime64": "DateTime64",
}


def normalize_clickhouse_ddl(sql: str) -> str:
    def replacer(match):
        return CLICKHOUSE_KEYWORDS.get(match.group(0).lower(), match.group(0))

    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in CLICKHOUSE_KEYWORDS) + r")\b", re.IGNORECASE
    )
    return pattern.sub(replacer, sql)


def format_sql(sql: str) -> str:
    if not sql:
        return sql
    result = sql.strip()
    result = result.replace("\n", " ")
    result = result.replace("  ", " ")
    result = result.replace(" ( ", " (")
    result = result.replace(" ) ", ") ")
    result = result.replace(",)", ")")
    result = result.replace(" ,", ", ")
    result = result.replace(" .", ".")
    result = result.replace(". ", ".")
    result = result.replace("( )", "()")
    if not result.endswith(";"):
        result += ";"
    result = normalize_clickhouse_ddl(result)
    return result


def generate_table_ddl_w_new_cols(
    src_db_name: str,
    src_table_name: str,
    target_db_name: str,
    target_table_name: str,
    initial_table_cols: List[str],
    new_cols: List[DatabaseCol],
) -> str | None:
    if not initial_table_cols:
        return None

    initial_table_cols_copy = list(initial_table_cols)
    initial_table_cols_copy[0] = initial_table_cols_copy[0].replace(
        f"{src_db_name}.{src_table_name}", f"{target_db_name}.{target_table_name}"
    )

    if not new_cols:
        return format_sql(" ".join(initial_table_cols_copy) + ";")

    for i in range(1, len(initial_table_cols) - 1):
        if i - 1 >= len(new_cols):
            break
        new_col_data = new_cols[i - 1]

        if (
            new_col_data.other_params
            and not new_col_data.name
            and not new_col_data.datatype
            and not new_col_data.codec
        ):
            column_def = new_col_data.other_params
        else:
            col_parts = [f"{new_col_data.name} {new_col_data.datatype}"]
            if new_col_data.other_params:
                col_parts.append(new_col_data.other_params)
            if new_col_data.codec:
                col_parts.append(f"CODEC({new_col_data.codec})")
            column_def = " ".join(filter(None, col_parts))

        if i < len(initial_table_cols) - 2:
            column_def = column_def.rstrip() + ","
        else:
            column_def = column_def.rstrip()

        initial_table_cols_copy[i] = column_def

    last_col_index = len(initial_table_cols) - 2
    if last_col_index > 0:
        initial_table_cols_copy[last_col_index] = (
            initial_table_cols_copy[last_col_index].rstrip().rstrip(",")
        )

    cleaned_lines = [line.strip() for line in initial_table_cols_copy if line.strip()]
    return format_sql(" ".join(cleaned_lines))


def generate_indexes_benchmark_select_query(
    database: str, table: str, cols_to_query: List[str], index_type: IndexType | None
) -> str:
    predefined_test_query = settings.INDEXES_BENCHMARK_TEST_QUERIES_BY_TABLE.get(
        f"{database}.{table}"
    )
    if predefined_test_query:
        return predefined_test_query

    str_to_search = "very looooooooooooong stringforsearch"
    token_to_search = "loooooooongstr"

    if not cols_to_query:
        logger.warning("Warning! No cols to query")

    query = "select " + ", ".join(cols_to_query) + f" from {database}.{table} where "
    for col in cols_to_query:
        if not index_type or index_type == IndexType.NGRAMBF_V1:
            query += f" {col} like '%{str_to_search}%' and "
        elif index_type == IndexType.TOKENBF_v1:
            query += f" hasToken({col}, '{token_to_search}') and "
        elif index_type == IndexType.FULL_TEXT:
            query += f" hasToken({col}, '{token_to_search}') and "
    query = query[:-4]
    query += " format Null "
    return query


def generate_data_compression_benchmark_select_query(database: str, table: str) -> str:
    return f"select * from {database}.{table} format Null"