"""
CLI-утилита пересчёта кастомного score для сохранённых benchmark-результатов.

Пересчёт не меняет основной `score`, а пишет результат в отдельную колонку `score_custom`.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List, Optional, Sequence

from src.benchmark_runtime.implementations.clickhouse_celery import (
    ClickHouseBenchmarkResultStore,
)
from src.loader import parse_config_parts
from src.models import BenchmarkRootConfig, ConnectionConfig
from settings import get_settings


def _resolve_result_connection(
    config: BenchmarkRootConfig,
    preferred_connection_id: Optional[str],
) -> ConnectionConfig:
    """Выбирает connection для result-store."""
    if not config.connections:
        raise ValueError("В конфиге отсутствуют connections")

    if preferred_connection_id is None:
        return config.connections[0]
    normalized = preferred_connection_id.strip()
    if not normalized:
        return config.connections[0]

    for connection in config.connections:
        if connection.id == normalized:
            return connection

    available_ids = ", ".join(sorted(conn.id for conn in config.connections))
    raise ValueError(
        "BENCH_RESULT_CONNECTION_ID указывает на несуществующий connection_id: "
        f"{normalized!r}. Доступные connection_id: {available_ids}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Пересчитывает custom-score (колонка score_custom) "
            "для benchmark-результатов по новой expression-формуле."
        )
    )
    parser.add_argument(
        "--benchmark-id",
        required=True,
        help="benchmark_id, для которого делаем пересчёт.",
    )
    parser.add_argument(
        "--expression",
        required=True,
        help="Новая expression-формула custom-score.",
    )
    parser.add_argument(
        "--benchmark-run-id",
        type=int,
        default=None,
        help="Опционально ограничить пересчёт конкретным benchmark_run_id.",
    )
    parser.add_argument(
        "--source-database",
        default=None,
        help="Опционально ограничить source_db_name.",
    )
    parser.add_argument(
        "--source-table",
        default=None,
        help="Опционально ограничить source_table_name.",
    )
    parser.add_argument(
        "--target-tables",
        choices=["phased", "legacy", "both"],
        default="phased",
        help="В каких result-таблицах пересчитывать score_custom.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
        root_config = parse_config_parts(
            celery_raw=settings.decode_celery_config(),
            connections_raw=settings.decode_connections_config(),
            rule_banks_raw=settings.decode_rule_banks_config(),
            benchmarks_raw=settings.decode_benchmarks_config(),
        )
        result_connection = _resolve_result_connection(
            config=root_config,
            preferred_connection_id=settings.result_connection_id,
        )

        result_store = ClickHouseBenchmarkResultStore(
            connection=result_connection,
            database=settings.result_database,
            table=settings.result_table,
            legacy_table=settings.resolved_legacy_result_table,
            phased_table=settings.resolved_phased_result_table,
            phased_runs_table=settings.resolved_phased_runs_table,
            create_legacy_table=True,
        )
        try:
            summary = result_store.recalculate_custom_score_for_benchmark(
                benchmark_id=args.benchmark_id,
                expression=args.expression,
                benchmark_run_id=args.benchmark_run_id,
                source_database=args.source_database,
                source_table=args.source_table,
                target_tables=args.target_tables,
            )
        finally:
            result_store.close()

        total_rows = sum(int(item.get("total_rows", 0)) for item in summary.values())
        updated_rows = sum(int(item.get("updated_rows", 0)) for item in summary.values())
        failed_rows = sum(int(item.get("failed_rows", 0)) for item in summary.values())
        print(
            "OK: custom-score пересчитан "
            f"(benchmark_id={args.benchmark_id}, "
            f"target_tables={args.target_tables}, "
            f"total_rows={total_rows}, updated_rows={updated_rows}, failed_rows={failed_rows})"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
