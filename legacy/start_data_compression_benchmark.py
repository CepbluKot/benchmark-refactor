import logging
import time
import uuid
from typing import List, Tuple

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from celery_tasks import app, benchmark_one_table_data_compression_variant_celery_job
from modules.clickhouse_ops import create_database, get_table_names
from modules.interfaces import DataCompressionBenchmarkResultModel
from modules.iterate_over_all_variants_ops import iterate_over_all_data_compression_variants
from modules.sql_query_generators import generate_table_ddl_w_new_cols
from modules.sqlalchemy_stuff.engine import Base, Session, engine
from modules.sqlalchemy_stuff.operations import get_new_data_compression_benchmark_id
from modules.table_schema_ops import get_splitted_table, parse_table_cols
from modules.task_monitor import TaskMonitorCelery
from settings import settings

logger = logging.getLogger(__name__)


def start_one_table_data_compression_benchmark_in_celery(
    source_db_client: Client,
    source_db_name: str,
    source_table_name: str,
    tested_db_name: str,
    tested_table_name: str,
    benchmark_id: int,
    task_monitor: TaskMonitorCelery,
    db_postfix: str = settings.TEST_DATA_COMPRESSION_DB_POSTFIX,
) -> Tuple[int, List[str]]:
    res_uuids: List[str] = []
    n_tests_per_table = 0

    initial_table_cols_raw_splitted = get_splitted_table(
        source_db_client, source_db_name, source_table_name
    )
    parsed_cols = parse_table_cols(initial_table_cols_raw_splitted)

    tested_initial_table_name_in_test_db = f"{tested_table_name}_{uuid.uuid4().hex}"

    original_ddl = initial_table_cols_raw_splitted[0]
    for id in range(1, len(initial_table_cols_raw_splitted) - 2):
        original_ddl += initial_table_cols_raw_splitted[id] + ","
    original_ddl += initial_table_cols_raw_splitted[-2]
    original_ddl += initial_table_cols_raw_splitted[-1]
    original_ddl = original_ddl.replace(
        f"{source_db_name}.{source_table_name}",
        f"{tested_db_name}.{tested_initial_table_name_in_test_db}",
    )

    res_uuid = str(uuid.uuid4())
    celery_task_id = task_monitor.new_task_id()
    data_compression_benchmark_source_table_task_id = (
        benchmark_one_table_data_compression_variant_celery_job.apply_async(
            kwargs={
                "source_db_name": source_db_name,
                "source_table_name": source_table_name,
                "tested_db_name": tested_db_name,
                "tested_table_name": tested_initial_table_name_in_test_db,
                "tested_table_ddl": original_ddl,
                "is_source_table_copy": True,
                "benchmark_id": benchmark_id,
                "res_uuid": res_uuid,
                "db_postfix": db_postfix,
            },
            task_id=celery_task_id,
        )
    )
    res_uuids.append(res_uuid)
    result = data_compression_benchmark_source_table_task_id.get()
    source_table_copy_benchmark_res = DataCompressionBenchmarkResultModel.model_validate_json(result)
    logger.info(f"table sent to celery: {tested_db_name}.{tested_initial_table_name_in_test_db}")

    for cols_w_new_params in iterate_over_all_data_compression_variants(
        parsed_cols, settings.DATA_TYPES_POSSIBLE_ALTERNATIVES
    ):
        time.sleep(25)
        tested_table_name_w_unique_postfix = f"{tested_table_name}_{uuid.uuid4().hex}"
        table_w_new_cols_ddl = generate_table_ddl_w_new_cols(
            source_db_name,
            source_table_name,
            tested_db_name,
            tested_table_name_w_unique_postfix,
            initial_table_cols_raw_splitted,
            cols_w_new_params,
        )
        if not table_w_new_cols_ddl:
            logger.warning(
                f"Warning! Table DDL wasnt generated for table {source_table_name}.{source_db_name}"
            )
            continue

        res_uuid = str(uuid.uuid4())
        celery_task_id = task_monitor.new_task_id()
        task_monitor.register_task(celery_task_id)
        benchmark_one_table_data_compression_variant_celery_job.apply_async(
            kwargs={
                "source_db_name": source_db_name,
                "source_table_name": source_table_name,
                "tested_db_name": tested_db_name,
                "tested_table_name": tested_table_name_w_unique_postfix,
                "tested_table_ddl": table_w_new_cols_ddl,
                "is_source_table_copy": False,
                "benchmark_id": benchmark_id,
                "source_table_ddl": source_table_copy_benchmark_res.tested_table_ddl,
                "source_table_n_rows": source_table_copy_benchmark_res.total_n_rows_in_tested_table,
                "source_table_insert_time_ms_measurements": source_table_copy_benchmark_res.tested_table_insert_time_ms_measurements,
                "source_table_insert_time_ms_measurements_percentiles": source_table_copy_benchmark_res.tested_table_insert_time_ms_measurements_percentiles,
                "source_table_insert_rows_per_second_measurements": source_table_copy_benchmark_res.tested_table_insert_rows_per_second_measurements,
                "source_table_insert_rows_per_second_measurements_percentiles": source_table_copy_benchmark_res.tested_table_insert_rows_per_second_measurements_percentiles,
                "source_table_insert_bytes_per_second_measurements": source_table_copy_benchmark_res.tested_table_insert_bytes_per_second_measurements,
                "source_table_insert_bytes_per_second_measurements_readable": source_table_copy_benchmark_res.tested_table_insert_bytes_per_second_measurements_readable,
                "source_table_insert_bytes_per_second_measurements_percentiles": source_table_copy_benchmark_res.tested_table_insert_bytes_per_second_measurements_percentiles,
                "source_table_select_test_query": source_table_copy_benchmark_res.tested_table_select_test_query,
                "source_table_select_time_ms_measurements": source_table_copy_benchmark_res.tested_table_select_time_ms_measurements,
                "source_table_select_time_ms_measurements_percentiles": source_table_copy_benchmark_res.tested_table_select_time_ms_measurements_percentiles,
                "source_table_select_rows_per_second_measurements": source_table_copy_benchmark_res.tested_table_select_rows_per_second_measurements,
                "source_table_select_rows_per_second_measurements_percentiles": source_table_copy_benchmark_res.tested_table_select_rows_per_second_measurements_percentiles,
                "source_table_select_bytes_per_second_measurements": source_table_copy_benchmark_res.tested_table_select_bytes_per_second_measurements,
                "source_table_select_bytes_per_second_measurements_readable": source_table_copy_benchmark_res.tested_table_select_bytes_per_second_measurements_readable,
                "source_table_select_bytes_per_second_measurements_percentiles": source_table_copy_benchmark_res.tested_table_select_bytes_per_second_measurements_percentiles,
                "source_table_consumed_compressed_size_bytes_by_each_column": source_table_copy_benchmark_res.tested_table_consumed_compressed_size_bytes_by_each_column,
                "source_table_consumed_compressed_size_bytes_overall": source_table_copy_benchmark_res.tested_table_consumed_compressed_size_bytes_overall,
                "source_table_n_rows_in_size_test": source_table_copy_benchmark_res.tested_table_n_rows_in_size_test,
                "res_uuid": res_uuid,
                "db_postfix": db_postfix,
            },
            task_id=celery_task_id,
            ignore_result=True,
        )
        res_uuids.append(res_uuid)
        n_tests_per_table += 1
        logger.info(f"table sent to celery: {tested_db_name}.{tested_table_name_w_unique_postfix}")

    return n_tests_per_table, res_uuids


