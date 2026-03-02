"""Предзапусковая валидация scoring expression в benchmark-конфигах."""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from src.benchmark_runtime.implementations.clickhouse_celery.scoring import (
    validate_score_expression,
)
from src.models import BenchmarkConfig, ScoringConfig, StageScoringConfig, TableRuleConfig


def _issues_for_scoring(
    *,
    scoring: ScoringConfig | StageScoringConfig,
    scope: str,
) -> List[str]:
    """Возвращает список проблем для одного scoring-блока."""
    issues: list[str] = []
    declared_variables = scoring.variables or {}
    declared_names_in_order: list[str] = []

    for variable_name, variable_expression in declared_variables.items():
        raw_issues = validate_score_expression(
            variable_expression,
            extra_allowed_names=declared_names_in_order,
        )
        issues.extend(
            f"{scope}, variable={variable_name}: {issue}" for issue in raw_issues
        )
        declared_names_in_order.append(variable_name)

    expression = scoring.expression or ""
    raw_issues = validate_score_expression(
        expression,
        extra_allowed_names=declared_names_in_order,
    )
    issues.extend(f"{scope}: {issue}" for issue in raw_issues)
    return issues


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
    - benchmark.scoring;
    - table_rules[].scoring (если задано).
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
        for stage_name, stage_scoring in (benchmark.scoring.by_stage or {}).items():
            issues.extend(
                _issues_for_scoring(
                    scoring=stage_scoring,
                    scope=f"benchmark={benchmark.id}, stage={stage_name}",
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
            for stage_name, stage_scoring in (table_rule.scoring.by_stage or {}).items():
                issues.extend(
                    _issues_for_scoring(
                        scoring=stage_scoring,
                        scope=f"{_scope_for_table_rule(benchmark, table_rule)}, stage={stage_name}",
                    )
                )

    return issues
