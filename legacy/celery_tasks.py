import json
import logging
import uuid
from typing import Dict, List
import numpy as np
import sqlparse
from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown, worker_ready
from modules.bytes_formatter import make_readable_bytes
from modules.clickhouse_manager import ClickhouseManager
from modules.clickhouse_ops import (
    copy_data_by_stream,
    copy_data_by_stream_and_measure_stats,
    count_rows,
    create_database,
    drop_table,
    get_table_columns_size_bytes,
    get_table_indexes_sizes_compressed_bytes,
    get_table_total_size_compressed_bytes,
    select_and_measure_stats,
)
from modules.interfaces import (
    DataCompressionBenchmarkResultModel,
    IndexBenchmarkResultModel,
    IndexType,
    QueryStats,
    TableColSizeInfo,
)
from modules.sql_query_generators import (
    generate_data_compression_benchmark_select_query,
    generate_indexes_benchmark_select_query,
)
from modules.sqlalchemy_stuff.engine import Session
from modules.sqlalchemy_stuff.tables import DataCompressionBenchmarkResults, IndexesBenchmarkResults
from settings import settings

logger = logging.getLogger(__name__)

rmq_login = settings.RABBITMQ_LOGIN.get_secret_value()
rmq_password = settings.RABBITMQ_PASSWORD.get_secret_value()

app: Celery = Celery(
    "celery_tasks",
    broker=f"pyamqp://{rmq_login}:{rmq_password}@{settings.RABBITMQ_HOSTNAME}:{settings.RABBITMQ_PORT}//",
    backend=f"rpc://{rmq_login}:{rmq_password}@{settings.RABBITMQ_HOSTNAME}:{settings.RABBITMQ_PORT}//",
)

app.conf.update(worker_concurrency=settings.CELERY_WORKER_CONCURRENCY)

ch_manager_src = ClickhouseManager(
    host=settings.SRC_DATABASE_HOST,
    port=settings.SRC_DATABASE_PORT,
    username=settings.SRC_DATABASE_USERNAME.get_secret_value(),
    password=settings.SRC_DATABASE_PASSWORD.get_secret_value(),
    max_pool_connections=settings.CLICKHOUSE_MANAGER_MAX_POOL_CONNECTIONS,
    num_pools=settings.CLICKHOUSE_MANAGER_NUM_POOLS,
    max_concurrent_streams=settings.CLICKHOUSE_MANAGER_MAX_CONCURRENT_STREAMS_PER_PROCESS,
)

ch_manager_target = ClickhouseManager(
    host=settings.TGT_DATABASE_HOST,
    port=settings.TGT_DATABASE_PORT,
    username=settings.TGT_DATABASE_USERNAME.get_secret_value(),
    password=settings.TGT_DATABASE_PASSWORD.get_secret_value(),
    max_pool_connections=settings.CLICKHOUSE_MANAGER_MAX_POOL_CONNECTIONS,
    num_pools=settings.CLICKHOUSE_MANAGER_NUM_POOLS,
    max_concurrent_streams=settings.CLICKHOUSE_MANAGER_MAX_CONCURRENT_STREAMS_PER_PROCESS,
)

ch_manager_target_w_timeout = ClickhouseManager(
    host=settings.TGT_DATABASE_HOST,
    port=settings.TGT_DATABASE_PORT,
    username=settings.TGT_DATABASE_USERNAME.get_secret_value(),
    password=settings.TGT_DATABASE_PASSWORD.get_secret_value(),
    max_pool_connections=settings.CLICKHOUSE_MANAGER_MAX_POOL_CONNECTIONS,
    num_pools=settings.CLICKHOUSE_MANAGER_NUM_POOLS,
    max_concurrent_streams=settings.CLICKHOUSE_MANAGER_MAX_CONCURRENT_STREAMS_PER_PROCESS,
    send_receive_timeout=settings.INDEXES_BENCHMARK_SELECT_QUERY_SEND_RECEIVE_TIMEOUT_SEC,
)


@worker_ready.connect
def _announce_build_info(sender=None, **kwargs):
    logger.info("=== Build metadata ===")
    logger.info("Build date: %s", settings.BUILD_DATETIME)
    logger.info("Git commit: %s", settings.GIT_COMMIT)
    logger.info("Git branch: %s", settings.GIT_BRANCH)
    logger.info("======================")

@worker_process_init.connect
def _on_worker_process_init(**kwargs):
    ch_manager_src.init()
    ch_manager_target.init()
    ch_manager_target_w_timeout.init()

@worker_process_shutdown.connect
def _on_worker_process_shutdown(**kwargs):
    try:
        ch_manager_src.close()
        ch_manager_target.close()
        ch_manager_target_w_timeout.close()
    except Exception as e:
        logger.error(f"Failed to close ClickhouseManager in worker_process_shutdown: {e}")


