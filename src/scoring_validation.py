"""Предзапусковая валидация scoring expression в benchmark-конфигах."""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from src.benchmark_runtime.implementations.clickhouse_celery.scoring import (
    validate_score_expression,
)
from src.models import BenchmarkConfig, ScoringConfig, TableRuleConfig


def _issues_for_scoring(
    *,
    scoring: ScoringConfig,
    scope: str,
) -> List[str]:
    """Возвращает список проблем для одного scoring-блока."""
    if scoring.mode != "expression":
        return []

    expression = scoring.expression or ""
    raw_issues = validate_score_expression(expression)
    return [f"{scope}: {issue}" for issue in raw_issues]


def _scope_for_table_rule(benchmark: BenchmarkConfig, table_rule: TableRuleConfig) -> str:
    """Формирует читаемое имя scope для table-level scoring override."""
    return (
        f"benchmark={benchmark.id}, "
        f"table_rule={table_rule.database}.{table_rule.table}"
    )


def collect_scoring_formula_issues(
    benchmarks: Iterable[BenchmarkConfig],
    benchmark_ids: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Валидирует scoring expression в benchmark/table-level конфигах.

    Проверяются:
    - benchmark.scoring (если mode=expression);
    - table_rules[].scoring (если задано и mode=expression).
    """
    benchmark_filter = set(benchmark_ids) if benchmark_ids else None
    issues: List[str] = []

    for benchmark in sorted(benchmarks, key=lambda item: item.id):
        if benchmark_filter and benchmark.id not in benchmark_filter:
            continue

        issues.extend(
            _issues_for_scoring(
                scoring=benchmark.scoring,
                scope=f"benchmark={benchmark.id}",
            )
        )

        for table_rule in benchmark.table_rules:
            if table_rule.scoring is None:
                continue
            issues.extend(
                _issues_for_scoring(
                    scoring=table_rule.scoring,
                    scope=_scope_for_table_rule(benchmark, table_rule),
                )
            )

    return issues
