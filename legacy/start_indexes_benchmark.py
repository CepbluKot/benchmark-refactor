import logging
import time
import uuid
from typing import List, Tuple

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from celery_tasks import app, benchmark_one_table_string_indexing_variant_celery_job
from modules.clickhouse_ops import create_database, get_table_names
from modules.interfaces import IndexBenchmarkResultModel
from modules.iterate_over_all_variants_ops import iterate_over_all_indexes_benchmark_variants
from modules.sqlalchemy_stuff.engine import Base, Session, engine
from modules.sqlalchemy_stuff.operations import get_new_indexes_benchmark_id
from modules.table_schema_ops import get_splitted_table
from modules.task_monitor import TaskMonitorCelery
from settings import settings

logger = logging.getLogger(__name__)


def start_one_table_indexes_benchmark_in_celery(
    source_db_client: Client,
    source_db_name: str,
    source_table_name: str,
    tested_db_name: str,
    tested_table_name: str,
    benchmark_id: int,
    task_monitor: TaskMonitorCelery,
    indexed_cols: List[str] = [],
    db_postfix: str = settings.TEST_INDEXES_DB_POSTFIX,
) -> Tuple[int, List[str]]:
    res_uuids: List[str] = []

    if not indexed_cols:
        indexed_cols = settings.INDEXES_BENCHMARK_INDEXED_COLS_BY_TABLE.get(
            f"{source_db_name}.{source_table_name}", []
        )
    if not indexed_cols:
        logger.info(f"No indexed cols for table {source_db_name}.{source_table_name}, skipping...")
        return 0, []

    n_tests_per_table = 0
    initial_table_cols_raw_splitted = get_splitted_table(
        source_db_client, source_db_name, source_table_name
    )

    close_bracket_id = -1
    for row_id in range(len(initial_table_cols_raw_splitted)):
        if (
            initial_table_cols_raw_splitted[row_id]
            and initial_table_cols_raw_splitted[row_id][0] == ")"
        ):
            close_bracket_id = row_id

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
    index_benchmark_source_table_task_id = (
        benchmark_one_table_string_indexing_variant_celery_job.apply_async(
            kwargs={
                "source_db_name": source_db_name,
                "source_table_name": source_table_name,
                "source_table_ddl": original_ddl,
                "tested_db_name": tested_db_name,
                "tested_table_name": tested_initial_table_name_in_test_db,
                "tested_table_ddl": original_ddl,
                "is_source_table_copy": True,
                "benchmark_id": benchmark_id,
                "str_cols_for_index": indexed_cols,
                "index_params_str": "",
                "index_type": None,
                "res_uuid": res_uuid,
                "db_postfix": db_postfix,
            },
            task_id=celery_task_id,
        )
    )
    res_uuids.append(res_uuid)
    result = index_benchmark_source_table_task_id.get()
    source_table_copy_benchmark_res = IndexBenchmarkResultModel.model_validate_json(result)

    for new_table_params, index_params_str, index_type in iterate_over_all_indexes_benchmark_variants(
        initial_table_cols_raw_splitted, close_bracket_id, indexed_cols
    ):
        time.sleep(25)
        if not new_table_params:
            logger.warning(
                f"Warning! Table DDL wasnt generated for table {source_table_name}.{source_db_name}"
            )
            continue
        if not index_type:
            logger.warning(
                f"Warning! index_type wasnt generated for table {source_table_name}.{source_db_name}"
            )
            continue

        tested_table_name_w_unique_postfix = f"{tested_table_name}_{uuid.uuid4().hex}"
        new_table_params[0] = new_table_params[0].replace(
            f"{source_db_name}.{source_table_name}",
            f"{tested_db_name}.{tested_table_name_w_unique_postfix}",
        )
        table_ddl = new_table_params[0]
        for id in range(1, len(new_table_params) - 2):
            table_ddl += new_table_params[id] + ","
        table_ddl += new_table_params[-2]
        table_ddl += new_table_params[-1]

        res_uuid = str(uuid.uuid4())
        celery_task_id = task_monitor.new_task_id()
        task_monitor.register_task(celery_task_id)
        benchmark_one_table_string_indexing_variant_celery_job.apply_async(
            kwargs={
                "source_db_name": source_db_name,
                "source_table_name": source_table_name,
                "source_table_ddl": original_ddl,
                "tested_db_name": tested_db_name,
                "tested_table_name": tested_table_name_w_unique_postfix,
                "tested_table_ddl": table_ddl,
                "is_source_table_copy": False,
                "benchmark_id": benchmark_id,
                "str_cols_for_index": indexed_cols,
                "index_params_str": index_params_str,
                "index_type": index_type.value,
                "source_table_select_test_query": source_table_copy_benchmark_res.tested_table_select_test_query,
                "source_table_insert_time_ms_measurements": source_table_copy_benchmark_res.tested_table_insert_time_ms_measurements,
                "source_table_insert_time_ms_measurements_percentiles": source_table_copy_benchmark_res.tested_table_insert_time_ms_measurements_percentiles,
                "source_table_insert_rows_per_second_measurements": source_table_copy_benchmark_res.tested_table_insert_rows_per_second_measurements,
                "source_table_insert_rows_per_second_measurements_percentiles": source_table_copy_benchmark_res.tested_table_insert_rows_per_second_measurements_percentiles,
                "source_table_insert_bytes_per_second_measurements": source_table_copy_benchmark_res.tested_table_insert_bytes_per_second_measurements,
                "source_table_insert_bytes_per_second_measurements_readable": source_table_copy_benchmark_res.tested_table_insert_bytes_per_second_measurements_readable,
                "source_table_insert_bytes_per_second_measurements_percentiles": source_table_copy_benchmark_res.tested_table_insert_bytes_per_second_measurements_percentiles,
                "source_table_insert_bytes_per_second_measurements_percentiles_readable": source_table_copy_benchmark_res.tested_table_insert_bytes_per_second_measurements_percentiles_readable,
                "source_table_n_rows": source_table_copy_benchmark_res.total_n_rows_in_tested_table,
                "source_table_select_time_ms_measurements": source_table_copy_benchmark_res.tested_table_select_time_ms_measurements,
                "source_table_select_time_ms_measurements_percentiles": source_table_copy_benchmark_res.tested_table_select_time_ms_measurements_percentiles,
                "res_uuid": res_uuid,
                "db_postfix": db_postfix,
            },
            task_id=celery_task_id,
            ignore_result=True,
        )
        res_uuids.append(res_uuid)
        n_tests_per_table += 1

    return n_tests_per_table, res_uuids