@app.task
def benchmark_one_table_data_compression_variant_celery_job(
    source_db_name: str,
    source_table_name: str,
    tested_db_name: str,
    tested_table_name: str,
    tested_table_ddl: str,
    is_source_table_copy: bool,
    benchmark_id: int,
    source_table_ddl: str = "",
    source_table_n_rows: int = -1,
    source_table_insert_time_ms_measurements: List[float] = [],
    source_table_insert_time_ms_measurements_percentiles: List[float] = [],
    source_table_insert_rows_per_second_measurements: List[float] = [],
    source_table_insert_rows_per_second_measurements_percentiles: List[float] = [],
    source_table_insert_bytes_per_second_measurements: List[float] = [],
    source_table_insert_bytes_per_second_measurements_readable: List[str] = [],
    source_table_insert_bytes_per_second_measurements_percentiles: List[float] = [],
    source_table_select_test_query: str = "",
    source_table_select_time_ms_measurements: List[float] = [],
    source_table_select_time_ms_measurements_percentiles: List[float] = [],
    source_table_select_rows_per_second_measurements: List[float] = [],
    source_table_select_rows_per_second_measurements_percentiles: List[float] = [],
    source_table_select_bytes_per_second_measurements: List[float] = [],
    source_table_select_bytes_per_second_measurements_readable: List[str] = [],
    source_table_select_bytes_per_second_measurements_percentiles: List[float] = [],
    source_table_consumed_compressed_size_bytes_by_each_column: str = "",
    source_table_consumed_compressed_size_bytes_overall: float = -1,
    source_table_n_rows_in_size_test: int = -1,
    res_uuid: str = "",
    db_postfix: str = settings.TEST_DATA_COMPRESSION_DB_POSTFIX,
) -> str:
    database_src = ch_manager_src.get_client()
    database_target = ch_manager_target.get_client()
    database_target_w_timeout = ch_manager_target_w_timeout.get_client()

    try:
        logger.info(
            f"Spawned job for benchmarking table: Test table name - {tested_db_name}.{tested_table_name}, Source table name - {source_db_name}.{source_table_name}"
        )

        # ---------------------------  Init table  ----------------------------
        logger.info(f"testing table ddl: {tested_table_ddl}")
        try:
            database_target.command(tested_table_ddl)
        except Exception as e:
            logger.warning(
                f"Error occurred during table creation for data compression benchmark, trying to drop/create. Error: {e}"
            )
            create_database(database_target, tested_db_name)
            drop_table(database_target, tested_db_name, tested_table_name, db_postfix)
            try:
                database_target.command(tested_table_ddl)
            except Exception as e:
                logger.error(
                    f"Error occurred during table creation for data compression benchmark, skipping table. Error: {e}, \n\ntest_table_ddl: {tested_table_ddl}"
                )
                return ""

        logger.info(f"copying data for {tested_db_name}.{tested_table_name}")

        # ---------------------------  Insert test  ----------------------------
        insert_stats = copy_data_by_stream_and_measure_stats(
            source_database_client=database_src,
            source_db_name=source_db_name,
            source_table_name=source_table_name,
            target_database_client=database_target,
            target_db_name=tested_db_name,
            target_table_name=tested_table_name,
            n_rows=settings.N_INSERT_ROWS_FOR_DATA_COMPRESSION_BENCHMARK,
            n_measurements=settings.INSERT_TIME_TEST_N_MEASUREMENTS_FOR_DATA_COMPRESSION_BENCHMARK,
            src_clickhouse_manager=ch_manager_src,
        )

        if not insert_stats:
            logger.error(f"Could not get stats for table {source_db_name}.{source_table_name}")
            return ""

        tested_table_insert_time_ms_measurements = (
            np.array(insert_stats.elapsed_ns_measurements) / 1_000_000
        )
        tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs = []
        tested_table_insert_time_ms_measurements_percentiles = np.percentile(
            tested_table_insert_time_ms_measurements, settings.MEASURED_PERCENTILES, method="linear"
        )
        if source_table_insert_time_ms_measurements_percentiles and len(
            tested_table_insert_time_ms_measurements_percentiles
        ) == len(source_table_insert_time_ms_measurements_percentiles):
            tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs = (
                source_table_insert_time_ms_measurements_percentiles
                / tested_table_insert_time_ms_measurements_percentiles
            )

        # rows per sec
        tested_table_insert_rows_per_second_measurements = np.array(
            insert_stats.read_rows_per_second_measurements
        )
        tested_table_insert_rows_per_second_measurements_percentiles = np.percentile(
            tested_table_insert_rows_per_second_measurements,
            settings.MEASURED_PERCENTILES,
            method="linear",
        )

        # bytes per sec
        tested_table_insert_bytes_per_second_measurements = np.array(
            insert_stats.read_bytes_per_second_measurements
        )
        tested_table_insert_bytes_per_second_measurements_readable = [
            make_readable_bytes(elem) for elem in tested_table_insert_bytes_per_second_measurements
        ]
        tested_table_insert_bytes_per_second_measurements_percentiles = np.percentile(
            tested_table_insert_bytes_per_second_measurements,
            settings.MEASURED_PERCENTILES,
            method="linear",
        )
        tested_table_insert_bytes_per_second_measurements_percentiles_readable = [
            make_readable_bytes(elem)
            for elem in tested_table_insert_bytes_per_second_measurements_percentiles
        ]
        source_table_insert_bytes_per_second_measurements_percentiles_readable = [
            make_readable_bytes(elem)
            for elem in source_table_insert_bytes_per_second_measurements_percentiles
        ]

        # ---------------------------  Select test  ----------------------------
        tested_table_select_test_query = generate_data_compression_benchmark_select_query(
            tested_db_name, tested_table_name
        )
        tested_table_select_stats = select_and_measure_stats(
            target_database_w_timeout=database_target_w_timeout,
            target_db_name=tested_db_name,
            target_table_name=tested_table_name,
            select_query=tested_table_select_test_query,
            n_measurements=settings.SELECT_TIME_TEST_N_MEASUREMENTS_FOR_INDEXES_BENCHMARK,
        )
        if not tested_table_select_stats:
            return ""

        tested_table_select_time_ms_measurements = (
            np.array(tested_table_select_stats.elapsed_ns_measurements) / 1_000_000
        )
        tested_table_select_time_ms_measurements_percentiles_speed_up_coefs = []
        tested_table_select_time_ms_measurements_percentiles = np.percentile(
            tested_table_select_time_ms_measurements, settings.MEASURED_PERCENTILES, method="linear"
        )
        if source_table_select_time_ms_measurements and len(
            tested_table_select_time_ms_measurements_percentiles
        ) == len(source_table_select_time_ms_measurements_percentiles):
            tested_table_select_time_ms_measurements_percentiles_speed_up_coefs = (
                source_table_select_time_ms_measurements_percentiles
                / tested_table_select_time_ms_measurements_percentiles
            )

        tested_table_select_rows_per_second_measurements = (
            tested_table_select_stats.read_rows_per_second_measurements
        )
        tested_table_select_rows_per_second_measurements_percentiles = np.percentile(
            tested_table_select_rows_per_second_measurements,
            settings.MEASURED_PERCENTILES,
            method="linear",
        )

        tested_table_select_bytes_per_second_measurements = (
            tested_table_select_stats.read_bytes_per_second_measurements
        )
        tested_table_select_bytes_per_second_measurements_readable = [
            make_readable_bytes(elem) for elem in tested_table_select_bytes_per_second_measurements
        ]
        tested_table_select_bytes_per_second_measurements_percentiles = np.percentile(
            tested_table_select_bytes_per_second_measurements,
            settings.MEASURED_PERCENTILES,
            method="linear",
        )
        tested_table_select_bytes_per_second_measurements_percentiles_readable = [
            make_readable_bytes(elem)
            for elem in tested_table_select_bytes_per_second_measurements_percentiles
        ]
        source_table_select_bytes_per_second_measurements_percentiles_readable = []
        if source_table_select_bytes_per_second_measurements_percentiles:
            source_table_select_bytes_per_second_measurements_percentiles_readable = [
                make_readable_bytes(elem)
                for elem in source_table_select_bytes_per_second_measurements_percentiles
            ]

        # ---------------------------  Compression  ----------------------------
        logger.info(f"measuring space for {tested_db_name}.{tested_table_name}")
        tested_table_consumed_compressed_size_bytes_by_each_column = get_table_columns_size_bytes(
            database_target, tested_db_name, tested_table_name
        )
        tested_table_consumed_compressed_size_bytes_by_each_column_serialized = {}
        for key in tested_table_consumed_compressed_size_bytes_by_each_column:
            tested_table_consumed_compressed_size_bytes_by_each_column_serialized[key] = (
                tested_table_consumed_compressed_size_bytes_by_each_column[key].model_dump()
            )

        tested_table_n_rows_in_size_test = count_rows(
            database_target, tested_db_name, tested_table_name
        )
        tested_table_consumed_compressed_size_bytes_overall = get_table_total_size_compressed_bytes(
            database_target, tested_db_name, tested_table_name
        )

        tested_table_compression_overall_coef = -1
        if (
            source_table_consumed_compressed_size_bytes_overall
            and tested_table_consumed_compressed_size_bytes_overall
            and source_table_consumed_compressed_size_bytes_overall != -1
            and tested_table_consumed_compressed_size_bytes_overall != -1
        ):
            tested_table_compression_overall_coef = round(
                source_table_consumed_compressed_size_bytes_overall
                / tested_table_consumed_compressed_size_bytes_overall,
                2,
            )

        source_table_consumed_compressed_size_bytes_by_each_column_deserialized = {}
        if source_table_consumed_compressed_size_bytes_by_each_column:
            source_table_consumed_compressed_size_bytes_by_each_column_deserialized: Dict[
                str, str
            ] = json.loads(source_table_consumed_compressed_size_bytes_by_each_column)

        tested_table_compression_by_each_column_coef: Dict[str, float] = {}
        if (
            tested_table_consumed_compressed_size_bytes_by_each_column
            and source_table_consumed_compressed_size_bytes_by_each_column
        ):
            for col_name in tested_table_consumed_compressed_size_bytes_by_each_column:
                tested_table_col_vals = tested_table_consumed_compressed_size_bytes_by_each_column[col_name]
                source_table_col_vals_serialized = (
                    source_table_consumed_compressed_size_bytes_by_each_column_deserialized[col_name]
                )
                source_table_col_vals = TableColSizeInfo.model_validate(
                    source_table_col_vals_serialized
                )
                tested_table_compression_by_each_column_coef[col_name] = -1
                if (
                    source_table_col_vals.size_compressed_bytes
                    and tested_table_col_vals.size_compressed_bytes
                ):
                    tested_table_compression_by_each_column_coef[col_name] = round(
                        source_table_col_vals.size_compressed_bytes
                        / tested_table_col_vals.size_compressed_bytes,
                        2,
                    )

        tested_table_n_rows_in_size_test = count_rows(
            database_target, tested_db_name, tested_table_name
        )

        # ---------------------------  Upload res  ----------------------------
        drop_table(database_target, tested_db_name, tested_table_name, db_postfix)

        if not res_uuid:
            res_uuid = str(uuid.uuid4())

        new_res = DataCompressionBenchmarkResults(
            # ---------------------------  Metadata  ----------------------------
            id=res_uuid,
            benchmark_id=benchmark_id,
            source_db_name=source_db_name,
            source_table_name=source_table_name,
            tested_table_ddl=tested_table_ddl,
            source_table_ddl=source_table_ddl,
            is_source_table_copy=is_source_table_copy,
            total_n_rows_in_tested_table=sum(insert_stats.written_rows_measurements),
            total_n_rows_in_source_table=source_table_n_rows,
            measured_percentiles=settings.MEASURED_PERCENTILES,
            # ---------------------------  Insert test results  ----------------------------
            insert_test_n_rows=settings.N_INSERT_ROWS_FOR_DATA_COMPRESSION_BENCHMARK,
            tested_table_insert_time_ms_measurements=list(tested_table_insert_time_ms_measurements),
            source_table_insert_time_ms_measurements=source_table_insert_time_ms_measurements,
            tested_table_insert_time_ms_measurements_percentiles=list(
                tested_table_insert_time_ms_measurements_percentiles
            ),
            source_table_insert_time_ms_measurements_percentiles=source_table_insert_time_ms_measurements_percentiles,
            tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs=list(
                tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs
            ),
            tested_table_insert_rows_per_second_measurements=list(
                tested_table_insert_rows_per_second_measurements
            ),
            source_table_insert_rows_per_second_measurements=source_table_insert_rows_per_second_measurements,
            tested_table_insert_rows_per_second_measurements_percentiles=list(
                tested_table_insert_rows_per_second_measurements_percentiles
            ),
            source_table_insert_rows_per_second_measurements_percentiles=source_table_insert_rows_per_second_measurements_percentiles,
            tested_table_insert_bytes_per_second_measurements=list(
                tested_table_insert_bytes_per_second_measurements
            ),
            tested_table_insert_bytes_per_second_measurements_readable=list(
                tested_table_insert_bytes_per_second_measurements_readable
            ),
            source_table_insert_bytes_per_second_measurements=source_table_insert_bytes_per_second_measurements,
            source_table_insert_bytes_per_second_measurements_readable=source_table_insert_bytes_per_second_measurements_readable,
            tested_table_insert_bytes_per_second_measurements_percentiles=list(
                tested_table_insert_bytes_per_second_measurements_percentiles
            ),
            tested_table_insert_bytes_per_second_measurements_percentiles_readable=list(
                tested_table_insert_bytes_per_second_measurements_percentiles_readable
            ),
            source_table_insert_bytes_per_second_measurements_percentiles=source_table_insert_bytes_per_second_measurements_percentiles,
            source_table_insert_bytes_per_second_measurements_percentiles_readable=source_table_insert_bytes_per_second_measurements_percentiles_readable,
            # ---------------------------  Select test results  ----------------------------
            tested_table_select_test_query=sqlparse.format(
                tested_table_select_test_query, reindent=True, keyword_case="upper"
            ),
            source_table_select_test_query=sqlparse.format(
                source_table_select_test_query, reindent=True, keyword_case="upper"
            ),
            tested_table_select_time_ms_measurements=list(tested_table_select_time_ms_measurements),
            source_table_select_time_ms_measurements=source_table_select_time_ms_measurements,
            tested_table_select_time_ms_measurements_percentiles=list(
                tested_table_select_time_ms_measurements_percentiles
            ),
            source_table_select_time_ms_measurements_percentiles=source_table_select_time_ms_measurements_percentiles,
            tested_table_select_time_ms_measurements_percentiles_speed_up_coefs=list(
                tested_table_select_time_ms_measurements_percentiles_speed_up_coefs
            ),
            tested_table_select_rows_per_second_measurements=list(
                tested_table_select_rows_per_second_measurements
            ),
            source_table_select_rows_per_second_measurements=source_table_select_rows_per_second_measurements,
            tested_table_select_rows_per_second_measurements_percentiles=list(
                tested_table_select_rows_per_second_measurements_percentiles
            ),
            source_table_select_rows_per_second_measurements_percentiles=source_table_select_rows_per_second_measurements_percentiles,
            tested_table_select_bytes_per_second_measurements=list(
                tested_table_select_bytes_per_second_measurements
            ),
            tested_table_select_bytes_per_second_measurements_readable=list(
                tested_table_select_bytes_per_second_measurements_readable
            ),
            source_table_select_bytes_per_second_measurements=source_table_select_bytes_per_second_measurements,
            source_table_select_bytes_per_second_measurements_readable=source_table_select_bytes_per_second_measurements_readable,
            tested_table_select_bytes_per_second_measurements_percentiles=list(
                tested_table_select_bytes_per_second_measurements_percentiles
            ),
            tested_table_select_bytes_per_second_measurements_percentiles_readable=list(
                tested_table_select_bytes_per_second_measurements_percentiles_readable
            ),
            source_table_select_bytes_per_second_measurements_percentiles=source_table_select_bytes_per_second_measurements_percentiles,
            source_table_select_bytes_per_second_measurements_percentiles_readable=source_table_select_bytes_per_second_measurements_percentiles_readable,
            # ---------------------------  Compression results  ----------------------------
            tested_table_consumed_compressed_size_bytes_by_each_column=json.dumps(
                tested_table_consumed_compressed_size_bytes_by_each_column_serialized,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            source_table_consumed_compressed_size_bytes_by_each_column=json.dumps(
                source_table_consumed_compressed_size_bytes_by_each_column,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            tested_table_consumed_compressed_size_bytes_overall=tested_table_consumed_compressed_size_bytes_overall,
            tested_table_consumed_compressed_size_bytes_overall_readable=make_readable_bytes(
                tested_table_consumed_compressed_size_bytes_overall
            ),
            source_table_consumed_compressed_size_bytes_overall=source_table_consumed_compressed_size_bytes_overall,
            source_table_consumed_compressed_size_bytes_overall_readable=make_readable_bytes(
                source_table_consumed_compressed_size_bytes_overall
            ),
            tested_table_compression_overall_coef=tested_table_compression_overall_coef,
            tested_table_compression_by_each_column_coef=json.dumps(
                tested_table_compression_by_each_column_coef,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            source_table_n_rows_in_size_test=source_table_n_rows_in_size_test,
            tested_table_n_rows_in_size_test=tested_table_n_rows_in_size_test,
        )

        benchmark_results_db_sqlalchemy_session = Session()
        try:
            benchmark_results_db_sqlalchemy_session.add(new_res)
            benchmark_results_db_sqlalchemy_session.commit()
        except Exception as e:
            logger.error(f"Error occurred while committing new data compression benchmark results: {e}")
            benchmark_results_db_sqlalchemy_session.rollback()
        benchmark_results_db_sqlalchemy_session.close()

        if is_source_table_copy:
            return DataCompressionBenchmarkResultModel(
                # ---------------------------  Metadata  ----------------------------
                benchmark_id=benchmark_id,
                source_db_name=source_db_name,
                source_table_name=source_table_name,
                tested_table_ddl=tested_table_ddl,
                source_table_ddl=source_table_ddl,
                is_source_table_copy=is_source_table_copy,
                total_n_rows_in_tested_table=sum(insert_stats.written_rows_measurements),
                total_n_rows_in_source_table=source_table_n_rows,
                measured_percentiles=settings.MEASURED_PERCENTILES,
                # ---------------------------  Insert test results  ----------------------------
                insert_test_n_rows=settings.N_INSERT_ROWS_FOR_DATA_COMPRESSION_BENCHMARK,
                tested_table_insert_time_ms_measurements=list(tested_table_insert_time_ms_measurements),
                source_table_insert_time_ms_measurements=list(source_table_insert_time_ms_measurements),
                tested_table_insert_time_ms_measurements_percentiles=list(tested_table_insert_time_ms_measurements_percentiles),
                source_table_insert_time_ms_measurements_percentiles=list(source_table_insert_time_ms_measurements_percentiles),
                tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs=list(tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs),
                tested_table_insert_rows_per_second_measurements=list(tested_table_insert_rows_per_second_measurements),
                source_table_insert_rows_per_second_measurements=list(source_table_insert_rows_per_second_measurements),
                tested_table_insert_rows_per_second_measurements_percentiles=list(tested_table_insert_rows_per_second_measurements_percentiles),
                source_table_insert_rows_per_second_measurements_percentiles=list(source_table_insert_rows_per_second_measurements_percentiles),
                tested_table_insert_bytes_per_second_measurements=list(tested_table_insert_bytes_per_second_measurements),
                tested_table_insert_bytes_per_second_measurements_readable=tested_table_insert_bytes_per_second_measurements_readable,
                source_table_insert_bytes_per_second_measurements=list(source_table_insert_bytes_per_second_measurements),
                source_table_insert_bytes_per_second_measurements_readable=source_table_insert_bytes_per_second_measurements_readable,
                tested_table_insert_bytes_per_second_measurements_percentiles=list(tested_table_insert_bytes_per_second_measurements_percentiles),
                tested_table_insert_bytes_per_second_measurements_percentiles_readable=tested_table_insert_bytes_per_second_measurements_percentiles_readable,
                source_table_insert_bytes_per_second_measurements_percentiles=list(source_table_insert_bytes_per_second_measurements_percentiles),
                source_table_insert_bytes_per_second_measurements_percentiles_readable=source_table_insert_bytes_per_second_measurements_percentiles_readable,
                # ---------------------------  Select test results  ----------------------------
                tested_table_select_test_query=sqlparse.format(tested_table_select_test_query, reindent=True, keyword_case="upper"),
                source_table_select_test_query=sqlparse.format(source_table_select_test_query, reindent=True, keyword_case="upper"),
                tested_table_select_time_ms_measurements=list(tested_table_select_time_ms_measurements),
                source_table_select_time_ms_measurements=list(source_table_select_time_ms_measurements),
                tested_table_select_time_ms_measurements_percentiles=list(tested_table_select_time_ms_measurements_percentiles),
                source_table_select_time_ms_measurements_percentiles=list(source_table_select_time_ms_measurements_percentiles),
                tested_table_select_time_ms_measurements_percentiles_speed_up_coefs=list(tested_table_select_time_ms_measurements_percentiles_speed_up_coefs),
                tested_table_select_rows_per_second_measurements=tested_table_select_rows_per_second_measurements,
                source_table_select_rows_per_second_measurements=list(source_table_select_rows_per_second_measurements),
                tested_table_select_rows_per_second_measurements_percentiles=list(tested_table_select_rows_per_second_measurements_percentiles),
                source_table_select_rows_per_second_measurements_percentiles=list(source_table_select_rows_per_second_measurements_percentiles),
                tested_table_select_bytes_per_second_measurements=tested_table_select_bytes_per_second_measurements,
                tested_table_select_bytes_per_second_measurements_readable=tested_table_select_bytes_per_second_measurements_readable,
                source_table_select_bytes_per_second_measurements=list(source_table_select_bytes_per_second_measurements),
                source_table_select_bytes_per_second_measurements_readable=source_table_select_bytes_per_second_measurements_readable,
                tested_table_select_bytes_per_second_measurements_percentiles=list(tested_table_select_bytes_per_second_measurements_percentiles),
                tested_table_select_bytes_per_second_measurements_percentiles_readable=tested_table_select_bytes_per_second_measurements_percentiles_readable,
                source_table_select_bytes_per_second_measurements_percentiles=list(source_table_select_bytes_per_second_measurements_percentiles),
                source_table_select_bytes_per_second_measurements_percentiles_readable=source_table_select_bytes_per_second_measurements_percentiles_readable,
                # ---------------------------  Compression results  ----------------------------
                tested_table_consumed_compressed_size_bytes_by_each_column=json.dumps(
                    tested_table_consumed_compressed_size_bytes_by_each_column_serialized,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                source_table_consumed_compressed_size_bytes_by_each_column=json.dumps(
                    source_table_consumed_compressed_size_bytes_by_each_column,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                tested_table_consumed_compressed_size_bytes_overall=tested_table_consumed_compressed_size_bytes_overall,
                tested_table_consumed_compressed_size_bytes_overall_readable=make_readable_bytes(tested_table_consumed_compressed_size_bytes_overall),
                source_table_consumed_compressed_size_bytes_overall=source_table_consumed_compressed_size_bytes_overall,
                source_table_consumed_compressed_size_bytes_overall_readable=make_readable_bytes(source_table_consumed_compressed_size_bytes_overall),
                tested_table_compression_overall_coef=tested_table_compression_overall_coef,
                tested_table_compression_by_each_column_coef=json.dumps(
                    tested_table_compression_by_each_column_coef,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                source_table_n_rows_in_size_test=source_table_n_rows_in_size_test,
                tested_table_n_rows_in_size_test=tested_table_n_rows_in_size_test,
            ).model_dump_json()

        return ""

    except Exception as e:
        logger.error(f"Error occurred during benchmark_one_table_data_compression_variant_celery_job: {e}")
        return ""


@app.task
def benchmark_one_table_string_indexing_variant_celery_job(
    source_db_name: str,
    source_table_name: str,
    source_table_ddl: str,
    tested_db_name: str,
    tested_table_name: str,
    tested_table_ddl: str,
    is_source_table_copy: bool,
    benchmark_id: int,
    str_cols_for_index: List[str],
    index_params_str: str,
    index_type: str | None,
    source_table_select_test_query: str = "",
    source_table_insert_time_ms_measurements: List[float] = [],
    source_table_insert_time_ms_measurements_percentiles: List[float] = [],
    source_table_insert_rows_per_second_measurements: List[float] = [],
    source_table_insert_rows_per_second_measurements_percentiles: List[float] = [],
    source_table_insert_bytes_per_second_measurements: List[float] = [],
    source_table_insert_bytes_per_second_measurements_readable: List[str] = [],
    source_table_insert_bytes_per_second_measurements_percentiles: List[float] = [],
    source_table_insert_bytes_per_second_measurements_percentiles_readable: List[float] = [],
    source_table_n_rows: int = -1,
    source_table_select_time_ms_measurements: List[float] = [],
    source_table_select_time_ms_measurements_percentiles: List[float] = [],
    res_uuid: str = "",
    db_postfix: str = settings.TEST_INDEXES_DB_POSTFIX,
) -> str:
    # ---------------------------  Init  ----------------------------
    try:
        if index_type:
            index_type = IndexType(index_type)
    except Exception as e:
        logger.error(f"Invalid enum input: {e}. Ending task.")
        return ""

    database_src = ch_manager_src.get_client()
    database_target = ch_manager_target.get_client()
    database_target_w_timeout = ch_manager_target_w_timeout.get_client()

    try:
        logger.info(
            f"Spawned job for benchmarking table: Test table name - {tested_db_name}.{tested_table_name}, Source table name - {source_db_name}.{source_table_name}"
        )

        try:
            database_target.command(tested_table_ddl)
        except Exception as e:
            logger.warning(
                f"Error occurred during table creation for indexes benchmark, trying to create db and drop this table. Error: {e}"
            )
            create_database(database_target, tested_db_name)
            drop_table(database_target, tested_db_name, tested_table_name, db_postfix)
            try:
                database_target.command(tested_table_ddl)
            except Exception as e:
                logger.error(
                    f"Error occurred during table creation for indexes benchmark, skipping table. Error: {e}, \n\ntest_table_ddl: {tested_table_ddl}"
                )
                return ""

        # ---------------------------  Insert time test  ----------------------------
        logger.info(f"measuring insert time for {tested_db_name}.{tested_table_name}")
        insert_stats = copy_data_by_stream_and_measure_stats(
            source_database_client=database_src,
            source_db_name=source_db_name,
            source_table_name=source_table_name,
            target_database_client=database_target,
            target_db_name=tested_db_name,
            target_table_name=tested_table_name,
            tested_cols=str_cols_for_index,
            n_rows=settings.N_INSERT_ROWS_FOR_INDEXES_BENCHMARK,
            n_measurements=settings.INSERT_TIME_TEST_N_MEASUREMENTS_FOR_INDEXES_BENCHMARK,
            src_clickhouse_manager=ch_manager_src,
        )

        if not insert_stats:
            logger.error(f"Could not get avg stats for table {source_db_name}.{source_table_name}")
            return ""

        # insert time
        tested_table_insert_time_ms_measurements = (
            np.array(insert_stats.elapsed_ns_measurements) / 1_000_000
        )
        tested_table_insert_time_ms_measurements_percentiles = np.percentile(
            tested_table_insert_time_ms_measurements, settings.MEASURED_PERCENTILES, method="linear"
        )
        tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs = []
        if source_table_insert_time_ms_measurements_percentiles and len(
            tested_table_insert_time_ms_measurements_percentiles
        ) == len(source_table_insert_time_ms_measurements_percentiles):
            tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs = (
                source_table_insert_time_ms_measurements_percentiles
                / tested_table_insert_time_ms_measurements_percentiles
            )

        # rows per sec
        tested_table_insert_rows_per_second_measurements = (
            insert_stats.read_rows_per_second_measurements
        )
        tested_table_insert_rows_per_second_measurements_percentiles = np.percentile(
            tested_table_insert_rows_per_second_measurements,
            settings.MEASURED_PERCENTILES,
            method="linear",
        )

        # bytes per sec
        tested_table_insert_bytes_per_second_measurements = (
            insert_stats.read_bytes_per_second_measurements
        )
        tested_table_insert_bytes_per_second_measurements_readable = [
            make_readable_bytes(elem) for elem in tested_table_insert_bytes_per_second_measurements
        ]
        tested_table_insert_bytes_per_second_measurements_percentiles = np.percentile(
            tested_table_insert_bytes_per_second_measurements,
            settings.MEASURED_PERCENTILES,
            method="linear",
        )
        tested_table_insert_bytes_per_second_measurements_percentiles_readable = [
            make_readable_bytes(elem)
            for elem in tested_table_insert_bytes_per_second_measurements_percentiles
        ]

        # ---------------------------  Count n of inserted rows  ----------------------------
        tested_table_n_rows = sum(insert_stats.written_rows_measurements)

        # ---------------------------  Get indexes sizes  ----------------------------
        tested_table_indexes_sizes = get_table_indexes_sizes_compressed_bytes(
            database_client=database_target, db_name=tested_db_name, table_name=tested_table_name
        )
        tested_table_indexes_sizes_serialized = {}
        for key in tested_table_indexes_sizes:
            tested_table_indexes_sizes_serialized[key] = tested_table_indexes_sizes[key].model_dump()

        # ---------------------------  Get cols sizes  ----------------------------
        tested_table_cols_sizes = get_table_columns_size_bytes(
            database_client=database_target, db_name=tested_db_name, table_name=tested_table_name
        )
        tested_table_cols_sizes_serialized = {}
        for key in tested_table_cols_sizes:
            tested_table_cols_sizes_serialized[key] = tested_table_cols_sizes[key].model_dump()

        # ---------------------------  Count index size % from col size  ----------------------------
        tested_table_index_size_percent_from_col_size: Dict[str, float] = {}
        for index_col_name in tested_table_indexes_sizes:
            index_size = tested_table_indexes_sizes.get(index_col_name)
            col_sizes = tested_table_cols_sizes.get(index_col_name)
            if (
                index_size
                and col_sizes
                and col_sizes.size_compressed_bytes
                and col_sizes.size_compressed_bytes != -1
            ):
                tested_table_index_size_percent_from_col_size[index_col_name] = round(
                    (index_size.size_compressed_bytes / col_sizes.size_compressed_bytes) * 100, 2
                )

        # ---------------------------  Select query time test  ----------------------------
        tested_table_select_test_query = generate_indexes_benchmark_select_query(
            tested_db_name, tested_table_name, str_cols_for_index, index_type
        )
        tested_table_stats = select_and_measure_stats(
            target_database_w_timeout=database_target_w_timeout,
            target_db_name=tested_db_name,
            target_table_name=tested_table_name,
            select_query=tested_table_select_test_query,
            n_measurements=settings.SELECT_TIME_TEST_N_MEASUREMENTS_FOR_INDEXES_BENCHMARK,
        )
        if not tested_table_stats:
            logger.error("empty tested_table_stats")
            return ""

        tested_table_select_time_ms_measurements = (
            np.array(tested_table_stats.elapsed_ns_measurements) / 1_000_000
        )
        tested_table_select_time_ms_measurements_percentiles = np.percentile(
            tested_table_select_time_ms_measurements,
            settings.MEASURED_PERCENTILES,
            method="linear",
        )
        tested_table_select_time_ms_measurements_percentiles_speed_up_coefs = []
        if source_table_select_time_ms_measurements_percentiles and len(
            tested_table_select_time_ms_measurements_percentiles
        ) == len(source_table_select_time_ms_measurements_percentiles):
            tested_table_select_time_ms_measurements_percentiles_speed_up_coefs = (
                source_table_select_time_ms_measurements_percentiles
                / tested_table_select_time_ms_measurements_percentiles
            )

        # ---------------------------  Save results  ----------------------------
        if not res_uuid:
            res_uuid = str(uuid.uuid4())

        new_res = IndexesBenchmarkResults(
            # ---------------------------  Metadata  ----------------------------
            id=res_uuid,
            benchmark_id=benchmark_id,
            source_db_name=source_db_name,
            source_table_name=source_table_name,
            tested_table_ddl=tested_table_ddl,
            source_table_ddl=source_table_ddl,
            is_source_table_copy=is_source_table_copy,
            index_params=index_params_str,
            total_n_rows_in_tested_table=tested_table_n_rows,
            total_n_rows_in_source_table=source_table_n_rows,
            measured_percentiles=settings.MEASURED_PERCENTILES,
            # ---------------------------  Insert test results  ----------------------------
            insert_test_n_rows=settings.N_INSERT_ROWS_FOR_INDEXES_BENCHMARK,
            tested_table_insert_time_ms_measurements=list(tested_table_insert_time_ms_measurements),
            source_table_insert_time_ms_measurements=source_table_insert_time_ms_measurements,
            tested_table_insert_time_ms_measurements_percentiles=list(
                tested_table_insert_time_ms_measurements_percentiles
            ),
            source_table_insert_time_ms_measurements_percentiles=source_table_insert_time_ms_measurements_percentiles,
            tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs=list(
                tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs
            ),
            tested_table_insert_rows_per_second_measurements=list(tested_table_insert_rows_per_second_measurements),
            source_table_insert_rows_per_second_measurements=source_table_insert_rows_per_second_measurements,
            tested_table_insert_rows_per_second_measurements_percentiles=list(
                tested_table_insert_rows_per_second_measurements_percentiles
            ),
            source_table_insert_rows_per_second_measurements_percentiles=source_table_insert_rows_per_second_measurements_percentiles,
            tested_table_insert_bytes_per_second_measurements=list(tested_table_insert_bytes_per_second_measurements),
            tested_table_insert_bytes_per_second_measurements_readable=list(tested_table_insert_bytes_per_second_measurements_readable),
            source_table_insert_bytes_per_second_measurements=source_table_insert_bytes_per_second_measurements,
            source_table_insert_bytes_per_second_measurements_readable=source_table_insert_bytes_per_second_measurements_readable,
            tested_table_insert_bytes_per_second_measurements_percentiles=list(tested_table_insert_bytes_per_second_measurements_percentiles),
            tested_table_insert_bytes_per_second_measurements_percentiles_readable=list(tested_table_insert_bytes_per_second_measurements_percentiles_readable),
            # ---------------------------  Select test results  ----------------------------
            tested_table_select_test_query=sqlparse.format(
                tested_table_select_test_query, reindent=True, keyword_case="upper"
            ),
            source_table_select_test_query=sqlparse.format(
                source_table_select_test_query, reindent=True, keyword_case="upper"
            ),
            source_table_select_time_ms_measurements=source_table_select_time_ms_measurements,
            tested_table_select_time_ms_measurements=list(tested_table_select_time_ms_measurements),
            source_table_select_time_ms_measurements_percentiles=source_table_select_time_ms_measurements_percentiles,
            tested_table_select_time_ms_measurements_percentiles=list(tested_table_select_time_ms_measurements_percentiles),
            tested_table_select_time_ms_measurements_percentiles_speed_up_coefs=list(tested_table_select_time_ms_measurements_percentiles_speed_up_coefs),
            # ---------------------------  Indexes results  ----------------------------
            tested_table_cols_sizes=json.dumps(tested_table_cols_sizes_serialized, ensure_ascii=False, indent=2, sort_keys=True),
            tested_table_indexes_sizes=json.dumps(tested_table_indexes_sizes_serialized, ensure_ascii=False, indent=2, sort_keys=True),
            tested_table_indexes_sizes_percent_from_col_size=json.dumps(
                tested_table_index_size_percent_from_col_size,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
        )

        benchmark_results_db_sqlalchemy_session = Session()
        try:
            benchmark_results_db_sqlalchemy_session.add(new_res)
            benchmark_results_db_sqlalchemy_session.commit()
            logger.info("Saved index benchmark result to database")
        except Exception as e:
            logger.error(f"Error occurred while committing new benchmark results: {e}")
            benchmark_results_db_sqlalchemy_session.rollback()
        benchmark_results_db_sqlalchemy_session.close()

        drop_table(database_target, tested_db_name, tested_table_name, db_postfix)

        if is_source_table_copy:
            return IndexBenchmarkResultModel(
                # ---------------------------  Metadata  ----------------------------
                benchmark_id=benchmark_id,
                source_db_name=source_db_name,
                source_table_name=source_table_name,
                tested_table_ddl=tested_table_ddl,
                source_table_ddl=source_table_ddl,
                is_source_table_copy=is_source_table_copy,
                index_params=index_params_str,
                total_n_rows_in_tested_table=tested_table_n_rows,
                total_n_rows_in_source_table=source_table_n_rows,
                # ---------------------------  Insert test results  ----------------------------
                insert_test_n_rows=settings.N_INSERT_ROWS_FOR_INDEXES_BENCHMARK,
                tested_table_insert_time_ms_measurements=list(tested_table_insert_time_ms_measurements),
                tested_table_insert_time_ms_measurements_percentiles=list(tested_table_insert_time_ms_measurements_percentiles),
                source_table_insert_time_ms_measurements=source_table_insert_time_ms_measurements,
                source_table_insert_time_ms_measurements_percentiles=source_table_insert_time_ms_measurements_percentiles,
                tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs=list(tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs),
                tested_table_insert_rows_per_second_measurements=tested_table_insert_rows_per_second_measurements,
                tested_table_insert_rows_per_second_measurements_percentiles=list(tested_table_insert_rows_per_second_measurements_percentiles),
                source_table_insert_rows_per_second_measurements_percentiles=source_table_insert_rows_per_second_measurements_percentiles,
                tested_table_insert_bytes_per_second_measurements=tested_table_insert_bytes_per_second_measurements,
                tested_table_insert_bytes_per_second_measurements_readable=tested_table_insert_bytes_per_second_measurements_readable,
                tested_table_insert_bytes_per_second_measurements_percentiles=list(tested_table_insert_bytes_per_second_measurements_percentiles),
                tested_table_insert_bytes_per_second_measurements_percentiles_readable=tested_table_insert_bytes_per_second_measurements_percentiles_readable,
                source_table_insert_bytes_per_second_measurements=source_table_insert_bytes_per_second_measurements,
                source_table_insert_bytes_per_second_measurements_readable=source_table_insert_bytes_per_second_measurements_readable,
                source_table_insert_bytes_per_second_measurements_percentiles=source_table_insert_bytes_per_second_measurements_percentiles,
                source_table_insert_bytes_per_second_measurements_percentiles_readable=source_table_insert_bytes_per_second_measurements_percentiles_readable,
                # ---------------------------  Select test results  ----------------------------
                tested_table_select_test_query=sqlparse.format(tested_table_select_test_query, reindent=True, keyword_case="upper"),
                source_table_select_test_query=sqlparse.format(source_table_select_test_query, reindent=True, keyword_case="upper"),
                tested_table_select_time_ms_measurements=list(tested_table_select_time_ms_measurements),
                tested_table_select_time_ms_measurements_percentiles=list(tested_table_select_time_ms_measurements_percentiles),
                source_table_select_time_ms_measurements=source_table_select_time_ms_measurements,
                source_table_select_time_ms_measurements_percentiles=source_table_select_time_ms_measurements_percentiles,
                tested_table_select_time_ms_measurements_percentiles_speed_up_coefs=list(tested_table_select_time_ms_measurements_percentiles_speed_up_coefs),
                # ---------------------------  Indexes results  ----------------------------
                tested_table_cols_sizes=json.dumps(tested_table_cols_sizes_serialized, ensure_ascii=False, indent=2, sort_keys=True),
                tested_table_indexes_sizes=json.dumps(tested_table_indexes_sizes_serialized, ensure_ascii=False, indent=2, sort_keys=True),
                tested_table_indexes_sizes_percent_from_col_size=json.dumps(tested_table_index_size_percent_from_col_size, ensure_ascii=False, indent=2, sort_keys=True),
            ).model_dump_json()

        return ""

    except Exception as e:
        logger.error(f"Error occurred during benchmark_one_table_string_indexing_variant_celery_job: {e}")
        return ""


# be careful with input params
@app.task
def copy_data_by_stream_and_measure_stats_celery_task(
    source_db_name: str,
    source_table_name: str,
    target_db_name: str,
    target_table_name: str,
    n_rows: int = 1_000_000,
    strictly_adhere_n_rows: bool = True,
    tested_cols: List[str] = [],
    n_measurements: int = 3,
) -> str:
    source_database_client = ch_manager_src.get_client()
    target_database_client = ch_manager_target.get_client()
    logger.info("Starting copy_data_by_stream_and_measure_stats_celery_task")
    try:
        curr_measurement_n = 0
        n_attempts = 0
        read_bytes_per_second_measurements: List[float] = []
        written_bytes_per_second_measurements: List[float] = []
        read_rows_per_second_measurements: List[float] = []
        written_rows_per_second_measurements: List[float] = []
        elapsed_ns_measurements: List[float] = []
        read_rows_measurements: List[int] = []
        written_rows_measurements: List[int] = []
        failed = False
        curr_offset = 0

        while curr_measurement_n < n_measurements:
            if n_attempts > 10:
                logger.warning(
                    f"Cant get query_summary for table {target_db_name}.{target_table_name}"
                )
                failed = True
                break

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
                src_clickhouse_manager=ch_manager_src,
                offset=curr_offset,
            )

            if query_summary:
                elapsed_sec = (
                    query_summary.elapsed_ns / 1_000_000_000
                    if query_summary.elapsed_ns != -1
                    else -1
                )

                read_rows_per_second = query_summary.read_rows / elapsed_sec if elapsed_sec > 0 else -1
                written_rows_per_second = query_summary.written_rows / elapsed_sec if elapsed_sec > 0 else -1
                read_bytes_per_second = query_summary.read_bytes / elapsed_sec if elapsed_sec > 0 else -1
                written_bytes_per_second = query_summary.written_bytes / elapsed_sec if elapsed_sec > 0 else -1

                read_bytes_per_second_measurements.append(read_bytes_per_second)
                written_bytes_per_second_measurements.append(written_bytes_per_second)
                read_rows_per_second_measurements.append(read_rows_per_second)
                written_rows_per_second_measurements.append(written_rows_per_second)
                elapsed_ns_measurements.append(query_summary.elapsed_ns)
                read_rows_measurements.append(query_summary.read_rows)
                written_rows_measurements.append(query_summary.written_rows)
                curr_measurement_n += 1
            else:
                logger.warning(
                    "Finishing copy_data_by_stream_and_measure_stats_celery_task with empty query summary"
                )
                return ""

            curr_offset += n_rows

        if not failed:
            logger.info(
                "Finishing copy_data_by_stream_and_measure_stats_celery_task successfully"
            )
            return QueryStats(
                read_bytes_per_second_measurements=read_bytes_per_second_measurements,
                written_bytes_per_second_measurements=written_bytes_per_second_measurements,
                read_rows_per_second_measurements=read_rows_per_second_measurements,
                written_rows_per_second_measurements=written_rows_per_second_measurements,
                elapsed_ns_measurements=elapsed_ns_measurements,
                read_rows_measurements=read_rows_measurements,
                written_rows_measurements=written_rows_measurements,
            ).model_dump_json()

        logger.warning(
            "Finishing copy_data_by_stream_and_measure_stats_celery_task with empty query summary"
        )
        return ""

    except Exception as e:
        logger.error(f"Error occurred during copy_data_by_stream_and_measure_stats_celery_task: {e}")
        return ""


# use carefully
@app.task
def copy_data_by_stream_celery_task(
    source_db_name: str,
    source_table_name: str,
    target_db_name: str,
    target_table_name: str,
    n_rows: int = 100_000,
    strictly_adhere_n_rows: bool = True,
    tested_cols: List[str] = [],
    offset: int = 0,
):
    source_database_client = ch_manager_src.get_client()
    target_database_client = ch_manager_target.get_client()
    logger.info("Starting copy_data_by_stream_celery_task")
    try:
        _ = copy_data_by_stream(
            source_database_client=source_database_client,
            source_db_name=source_db_name,
            source_table_name=source_table_name,
            target_database_client=target_database_client,
            target_db_name=target_db_name,
            target_table_name=target_table_name,
            n_rows=n_rows,
            strictly_adhere_n_rows=strictly_adhere_n_rows,
            tested_cols=tested_cols,
            src_clickhouse_manager=ch_manager_src,
            offset=offset,
        )
    except Exception as e:
        logger.error(f"Error occurred during copy_data_by_stream_celery_task: {e}")