def start_data_compression_benchmark_in_celery(
    database_src: Client,
    database_target: Client,
    database_names_to_check: List[str] = settings.DATABASE_NAMES_TO_CHECK,
    tables_names_to_check: List[str] = settings.TABLES_TO_CHECK,
    db_postfix: str = settings.TEST_DATA_COMPRESSION_DB_POSTFIX,
) -> Tuple[int, int]:
    task_monitor = TaskMonitorCelery(app, benchmark_name="data compression benchmark")
    task_monitor.start_event_listener()

    database_target.command(
        f"""CREATE DATABASE IF NOT EXISTS {settings.BENCHMARK_RESULTS_DATABASE};"""
    )
    Base.metadata.create_all(engine)

    get_benchmark_id_session = Session()
    benchmark_id = get_new_data_compression_benchmark_id(get_benchmark_id_session)
    get_benchmark_id_session.close()

    logger.info("=== Data compression benchmark ===")
    logger.info("=== Build metadata ===")
    logger.info("Build date: %s", settings.BUILD_DATETIME)
    logger.info("Git commit: %s", settings.GIT_COMMIT)
    logger.info("Git branch: %s", settings.GIT_BRANCH)
    logger.info("======================")
    logger.info(f"database_names_to_check: {database_names_to_check}")
    logger.info(f"tables_names_to_check: {tables_names_to_check}")
    logger.info(f"TOP_N_RESULTS: {settings.TOP_N_RESULTS}")
    logger.info(f"starting data compression benchmark #{benchmark_id}")

    total_n_tests = 0
    for tested_db_original_name in database_names_to_check:
        test_db_name = tested_db_original_name + settings.TEST_DATA_COMPRESSION_DB_POSTFIX
        create_database(database_target, test_db_name)

        if not tables_names_to_check:
            tables_names_to_check = get_table_names(
                database_src, tested_db_original_name, settings.CHECKED_TABLES_ENGINE_TYPES
            )

        tested_table_names_set = set(tables_names_to_check).difference(
            settings.DATA_COMPRESSION_BENCHMARK_TABLES_TO_EXCLUDE
        )
        if not tested_table_names_set:
            logger.warning(
                f"no tested tables to test, initial input: {tables_names_to_check}. Skipping..."
            )

        for tested_table_name in tested_table_names_set:
            n_tests_per_table, _ = start_one_table_data_compression_benchmark_in_celery(
                database_src,
                tested_db_original_name,
                tested_table_name,
                test_db_name,
                tested_table_name,
                benchmark_id,
                task_monitor,
                db_postfix=db_postfix,
            )
            total_n_tests += n_tests_per_table

    task_monitor.make_all_sent()
    logger.info(
        f"sent data compression benchmark #{benchmark_id} to celery! Total n tests: {total_n_tests}"
    )
    task_monitor.wait_for_completion()
    task_monitor.pbar.close()
    return total_n_tests, benchmark_id


if __name__ == "__main__":
    database_src = clickhouse_connect.get_client(
        host=settings.SRC_DATABASE_HOST,
        port=settings.SRC_DATABASE_PORT,
        username=settings.SRC_DATABASE_USERNAME.get_secret_value(),
        password=settings.SRC_DATABASE_PASSWORD.get_secret_value(),
    )
    database_target = clickhouse_connect.get_client(
        host=settings.TGT_DATABASE_HOST,
        port=settings.TGT_DATABASE_PORT,
        username=settings.TGT_DATABASE_USERNAME.get_secret_value(),
        password=settings.TGT_DATABASE_PASSWORD.get_secret_value(),
    )
    total_n_tests, benchmark_id = start_data_compression_benchmark_in_celery(
        database_src,
        database_target,
    )
    database_src.close()
    database_target.close()