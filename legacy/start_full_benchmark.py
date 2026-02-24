import logging
import time
import uuid
from typing import List

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from celery_tasks import app
from modules.clickhouse_ops import create_database, drop_table, get_table_ddl
from modules.clickhouse_ops_w_celery import copy_data_by_stream_and_measure_stats_in_celery
from modules.interfaces import TableData
from modules.sqlalchemy_stuff.engine import Base, Session, engine
from modules.sqlalchemy_stuff.operations import (
    get_new_data_compression_benchmark_id,
    get_new_full_benchmark_id,
    get_new_indexes_benchmark_id,
)
from modules.sqlalchemy_stuff.tables import FullBenchmarkResults
from modules.task_monitor import TaskMonitorCelery
from settings import settings
from start_data_compression_benchmark import start_data_compression_benchmark_in_celery
from start_indexes_benchmark import start_one_table_indexes_benchmark_in_celery

logger = logging.getLogger(__name__)


def save_top5_table_to_full_benchmark_db(
    db_name: str, table_name: str, benchmark_id: str, source_table_ddl: str, database_client: Client
):
    table_ddl = source_table_ddl.replace(
        f"CREATE TABLE {db_name}.{table_name}",
        f"CREATE TABLE {settings.FULL_BENCHMARK_TOP_N_DATA_COMPRESSION_RESULTS_TABLES_DB_NAME}.{table_name}_source_table_for_benchmark_{benchmark_id}",
    )
    database_client.command(table_ddl)


