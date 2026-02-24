import logging
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from modules.sqlalchemy_stuff.tables import (
    DataCompressionBenchmarkResults,
    FullBenchmarkResults,
    IndexesBenchmarkResults,
)
logger = logging.getLogger(__name__)
def get_new_data_compression_benchmark_id(session: Session) -> int:
    max_id = session.execute(
        select(func.coalesce(func.max(DataCompressionBenchmarkResults.benchmark_id), -1))
    ).scalar_one()
    if max_id == -1:
        return 0
    else:
        return max_id + 1
def get_new_indexes_benchmark_id(session: Session) -> int:
    max_id = session.execute(
        select(func.coalesce(func.max(IndexesBenchmarkResults.benchmark_id), -1))
    ).scalar_one()
    if max_id == -1:
        return 0
    else:
        return max_id + 1
def get_new_full_benchmark_id(session: Session) -> int:
    max_id = session.execute(
        select(func.coalesce(func.max(FullBenchmarkResults.benchmark_id), -1))
    ).scalar_one()
    if max_id == -1:
        return 0
    else:
        return max_id + 1
