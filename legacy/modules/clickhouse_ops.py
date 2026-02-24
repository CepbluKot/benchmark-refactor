import functools
import json
import logging
import time
from typing import Dict, List
import pandas as pd
import urllib3
from clickhouse_connect.driver.client import Client
from clickhouse_connect.driver.exceptions import OperationalError
from clickhouse_connect.driver.summary import QuerySummary
from modules.bytes_formatter import make_readable_bytes
from modules.clickhouse_manager import ClickhouseManager
from modules.interfaces import IndexSizeInfo, QueryStats, QuerySummaryModel, TableColSizeInfo
from settings import settings

logger = logging.getLogger(__name__)


def is_safe_input_parameter(param: str) -> bool:
    if not isinstance(param, str):
        return False
    keywords = ["drop", "alter", "delete", "truncate", "insert", "update", "grant", "revoke"]
    lower_query = param.lower()
    if any(keyword in lower_query for keyword in keywords):
        return False
    param = param.strip()
    if not param:
        return False
    return True


def are_all_input_params_safe(params):
    return all(is_safe_input_parameter(param) for param in params)


def check_input_params_decorator(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        str_args = [arg for arg in args if isinstance(arg, str)]
        str_args.extend([kwargs[key] for key in kwargs if isinstance(kwargs[key], str)])
        if not are_all_input_params_safe(str_args):
            raise Exception(
                f"Some input params are dangerous at {func.__name__} func: args: {args} kwargs: {kwargs}"
            )
        return func(*args, **kwargs)
    return wrapper


def check_is_stream_empty(stream: urllib3.response.HTTPResponse):
    try:
        is_empty = False
        clickhouse_summary_header = stream.headers.get("X-ClickHouse-Summary")
        if clickhouse_summary_header:
            clickhouse_summary_header_parsed = json.loads(clickhouse_summary_header)
            read_rows = clickhouse_summary_header_parsed.get("read_rows")
            read_rows = int(read_rows)
            is_empty = not bool(read_rows)
        return is_empty
    except Exception as e:
        logger.error(f"Error at check_stream_is_empty: {e}")
        return True


@check_input_params_decorator
def is_database_exists(database_client: Client, db_name: str):
    try:
        exists = database_client.command(
            f"""SELECT count() > 0 AS db_exists FROM system.databases WHERE name = '{db_name}';"""
        )
        return bool(exists)
    except Exception as e:
        logger.error(f"Error occupied during database existance check: {e}")


@check_input_params_decorator
def is_table_exists(database_client: Client, db_name: str, table_name: str) -> bool:
    try:
        exists = database_client.command(
            f"""SELECT count() > 0 AS table_exists FROM system.tables where database='{db_name}' and table='{table_name}';"""
        )
        return bool(exists)
    except Exception as e:
        logger.error(f"Error occupied during table existance check: {e}")
        return False


@check_input_params_decorator
def count_rows(client: Client, db: str, table: str) -> int:
    try:
        q = f"SELECT count() AS c FROM {db}.{table}"
        df = client.query_df(q)
        if df.empty:
            return 0
        return int(df.loc[0, "c"])
    except Exception as e:
        logger.error(f"Error occupied while counting rows for table {db}.{table}: {e}")
        return -1


@check_input_params_decorator
def get_table_names(
    database_client: Client, db_name: str, checked_tables_engine_types: List[str]
) -> List[str]:
    res: pd.DataFrame = database_client.query_df(
        f"select distinct(name) from system.tables where database = '{db_name}' and engine in {checked_tables_engine_types};"
    )
    res = list(res.get("name", default=[]))
    return res


@check_input_params_decorator
def get_table_ddl(database_client: Client, db_name: str, table_name: str) -> str:
    return (
        str(database_client.command(f"show create table {db_name}.{table_name};"))
        .replace("\\n", " ")
        .replace("\\", "")
    )


@check_input_params_decorator
def create_database(database_client: Client, db_name: str):
    try:
        if is_database_exists(database_client, db_name):
            logger.info(f"Database {db_name} already exists")
            return
        database_client.command(f"create database {db_name};")
    except Exception as e:
        logger.error(f"Error occupied during database creation: {e}")


@check_input_params_decorator
def copy_table_structure(
    source_database_client: Client,
    source_db_name: str,
    source_table_name: str,
    target_database_client: Client,
    target_db_name: str,
    target_table_name: str,
):
    try:
        create_database(target_database_client, target_db_name)
        if is_table_exists(target_database_client, target_db_name, target_table_name):
            logger.info(f"Table {target_db_name}.{target_table_name} already exists")
            return
        table_ddl = get_table_ddl(source_database_client, source_db_name, source_table_name)
        table_ddl = table_ddl.replace(
            f"CREATE TABLE {source_db_name}.{source_table_name}",
            f"CREATE TABLE {target_db_name}.{target_table_name}",
        )
        target_database_client.command(table_ddl)
    except Exception as e:
        logger.error(f"Error occupied during initial tables copies creation: {e}")


@check_input_params_decorator
def drop_database(database_client: Client, db_name: str, test_db_postfix: str):
    try:
        if test_db_postfix not in db_name:
            logger.warning("Attempt to delete an important db! Aborting...")
            return
        if not is_database_exists(database_client, db_name):
            logger.info(f"Database {db_name} does not exists")
            return
        database_client.command(f"drop database {db_name} format Null")
    except Exception as e:
        logger.error(f"Error occupied during database drop: {e}")


@check_input_params_decorator
def drop_table(
    database_client: Client,
    target_db_name: str,
    target_table_name: str,
    test_db_postfix: str,
):
    if not is_table_exists(database_client, target_db_name, target_table_name):
        logger.info(f"Table for deletion {target_db_name}.{target_table_name} doesnt exist")
        return
    if test_db_postfix not in target_db_name:
        logger.warning(
            f"Attempt to delete table at important db (test_db_postfix: {test_db_postfix}, target_db_name: {target_db_name})! Aborting..."
        )
        return
    try:
        q = f"drop table {target_db_name}.{target_table_name} format Null"
        logger.info(f"dropped table {target_db_name}.{target_table_name}")
        database_client.command(q)
    except Exception as e:
        logger.error(f"Error occupied during table {target_db_name}.{target_table_name} deletion: {e}")


@check_input_params_decorator
def get_table_columns_size_bytes(
    database_client: Client, db_name: str, table_name: str, col_name: str = ""
) -> Dict[str, TableColSizeInfo]:
    try:
        res = {}
        if not is_table_exists(database_client, db_name, table_name):
            logger.info(f"Table {db_name}.{table_name} does not exists")
            return {}
        query = f"""select name, type, data_compressed_bytes from system.columns where database = '{db_name}' and table = '{table_name}';"""
        if col_name:
            query = f"""select name, type, data_compressed_bytes from system.columns where database = '{db_name}' and table = '{table_name}' and name = '{col_name}';"""
        query_res: pd.DataFrame = database_client.query_df(query)
        for elem in query_res.values:
            if len(elem) == 3:
                res[elem[0]] = TableColSizeInfo(
                    name=elem[0],
                    datatype=elem[1],
                    size_compressed_bytes=elem[2],
                    size_compressed_bytes_readable=make_readable_bytes(elem[2]),
                )
        return res
    except Exception as e:
        logger.error(f"Error occupied during gaining info about table column sizes: {e}")
        return {}


@check_input_params_decorator
def get_table_total_size_compressed_bytes(
    database_client: Client,
    db_name: str,
    table_name: str,
) -> int:
    try:
        if not is_table_exists(database_client, db_name, table_name):
            logger.info(f"Table {db_name}.{table_name} does not exists")
            return -1
        logger.info("starting count_rows from get_table_total_size_compressed_bytes")
        if not count_rows(database_client, db_name, table_name):
            return 0
        query_res = database_client.command(
            f"""
                SELECT
                    (sum(data_compressed_bytes)) as compressed_bytes
                FROM system.parts
                WHERE database='{db_name}' and table='{table_name}'
                GROUP BY database, table;
            """
        )
        res = -1
        try:
            res = int(query_res)
        except Exception as e:
            logger.error(f"Error occupied during table size conversion to int: query_res={query_res}, error: {e}")
        return res
    except Exception as e:
        logger.error(f"Error occupied during gaining info about table column sizes: {e}")
        return -1


@check_input_params_decorator
def get_table_indexes_sizes_compressed_bytes(
    database_client: Client,
    db_name: str,
    table_name: str,
) -> Dict[str, IndexSizeInfo]:
    res = {}
    try:
        if not is_table_exists(database_client, db_name, table_name):
            logger.info(f"Table {db_name}.{table_name} does not exists")
            return res
        query_res: pd.DataFrame = database_client.query_df(
            f"""SELECT expr, data_compressed_bytes FROM system.data_skipping_indices WHERE database = '{db_name}' and table = '{table_name}';"""
        )
        for row in query_res.values:
            if len(row) == 2:
                res[row[0]] = IndexSizeInfo(
                    size_compressed_bytes=int(row[1]),
                    size_compressed_bytes_readable=make_readable_bytes(int(row[1])),
                )
    except Exception as e:
        logger.error(f"Error occupied during gaining info about table column sizes: {e}")
    return res


@check_input_params_decorator
def copy_data_by_stream(
    source_database_client: Client,
    source_db_name: str,
    source_table_name: str,
    target_database_client: Client,
    target_db_name: str,
    target_table_name: str,
    n_rows: int = 1_000_000,
    strictly_adhere_n_rows: bool = True,
    tested_cols: List[str] = [],
    src_clickhouse_manager: ClickhouseManager | None = None,
    raise_on_operational_error: bool = False,
    offset: int = 0,
) -> QuerySummaryModel | None:
    if n_rows <= 0:
        logger.warning(f"Got {n_rows} rows to copy at stream copy. Exiting")
        return
    if offset < 0:
        logger.warning(f"Got {offset} offset at stream copy. Exiting")
        return

    n_rows_copied = -1
    src_client_stream = None
    try:
        total_rows_in_source_table = count_rows(source_database_client, source_db_name, source_table_name)
        if total_rows_in_source_table == -1:
            logger.error("cant copy data due to invalid total n rows: total_rows_in_source_table == -1")
            return

        tested_cols_query_part = ""
        if tested_cols:
            tested_cols_query_part += " where "
            for col in tested_cols:
                tested_cols_query_part += f"{col} != '' and "
            tested_cols_query_part = tested_cols_query_part[:-4]

        if strictly_adhere_n_rows and total_rows_in_source_table < n_rows:
            q = f"""
                WITH
                ifNull((SELECT count() FROM {source_db_name}.{source_table_name}), 0) AS cnt,
                if(cnt = 0, 0, intDiv({n_rows} + cnt - 1, cnt)) AS repeats,
                if(repeats=0, 1, repeats) as repeats_not_equal_zero
                SELECT *
                FROM (select * from {source_db_name}.{source_table_name}, numbers(repeats_not_equal_zero) AS n
                {tested_cols_query_part}
                LIMIT {n_rows} OFFSET {offset})
            """
            n_rows_copied = n_rows
        else:
            q = f"SELECT * FROM {source_db_name}.{source_table_name} {tested_cols_query_part} limit {n_rows} OFFSET {offset}"
            n_rows_copied = min(n_rows, total_rows_in_source_table)

        if src_clickhouse_manager:
            stream_acquired = src_clickhouse_manager.acquire_stream_slot()
            if not stream_acquired:
                raise RuntimeError("Timeout acquiring ClickHouse stream slot in copy_data_by_stream")

        src_client_stream = source_database_client.raw_stream(q, fmt="Native")
        is_empty = check_is_stream_empty(src_client_stream)
        if is_empty:
            logger.info(f"Пустой результат - прекращаем копирование данных для {source_db_name}.{source_table_name}")
            return

        query_summary = target_database_client.raw_insert(
            table=f"{target_db_name}.{target_table_name}",
            insert_block=src_client_stream,
            fmt="Native",
        )
        logger.info(
            "Из %s.%s в таблицу %s.%s: скопировано %d строк.",
            source_db_name, source_table_name,
            target_db_name, target_table_name,
            n_rows_copied,
        )
        return QuerySummaryModel(
            read_rows=int(query_summary.summary.get("read_rows", -1)),
            read_bytes=int(query_summary.summary.get("read_bytes", -1)),
            written_rows=int(query_summary.summary.get("written_rows", -1)),
            written_bytes=int(query_summary.summary.get("written_bytes", -1)),
            elapsed_ns=int(query_summary.summary.get("elapsed_ns", -1)),
        )
    except OperationalError as e:
        logger.error(f"Operational error: {e}")
        if raise_on_operational_error:
            logger.error(f"Raising on operational error: {e}")
            raise OperationalError
    except Exception as e:
        logger.error(f"Unexpected error occupied during data copy: {e}")
    finally:
        if src_client_stream:
            src_client_stream.close()
        if src_clickhouse_manager:
            src_clickhouse_manager.release_stream_slot()


@check_input_params_decorator
def copy_data_by_stream_and_measure_stats(
    source_database_client: Client,
    source_db_name: str,
    source_table_name: str,
    target_database_client: Client,
    target_db_name: str,
    target_table_name: str,
    n_rows: int = 1_000_000,
    strictly_adhere_n_rows: bool = True,
    tested_cols: List[str] = [],
    n_measurements: int = 3,
    src_clickhouse_manager: ClickhouseManager | None = None,
) -> QueryStats | None:
    try:
        curr_measurement_n = 0
        n_attempts = 0
        sleep_sec = settings.MAX_COPY_RETRY_SLEEP_SEC
        read_bytes_per_second_entries: List[float] = []
        written_bytes_per_second_entries: List[float] = []
        read_rows_per_second_entries: List[float] = []
        written_rows_per_second_entries: List[float] = []
        elapsed_ns_entries: List[float] = []
        read_rows_entries: List[int] = []
        written_rows_entries: List[int] = []
        failed = False
        curr_offset = 0

        while curr_measurement_n < n_measurements:
            if settings.MAX_COPY_N_RETRIES != -1 and n_attempts > settings.MAX_COPY_N_RETRIES:
                logger.warning(
                    f"Cant get copy_data_by_stream_and_measure_stats for table {target_db_name}.{target_table_name}, max n of attempts exceeded"
                )
                failed = True
                break
            try:
                query_summary = copy_data_by_stream(
                    source_database_client=source_database_client,
                    source_db_name=source_db_name,
                    source_table_name=source_table_name,
                    target_database_client=target_database_client,
                    target_db_name=target_db_name,
                    target_table_name=target_table_name,
                    n_rows=n_rows,
                    strictly_adhere_n_rows=strictly_adhere_n_rows,
                    tested_cols=tested_cols,
                    src_clickhouse_manager=src_clickhouse_manager,
                    raise_on_operational_error=True,
                    offset=curr_offset,
                )
                curr_offset += n_rows
            except Exception as e:
                msg = (
                    f"Warning, could not perform select stream query test. Attempt #{n_attempts} / "
                    + (f"{settings.MAX_COPY_N_RETRIES}" if settings.MAX_COPY_N_RETRIES != -1 else "infinite amount")
                )
                msg += f". Sleeping for {sleep_sec} sec. Error: {e}"
                logger.error(msg)
                n_attempts += 1
                time.sleep(sleep_sec)
                sleep_sec += settings.MAX_COPY_RETRY_SLEEP_SEC_INCREMENT
                continue

            if query_summary:
                elapsed_sec = query_summary.elapsed_ns / 1_000_000_000 if query_summary.elapsed_ns != -1 else -1
                read_rows_per_second_entries.append(query_summary.read_rows / elapsed_sec)
                written_rows_per_second_entries.append(query_summary.written_rows / elapsed_sec)
                read_bytes_per_second_entries.append(query_summary.read_bytes / elapsed_sec)
                written_bytes_per_second_entries.append(query_summary.written_bytes / elapsed_sec)
                elapsed_ns_entries.append(query_summary.elapsed_ns)
                read_rows_entries.append(query_summary.read_rows)
                written_rows_entries.append(query_summary.written_rows)
                curr_measurement_n += 1

        if not failed:
            return QueryStats(
                read_bytes_per_second_measurements=read_bytes_per_second_entries,
                written_bytes_per_second_measurements=written_bytes_per_second_entries,
                read_rows_per_second_measurements=read_rows_per_second_entries,
                written_rows_per_second_measurements=written_rows_per_second_entries,
                elapsed_ns_measurements=elapsed_ns_entries,
                read_rows_measurements=read_rows_entries,
                written_rows_measurements=written_rows_entries,
            )
    except Exception as e:
        logger.error(f"Error occupied during copy_data_by_stream_and_measure_insert_time_ms: {e}")


@check_input_params_decorator
def select_and_measure_stats(
    target_database_w_timeout: Client,
    target_db_name: str,
    target_table_name: str,
    select_query: str,
    n_measurements: int = 3,
) -> QueryStats | None:
    try:
        read_bytes_per_second_entries: List[float] = []
        written_bytes_per_second_entries: List[float] = []
        read_rows_per_second_entries: List[float] = []
        written_rows_per_second_entries: List[float] = []
        elapsed_ns_entries: List[float] = []
        read_rows_entries: List[int] = []
        written_rows_entries: List[int] = []
        sleep_sec = 0
        curr_measurement_n = 0
        n_attempts = 0
        failed = False

        while curr_measurement_n < n_measurements:
            if n_attempts > 10:
                logger.warning(f"Cant measure select time for table {target_db_name}.{target_table_name}")
                failed = True
                break

            query_summary = target_database_w_timeout.command(select_query)
            if not isinstance(query_summary, QuerySummary):
                logger.error("Error, query summary is not instance of QuerySummary")
                return

            read_rows = int(query_summary.summary.get("read_rows", -1))
            read_bytes = int(query_summary.summary.get("read_bytes", -1))
            written_rows = int(query_summary.summary.get("written_rows", -1))
            written_bytes = int(query_summary.summary.get("written_bytes", -1))
            elapsed_ns = int(query_summary.summary.get("elapsed_ns", -1))

            if elapsed_ns == -1:
                msg = (
                    f"Warning, could not perform select stream query test. Attempt #{n_attempts} / "
                    + (f"{settings.MAX_COPY_N_RETRIES}" if settings.MAX_COPY_N_RETRIES != -1 else "infinite amount")
                )
                msg += f". Sleeping for {sleep_sec} sec."
                logger.error(msg)
                n_attempts += 1
                time.sleep(sleep_sec)
                sleep_sec += settings.MAX_COPY_RETRY_SLEEP_SEC_INCREMENT
                continue

            elapsed_sec = elapsed_ns / 1_000_000_000 if elapsed_ns != -1 else -1
            read_rows_per_second_entries.append(read_rows / elapsed_sec)
            written_rows_per_second_entries.append(written_rows / elapsed_sec)
            read_bytes_per_second_entries.append(read_bytes / elapsed_sec)
            written_bytes_per_second_entries.append(written_bytes / elapsed_sec)
            elapsed_ns_entries.append(elapsed_ns)
            read_rows_entries.append(read_rows)
            written_rows_entries.append(written_rows)
            curr_measurement_n += 1

        if not failed:
            return QueryStats(
                read_bytes_per_second_measurements=read_bytes_per_second_entries,
                written_bytes_per_second_measurements=written_bytes_per_second_entries,
                read_rows_per_second_measurements=read_rows_per_second_entries,
                written_rows_per_second_measurements=written_rows_per_second_entries,
                elapsed_ns_measurements=elapsed_ns_entries,
                read_rows_measurements=read_rows_entries,
                written_rows_measurements=written_rows_entries,
            )
        else:
            logger.error("Error occupied at select and measure stats")
    except Exception as e:
        logger.error(f"Error occupied while measuring avg select time: {e}")