def start_full_benchmark_in_celery(
    database_src: Client,
    database_target: Client,
    database_names_to_check: List[str] = settings.DATABASE_NAMES_TO_CHECK,
    tables_names_to_check: List[str] = settings.TABLES_TO_CHECK,
) -> int:
    created_tables_data: List[TableData] = []
    task_monitor = TaskMonitorCelery(app, benchmark_name="full benchmark")
    task_monitor.start_event_listener()

    create_database(
        database_target, settings.FULL_BENCHMARK_TOP_N_DATA_COMPRESSION_RESULTS_TABLES_DB_NAME
    )

    benchmark_db_sqlalchemy_session = Session()
    full_benchmark_id = get_new_full_benchmark_id(benchmark_db_sqlalchemy_session)
    indexes_benchmark_id = get_new_indexes_benchmark_id(benchmark_db_sqlalchemy_session)
    last_data_compression_benchmark_id = get_new_data_compression_benchmark_id(
        benchmark_db_sqlalchemy_session
    )
    last_data_compression_benchmark_id = (
        last_data_compression_benchmark_id - 1
        if last_data_compression_benchmark_id
        else last_data_compression_benchmark_id
    )

    logger.info("=== Full benchmark ===")
    logger.info("=== Build metadata ===")
    logger.info("Build date: %s", settings.BUILD_DATETIME)
    logger.info("Git commit: %s", settings.GIT_COMMIT)
    logger.info("Git branch: %s", settings.GIT_BRANCH)
    logger.info("======================")
    logger.info(f"database_names_to_check: {database_names_to_check}")
    logger.info(f"tables_names_to_check: {tables_names_to_check}")
    logger.info(f"TOP_N_RESULTS: {settings.TOP_N_RESULTS}")
    logger.info("======================")
    logger.info(f"N_INSERT_ROWS_FOR_DATA_COMPRESSION_BENCHMARK: {settings.N_INSERT_ROWS_FOR_DATA_COMPRESSION_BENCHMARK}")
    logger.info(f"INSERT_TIME_TEST_N_MEASUREMENTS_FOR_DATA_COMPRESSION_BENCHMARK: {settings.INSERT_TIME_TEST_N_MEASUREMENTS_FOR_DATA_COMPRESSION_BENCHMARK}")
    logger.info(f"SELECT_TIME_TEST_N_MEASUREMENTS_FOR_INDEXES_BENCHMARK: {settings.SELECT_TIME_TEST_N_MEASUREMENTS_FOR_INDEXES_BENCHMARK}")
    logger.info(f"N_INSERT_ROWS_FOR_INDEXES_BENCHMARK: {settings.N_INSERT_ROWS_FOR_INDEXES_BENCHMARK}")
    logger.info(f"INSERT_TIME_TEST_N_MEASUREMENTS_FOR_INDEXES_BENCHMARK: {settings.INSERT_TIME_TEST_N_MEASUREMENTS_FOR_INDEXES_BENCHMARK}")
    logger.info(f"N_INSERT_ROWS_FOR_FULL_BENCHMARK: {settings.N_INSERT_ROWS_FOR_FULL_BENCHMARK}")
    logger.info(f"INSERT_TIME_TEST_N_MEASUREMENTS_FOR_FULL_BENCHMARK: {settings.INSERT_TIME_TEST_N_MEASUREMENTS_FOR_FULL_BENCHMARK}")
    logger.info("======================")
    logger.info(f"starting full benchmark #{full_benchmark_id}")

    if not last_data_compression_benchmark_id:
        logger.info("No data compression test has been run previously")

    if (
        settings.FULL_BENCHMARK_USED_DATA_COMPRESSION_BENCHMARK_ID != -1
        and settings.FULL_BENCHMARK_USED_DATA_COMPRESSION_BENCHMARK_ID
        <= last_data_compression_benchmark_id
    ):
        logger.info(
            f"using predefined data compression bench id: {settings.FULL_BENCHMARK_USED_DATA_COMPRESSION_BENCHMARK_ID}"
        )
        last_data_compression_benchmark_id = settings.FULL_BENCHMARK_USED_DATA_COMPRESSION_BENCHMARK_ID
    elif settings.FULL_BENCHMARK_PERFORM_PRELIMINARY_DATA_COMPRESSION_BENCHMARK:
        logger.info("starting preliminary data compression test")
        _, last_data_compression_benchmark_id = start_data_compression_benchmark_in_celery(
            database_src,
            database_target,
            database_names_to_check,
            tables_names_to_check,
        )

    logger.info(f"using data compression benchmark #{last_data_compression_benchmark_id}")

    data_compression_benchmark_db_and_tables = database_target.query_df(
        f"""select distinct source_db_name, source_table_name from {settings.BENCHMARK_RESULTS_DATABASE}.{settings.DATA_COMPRESSION_BENCHMARK_RESULTS_TABLE} where benchmark_id = {last_data_compression_benchmark_id}"""
    )
    if data_compression_benchmark_db_and_tables.empty:
        logger.warning(
            f"no data_compression_benchmark_db_and_tables for selected data compression bench id = {last_data_compression_benchmark_id}"
        )

    for res in data_compression_benchmark_db_and_tables.values:
        if len(res) != 2:
            continue
        source_db_name = res[0]
        source_table_name = res[1]

        if database_names_to_check and source_db_name not in database_names_to_check:
            continue
        if tables_names_to_check and source_table_name not in tables_names_to_check:
            continue
        if source_table_name in settings.FULL_BENCHMARK_TABLES_TO_EXCLUDE:
            continue

        indexed_cols = settings.INDEXES_BENCHMARK_INDEXED_COLS_BY_TABLE.get(
            f"{source_db_name}.{source_table_name}", []
        )
        if not indexed_cols:
            logger.info(f"no indexed cols for {source_db_name}.{source_table_name}, skipping...")
            continue

        get_top_n_best_options_data_compression_query = f"""
            select id, tested_table_ddl
            from {settings.BENCHMARK_RESULTS_DATABASE}.{settings.DATA_COMPRESSION_BENCHMARK_RESULTS_TABLE}
            where source_db_name = '{source_db_name}'
              and source_table_name = '{source_table_name}'
              and benchmark_id = {last_data_compression_benchmark_id}
            order by tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs[-1] desc
            limit {settings.TOP_N_RESULTS}
        """
        top_n = database_target.query_df(get_top_n_best_options_data_compression_query)

        for top_n_res in top_n.values:
            if len(top_n_res) != 2:
                continue
            curr_data_compression_benchmark_uuid: str = top_n_res[0]
            table_ddl: str = top_n_res[1]
            first_bracket_start_pos = table_ddl.find("(")

            test_db_name = settings.FULL_BENCHMARK_TOP_N_DATA_COMPRESSION_RESULTS_TABLES_DB_NAME
            tested_table_name = (
                f"{source_table_name}_for_full_benchmark_{full_benchmark_id}_{uuid.uuid4().hex}"
            )
            replaced_ddl = (
                "CREATE TABLE "
                + f"{test_db_name}.{tested_table_name} "
                + table_ddl[first_bracket_start_pos:]
            )

            try:
                database_target.command(replaced_ddl)
                created_tables_data.append(
                    TableData(db_name=test_db_name, table_name=tested_table_name)
                )
            except Exception as e:
                logger.error(f"error occupied during table creation for full benchmark: {e}")

            insert_res = copy_data_by_stream_and_measure_stats_in_celery(
                source_db_name=source_db_name,
                source_table_name=source_table_name,
                target_db_name=test_db_name,
                target_table_name=tested_table_name,
                n_rows=settings.N_INSERT_ROWS_FOR_FULL_BENCHMARK,
                n_measurements=settings.INSERT_TIME_TEST_N_MEASUREMENTS_FOR_FULL_BENCHMARK,
            )
            if not insert_res:
                logger.error(
                    f"Could not insert data to {test_db_name}.{tested_table_name}, benchmarking next top n (n={settings.TOP_N_RESULTS}) table..."
                )
                error_table_ddl = get_table_ddl(database_target, test_db_name, tested_table_name)
                logger.error(f"DDL of table with error {test_db_name}.{tested_table_name}: {error_table_ddl}")
                continue

            _, indexes_benchmarks_uuids = start_one_table_indexes_benchmark_in_celery(
                database_src,
                test_db_name,
                tested_table_name,
                test_db_name,
                tested_table_name,
                indexes_benchmark_id,
                task_monitor,
                indexed_cols,
                settings.FULL_BENCHMARK_TOP_N_DATA_COMPRESSION_RESULTS_TABLES_DB_NAME,
            )

            for indexes_benchmark_uuid in indexes_benchmarks_uuids:
                new_res = FullBenchmarkResults(
                    id=str(uuid.uuid4()),
                    benchmark_id=full_benchmark_id,
                    source_db_name=source_db_name,
                    source_table_name=source_table_name,
                    data_compression_benchmark_uuid=curr_data_compression_benchmark_uuid,
                    indexes_benchmark_uuid=indexes_benchmark_uuid,
                )
                try:
                    benchmark_db_sqlalchemy_session.add(new_res)
                    benchmark_db_sqlalchemy_session.commit()
                except Exception as e:
                    logger.error(f"Error occupied while committing new full benchmark results: {e}")
                    benchmark_db_sqlalchemy_session.rollback()

    task_monitor.make_all_sent()
    task_monitor.wait_for_completion()
    task_monitor.pbar.close()

    logger.info("dropping temp tables")
    for table in created_tables_data:
        drop_table(
            database_client=database_target,
            target_db_name=table.db_name,
            target_table_name=table.table_name,
            test_db_postfix=settings.FULL_BENCHMARK_TOP_N_DATA_COMPRESSION_RESULTS_TABLES_DB_NAME,
        )

    if not task_monitor.total_n_tests:
        logger.warning("looks like selected tested tables were not tested in data comp benchmark")

    logger.info("full benchmark finished successfully")
    benchmark_db_sqlalchemy_session.close()
    return full_benchmark_id


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
    try:
        database_target.command(
            f"""CREATE DATABASE IF NOT EXISTS {settings.BENCHMARK_RESULTS_DATABASE};"""
        )
        Base.metadata.create_all(engine)
        benchmark_id = start_full_benchmark_in_celery(
            database_src,
            database_target,
        )
    except Exception as e:
        logger.error(
            f"Error at full benchmark (rmq at {settings.RABBITMQ_HOSTNAME}:{settings.RABBITMQ_PORT}): {e}"
        )
        database_src.close()
        database_target.close()
        raise Exception
    finally:
        database_src.close()
        database_target.close()

    t = 10
    while 1:
        logger.info("full benchmark finished successfully. This infinite loop is a temporary hack.")
        time.sleep(t)
        t *= t