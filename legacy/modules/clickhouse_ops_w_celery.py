import logging
from typing import List
from celery_tasks import copy_data_by_stream_and_measure_stats_celery_task
from modules.clickhouse_ops import check_input_params_decorator
from modules.interfaces import QueryStats
logger = logging.getLogger(__name__)
@check_input_params_decorator
def copy_data_by_stream_and_measure_stats_in_celery(
    source_db_name: str,
    source_table_name: str,
    target_db_name: str,
    target_table_name: str,
    n_rows: int = 1_000_000,
    strictly_adhere_n_rows: bool = True,
    tested_cols: List[str] = [],
    n_measurements: int = 3,
) -> QueryStats | None:
    try:
        res = copy_data_by_stream_and_measure_stats_celery_task.apply_async(
            kwargs={
                "source_db_name": source_db_name,
                "source_table_name": source_table_name,
                "target_db_name": target_db_name,
                "target_table_name": target_table_name,
                "n_rows": n_rows,
                "strictly_adhere_n_rows": strictly_adhere_n_rows,
                "tested_cols": tested_cols,
                "n_measurements": n_measurements,
            },
        )
        final_result = res.get()
        if final_result:
            return QueryStats.model_validate_json(final_result)
        logger.warning("res is empty for copy_data_by_stream_and_measure_stats_in_celery")
    except Exception as e:
        logger.error(f"Error occupied during copy_data_by_stream_and_measure_stats_in_celery: {e}")