def start_indexes_benchmark_in_celery(
    database_src: Client,
    database_target: Client,
    database_names_to_check: List[str] = settings.DATABASE_NAMES_TO_CHECK,
    tables_names_to_check: List[str] = settings.TABLES_TO_CHECK,
    db_postfix: str = settings.TEST_INDEXES_DB_POSTFIX,
) -> Tuple[int, int]:
    task_monitor = TaskMonitorCelery(app, benchmark_name="indexes benchmark")
    task_monitor.start_event_listener()

    database_target.command(
        f"""CREATE DATABASE IF NOT EXISTS {settings.BENCHMARK_RESULTS_DATABASE}"""
    )
    Base.metadata.create_all(engine)

    get_benchmark_id_session = Session()
    benchmark_id = get_new_indexes_benchmark_id(get_benchmark_id_session)
    get_benchmark_id_session.close()

    logger.info("=== Indexes benchmark ===")
    logger.info("=== Build metadata ===")
    logger.info("Build date: %s", settings.BUILD_DATETIME)
    logger.info("Git commit: %s", settings.GIT_COMMIT)
    logger.info("Git branch: %s", settings.GIT_BRANCH)
    logger.info("======================")
    logger.info(f"database_names_to_check: {database_names_to_check}")
    logger.info(f"tables_names_to_check: {tables_names_to_check}")
    logger.info(f"TOP_N_RESULTS: {settings.TOP_N_RESULTS}")
    logger.info(f"starting indexes benchmark #{benchmark_id}")

    total_n_tests = 0
    for tested_db_original_name in database_names_to_check:
        test_db_name = tested_db_original_name + db_postfix
        create_database(database_target, test_db_name)

        if not tables_names_to_check:
            tables_names_to_check = get_table_names(
                database_src, tested_db_original_name, settings.CHECKED_TABLES_ENGINE_TYPES
            )

        tested_table_names_set = set(tables_names_to_check).difference(
            settings.INDEXES_BENCHMARK_TABLES_TO_EXCLUDE
        )

        for tested_table_name in tested_table_names_set:
            n_tests_per_table, _ = start_one_table_indexes_benchmark_in_celery(
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
    logger.info(f"sent indexes benchmark #{benchmark_id} to celery! Total n tests: {total_n_tests}")
    task_monitor.wait_for_completion()
    task_monitor.pbar.close()
    logger.info(f"indexes benchmark #{benchmark_id} finished successfully")
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
    total_n_tests, benchmark_id = start_indexes_benchmark_in_celery(
        database_src,
        database_target,
    )
    database_src.close()
    database_target.close()