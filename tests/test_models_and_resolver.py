import unittest

from pydantic import ValidationError

from src.models import (
    BenchmarkConfig,
    BenchmarkProjectConfig,
    CodecRuleConfig,
    ColumnRuleConfig,
    InsertRowsLimitsConfig,
    IndexConfig,
    IndexRuleConfig,
    OrderByRulesConfig,
    QueriesConfig,
    RuleBankConfig,
    RulesConfig,
    ScoringConfig,
    TableRuleConfig,
)
from src.resolver import RuleResolver


class ModelsValidationTests(unittest.TestCase):
    def test_column_rule_requires_matcher(self) -> None:
        """Проверяет, что column rule requires matcher."""
        with self.assertRaises(ValidationError):
            ColumnRuleConfig()

    def test_column_rule_by_name_requires_by_type(self) -> None:
        """Проверяет, что column rule by name requires by type."""
        with self.assertRaises(ValidationError):
            ColumnRuleConfig(by_name="user_id")

    def test_column_rule_rejects_empty_auto_compressions_datatype(self) -> None:
        """Проверяет, что auto_compressions_datatype не может быть пустым."""
        with self.assertRaises(ValidationError):
            ColumnRuleConfig(
                by_type="String",
                auto_generate_alternatives=True,
                auto_compressions_datatype="   ",
            )

    def test_index_rule_rejects_empty_auto_indexes_datatype(self) -> None:
        """Проверяет, что auto_indexes_datatype не может быть пустым."""
        with self.assertRaises(ValidationError):
            IndexRuleConfig(
                by_type="String",
                auto_generate_indexes=True,
                auto_indexes_datatype="   ",
            )

    def test_index_config_normalizes_per_index_table_granularity_values(self) -> None:
        """Проверяет per-index index_granularity_values в IndexConfig."""
        index_cfg = IndexConfig.model_validate(
            {
                "type": "minmax",
                "granularity": 4,
                "index_granularity_values": [8192, 16384, 8192],
            }
        )
        self.assertEqual(index_cfg.table_index_granularity_values, [8192, 16384])

        with self.assertRaises(ValidationError):
            IndexConfig.model_validate(
                {
                    "type": "minmax",
                    "granularity": 4,
                    "index_granularity_values": [0, 8192],
                }
            )

    def test_index_config_accepts_granularity_array_and_normalizes_it(self) -> None:
        """Проверяет, что granularity может задаваться массивом значений."""
        index_cfg = IndexConfig.model_validate(
            {
                "type": "minmax",
                "granularity": [4, 2, 4],
            }
        )
        self.assertEqual(index_cfg.granularity, 4)
        self.assertEqual(index_cfg.granularity_values, [4, 2])
        self.assertEqual(index_cfg.iter_granularity_values(), [4, 2])

        with self.assertRaises(ValidationError):
            IndexConfig.model_validate(
                {
                    "type": "minmax",
                    "granularity": [0, 2],
                }
            )

        with self.assertRaises(ValidationError):
            IndexConfig.model_validate(
                {
                    "type": "minmax",
                    "granularity": [],
                }
            )

    def test_queries_manual_requires_test_queries(self) -> None:
        """Проверяет, что queries manual requires test queries."""
        with self.assertRaises(ValidationError):
            QueriesConfig(mode="manual")

    def test_test_query_rejects_removed_weight_field(self) -> None:
        """Проверяет, что `weight` больше не поддерживается в test_queries[]."""
        with self.assertRaises(ValidationError):
            QueriesConfig.model_validate(
                {
                    "mode": "manual",
                    "test_queries": [
                        {
                            "query": "SELECT 1",
                            "weight": 1.0,
                        }
                    ],
                }
            )

    def test_queries_rejects_removed_global_warmup_queries(self) -> None:
        """Проверяет, что глобальный queries.warmup_queries больше не поддерживается."""
        with self.assertRaises(ValidationError):
            QueriesConfig.model_validate(
                {
                    "mode": "manual",
                    "warmup_queries": ["SELECT 1"],
                    "test_queries": [
                        {
                            "query": "SELECT 1",
                        }
                    ],
                }
            )

    def test_test_query_validates_cold_mode_warmup_and_select_count(self) -> None:
        """Проверяет валидацию cache_mode/select_operations_count для test_queries[]."""
        with self.assertRaises(ValidationError):
            QueriesConfig.model_validate(
                {
                    "mode": "manual",
                    "test_queries": [
                        {
                            "query": "SELECT 1",
                            "cache_mode": "cold",
                            "select_operations_count": 0,
                        }
                    ],
                }
            )

        with self.assertRaises(ValidationError):
            QueriesConfig.model_validate(
                {
                    "mode": "manual",
                    "test_queries": [
                        {
                            "query": "SELECT 1",
                            "cache_mode": "cold",
                            "select_operations_count": 1,
                            "warmup_queries": ["SELECT 1"],
                        }
                    ],
                }
            )

        parsed = QueriesConfig.model_validate(
            {
                "mode": "manual",
                "test_queries": [
                    {
                        "query": "SELECT count() FROM {table}",
                        "cache_mode": "warm",
                        "select_operations_count": 3,
                        "warmup_queries": ["SELECT count() FROM {table}"],
                    }
                ],
            }
        )
        self.assertEqual(parsed.test_queries[0].cache_mode, "warm")
        self.assertEqual(parsed.test_queries[0].select_operations_count, 3)

    def test_benchmark_config_rejects_duplicate_table_rules(self) -> None:
        """Проверяет, что benchmark config rejects duplicate table rules."""
        with self.assertRaises(ValidationError):
            BenchmarkConfig(
                id="bench",
                connection_id="conn",
                strategy="types_strategy",
                databases=["analytics"],
                tables=["events"],
                table_rules=[
                    TableRuleConfig(database="analytics", table="events"),
                    TableRuleConfig(database="analytics", table="events"),
                ],
            )

    def test_benchmark_config_rejects_benchmark_level_celery(self) -> None:
        """Проверяет, что benchmark config rejects benchmark level celery."""
        with self.assertRaises(ValidationError):
            BenchmarkConfig.model_validate(
                {
                    "id": "bench",
                    "connection_id": "conn",
                    "strategy": "types_strategy",
                    "databases": ["analytics"],
                    "tables": ["events"],
                    "celery": {"workers": 2, "threads_per_worker": 1},
                }
            )

    def test_benchmark_config_rejects_unknown_rules_mode(self) -> None:
        """Проверяет, что benchmark config rejects unknown rules mode."""
        with self.assertRaises(ValidationError):
            BenchmarkConfig.model_validate(
                {
                    "id": "bench",
                    "connection_id": "conn",
                    "strategy": "types_strategy",
                    "databases": ["analytics"],
                    "tables": ["events"],
                    "column_rules_mode": "unknown_mode",
                }
            )

    def test_scoring_expression_mode_rejects_empty_expression(self) -> None:
        """Проверяет, что scoring.expression не может быть пустым."""
        with self.assertRaises(ValidationError):
            ScoringConfig(mode="expression", expression="   ")

    def test_scoring_rejects_builtin_mode(self) -> None:
        """Проверяет, что mode=builtin больше не поддерживается."""
        with self.assertRaises(ValidationError):
            ScoringConfig(mode="builtin", expression="1 + 1")

    def test_scoring_allows_stage_expression_overrides(self) -> None:
        """Проверяет, что stage-specific expression работает при глобальном expression."""
        scoring = ScoringConfig.model_validate(
            {
                "mode": "expression",
                "expression": "1 + 1",
                "by_stage": {
                    "types": {
                        "mode": "expression",
                        "expression": "2 + 2",
                    }
                },
            }
        )
        self.assertIsNotNone(scoring.by_stage)
        self.assertIn("types", scoring.by_stage or {})
        self.assertEqual(scoring.stage_override("types").expression, "2 + 2")

    def test_scoring_by_stage_normalizes_stage_name(self) -> None:
        """Проверяет нормализацию ключей scoring.by_stage."""
        scoring = ScoringConfig.model_validate(
            {
                "mode": "expression",
                "expression": "1 + 1",
                "by_stage": {
                    "  TyPeS  ": {
                        "mode": "expression",
                        "expression": "2 + 2",
                    }
                },
            }
        )
        self.assertIsNotNone(scoring.by_stage)
        self.assertIn("types", scoring.by_stage or {})
        self.assertIsNotNone(scoring.stage_override("types"))

    def test_scoring_by_stage_rejects_empty_stage_name(self) -> None:
        """Проверяет, что пустой ключ в scoring.by_stage запрещён."""
        with self.assertRaises(ValidationError):
            ScoringConfig.model_validate(
                {
                    "mode": "expression",
                    "expression": "1 + 1",
                    "by_stage": {
                        "   ": {
                            "mode": "expression",
                            "expression": "2 + 2",
                        }
                    },
                }
            )

    def test_benchmark_config_accepts_scoring_expression(self) -> None:
        """Проверяет заполнение scoring.expression."""
        benchmark = BenchmarkConfig.model_validate(
            {
                "id": "bench_scoring_alias",
                "connection_id": "conn",
                "strategy": "types_strategy",
                "databases": ["analytics"],
                "tables": ["events"],
                "global_rules": {
                    "column_rules": [{"by_type": "UInt64", "types": ["UInt64"]}]
                },
                "scoring": {
                    "mode": "expression",
                    "expression": "safe_div(2, 1)",
                    "on_error_score": -1.0,
                },
            }
        )
        self.assertEqual(benchmark.scoring.mode, "expression")
        self.assertEqual(benchmark.scoring.expression, "safe_div(2, 1)")
        self.assertEqual(benchmark.scoring.on_error_score, -1.0)

    def test_benchmark_config_accepts_strategy(self) -> None:
        """Проверяет, что benchmark config accepts strategy."""
        benchmark = BenchmarkConfig(
            id="bench_strategy_only",
            connection_id="conn",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            global_rules=RulesConfig(
                column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64"])]
            ),
        )
        self.assertEqual(benchmark.strategy, "types_strategy")

    def test_benchmark_config_rejects_removed_sequential_dispatch_strategies(self) -> None:
        """Проверяет, что удалённые sequential dispatch стратегии недоступны в конфиге."""
        for removed_strategy in (
            "sequential_topn_stage1_dispatch_strategy",
            "sequential_topn_stage2_dispatch_strategy",
        ):
            with self.subTest(strategy=removed_strategy):
                with self.assertRaises(ValidationError):
                    BenchmarkConfig(
                        id=f"bench_removed_{removed_strategy}",
                        connection_id="conn",
                        strategy=removed_strategy,
                        databases=["analytics"],
                        tables=["events"],
                        global_rules=RulesConfig(
                            column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64"])]
                        ),
                    )

    def test_benchmark_config_rejects_legacy_mode_field(self) -> None:
        """Проверяет, что benchmark config rejects legacy mode field."""
        with self.assertRaises(ValidationError):
            BenchmarkConfig.model_validate(
                {
                    "id": "bench_legacy_mode_field",
                    "connection_id": "conn",
                    "mode": "types",
                    "strategy": "types_strategy",
                    "databases": ["analytics"],
                    "tables": ["events"],
                }
            )

    def test_table_rule_rejects_legacy_mode_field(self) -> None:
        """Проверяет, что table rule rejects legacy mode field."""
        with self.assertRaises(ValidationError):
            TableRuleConfig.model_validate(
                {
                    "database": "analytics",
                    "table": "events",
                    "mode": "types",
                }
            )

    def test_benchmark_project_requires_exactly_one_benchmarks_source(self) -> None:
        """Проверяет, что benchmark project requires exactly one benchmarks source."""
        with self.assertRaises(ValidationError):
            BenchmarkProjectConfig(
                connections_file="connections.json",
                rule_banks_file="rule_banks.json",
            )

        with self.assertRaises(ValidationError):
            BenchmarkProjectConfig(
                connections_file="connections.json",
                rule_banks_file="rule_banks.json",
                benchmarks=[],
                benchmarks_file="benchmarks.json",
            )

    def test_insert_rows_limit_must_be_positive_when_set(self) -> None:
        """Проверяет, что insert rows limit must be positive when set."""
        with self.assertRaises(ValidationError):
            BenchmarkConfig(
                id="bench",
                connection_id="conn",
                strategy="types_strategy",
                databases=["analytics"],
                tables=["events"],
                global_rules=RulesConfig(
                    column_rules=[
                        ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])
                    ]
                ),
                insert_rows_per_operation_limit=0,
            )

        with self.assertRaises(ValidationError):
            BenchmarkConfig(
                id="bench",
                connection_id="conn",
                strategy="types_strategy",
                databases=["analytics"],
                tables=["events"],
                global_rules=RulesConfig(
                    column_rules=[
                        ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])
                    ]
                ),
                source_insert_rows_per_operation_limit=0,
            )

        with self.assertRaises(ValidationError):
            TableRuleConfig(
                database="analytics",
                table="events",
                insert_rows_per_operation_limit=0,
            )

        with self.assertRaises(ValidationError):
            TableRuleConfig(
                database="analytics",
                table="events",
                source_insert_rows_per_operation_limit=0,
            )

    def test_insert_rows_limits_by_mode_must_be_positive_when_set(self) -> None:
        """Проверяет, что insert rows limits by mode must be positive when set."""
        with self.assertRaises(ValidationError):
            BenchmarkConfig(
                id="bench",
                connection_id="conn",
                strategy="types_strategy",
                databases=["analytics"],
                tables=["events"],
                global_rules=RulesConfig(
                    column_rules=[
                        ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])
                    ]
                ),
                insert_rows_per_operation_limits=InsertRowsLimitsConfig(types=0),
            )

        with self.assertRaises(ValidationError):
            TableRuleConfig(
                database="analytics",
                table="events",
                insert_rows_per_operation_limits=InsertRowsLimitsConfig(indexes=0),
            )

    def test_insert_rows_limits_accepts_future_mode_keys(self) -> None:
        """Проверяет, что insert rows limits accepts future mode keys."""
        bench = BenchmarkConfig.model_validate(
            {
                "id": "bench_future_insert_limits",
                "connection_id": "conn",
                "strategy": "types_strategy",
                "databases": ["analytics"],
                "tables": ["events"],
                "global_rules": {
                    "column_rules": [{"by_type": "UInt64", "types": ["UInt64"]}]
                },
                "insert_rows_per_operation_limits": {
                    "types": 100,
                    "future_mode_x": 55,
                },
            }
        )
        self.assertIsNotNone(bench.insert_rows_limits)
        self.assertEqual(bench.insert_rows_limits.for_mode("types"), 100)
        self.assertEqual(bench.insert_rows_limits.for_mode("future_mode_x"), 55)

    def test_insert_rows_limits_rejects_invalid_future_mode_values(self) -> None:
        """Проверяет, что insert rows limits rejects invalid future mode values."""
        with self.assertRaises(ValidationError):
            BenchmarkConfig.model_validate(
                {
                    "id": "bench_invalid_future_mode_limit",
                    "connection_id": "conn",
                    "strategy": "types_strategy",
                    "databases": ["analytics"],
                    "tables": ["events"],
                    "global_rules": {
                        "column_rules": [{"by_type": "UInt64", "types": ["UInt64"]}]
                    },
                    "insert_rows_per_operation_limits": {
                        "future_mode_x": 0,
                    },
                }
            )

    def test_new_insert_and_sequential_aliases_are_supported(self) -> None:
        """Проверяет, что новые имена полей корректно мапятся в модель."""
        bench = BenchmarkConfig.model_validate(
            {
                "id": "bench_new_aliases",
                "connection_id": "conn",
                "strategy": "sequential_topn_strategy",
                "databases": ["analytics"],
                "tables": ["events"],
                "global_rules": {
                    "column_rules": [{"by_type": "UInt64", "types": ["UInt64"]}]
                },
                "insert_operations_count": 7,
                "sequential_types_top_n_for_indexes": 3,
                "sequential_top_n_limits": {
                    "order_by": 4,
                    "types": 3,
                    "codecs": 2,
                    "indexes": 1,
                },
                "max_winners_per_parent_limits": {
                    "types": 2,
                    "codecs": 2,
                    "indexes": 1,
                },
                "insert_rows_per_operation_limit": 123,
                "source_insert_rows_per_operation_limit": 77,
                "source_insert_rows_per_operation_limits": {
                    "sequential": 66
                },
                "insert_rows_per_operation_limits": {
                    "types": 100,
                    "indexes": 50,
                    "future_mode_x": 33,
                },
                "max_benchmarks_limits": {
                    "types": 9,
                    "indexes": 11,
                    "sequential": 8,
                },
                "index_granularity_values": [8192, 16384],
                "table_rules": [
                    {
                        "database": "analytics",
                        "table": "events",
                        "insert_operations_count": 4,
                        "sequential_types_top_n_for_indexes": 2,
                        "sequential_top_n_limits": {
                            "types": 2,
                            "indexes": 1
                        },
                        "max_winners_per_parent_limits": {
                            "types": 2,
                            "codecs": 1,
                        },
                        "insert_rows_per_operation_limit": 99,
                        "source_insert_rows_per_operation_limit": 44,
                        "source_insert_rows_per_operation_limits": {
                            "sequential": 33
                        },
                        "insert_rows_per_operation_limits": {
                            "types": 88,
                            "future_mode_y": 22,
                        },
                        "max_benchmarks_limits": {
                            "types": 6,
                            "indexes": 7,
                        },
                        "index_granularity_values": [4096, 8192, 4096],
                    }
                ],
            }
        )

        self.assertEqual(bench.insert_operations_count, 7)
        self.assertEqual(bench.sequential_top_n, 3)
        self.assertIsNotNone(bench.sequential_top_n_limits)
        self.assertEqual(bench.sequential_top_n_limits.for_mode("order_by"), 4)
        self.assertEqual(bench.sequential_top_n_limits.for_mode("types"), 3)
        self.assertEqual(bench.sequential_top_n_limits.for_mode("codecs"), 2)
        self.assertEqual(bench.sequential_top_n_limits.for_mode("indexes"), 1)
        self.assertIsNotNone(bench.max_winners_per_parent_limits)
        self.assertEqual(bench.max_winners_per_parent_limits.for_mode("types"), 2)
        self.assertEqual(bench.max_winners_per_parent_limits.for_mode("codecs"), 2)
        self.assertEqual(bench.max_winners_per_parent_limits.for_mode("indexes"), 1)
        self.assertEqual(bench.insert_rows_limit, 123)
        self.assertEqual(bench.source_insert_rows_limit, 77)
        self.assertIsNotNone(bench.source_insert_rows_limits)
        self.assertEqual(bench.source_insert_rows_limits.sequential, 66)
        self.assertIsNotNone(bench.max_benchmarks_limits)
        self.assertEqual(bench.max_benchmarks_limits.types, 9)
        self.assertEqual(bench.max_benchmarks_limits.indexes, 11)
        self.assertEqual(bench.max_benchmarks_limits.sequential, 8)
        self.assertEqual(bench.index_granularity_values, [8192, 16384])
        self.assertIsNotNone(bench.insert_rows_limits)
        self.assertEqual(bench.insert_rows_limits.for_mode("types"), 100)
        self.assertEqual(bench.insert_rows_limits.for_mode("future_mode_x"), 33)

        self.assertEqual(len(bench.table_rules), 1)
        table_rule = bench.table_rules[0]
        self.assertEqual(table_rule.insert_operations_count, 4)
        self.assertEqual(table_rule.sequential_top_n, 2)
        self.assertIsNotNone(table_rule.sequential_top_n_limits)
        self.assertEqual(table_rule.sequential_top_n_limits.for_mode("types"), 2)
        self.assertEqual(table_rule.sequential_top_n_limits.for_mode("indexes"), 1)
        self.assertIsNotNone(table_rule.max_winners_per_parent_limits)
        self.assertEqual(table_rule.max_winners_per_parent_limits.for_mode("types"), 2)
        self.assertEqual(table_rule.max_winners_per_parent_limits.for_mode("codecs"), 1)
        self.assertEqual(table_rule.insert_rows_limit, 99)
        self.assertEqual(table_rule.source_insert_rows_limit, 44)
        self.assertIsNotNone(table_rule.source_insert_rows_limits)
        self.assertEqual(table_rule.source_insert_rows_limits.sequential, 33)
        self.assertIsNotNone(table_rule.max_benchmarks_limits)
        self.assertEqual(table_rule.max_benchmarks_limits.types, 6)
        self.assertEqual(table_rule.max_benchmarks_limits.indexes, 7)
        self.assertEqual(table_rule.index_granularity_values, [4096, 8192])
        self.assertIsNotNone(table_rule.insert_rows_limits)
        self.assertEqual(table_rule.insert_rows_limits.for_mode("types"), 88)
        self.assertEqual(table_rule.insert_rows_limits.for_mode("future_mode_y"), 22)

    def test_index_granularity_values_reject_invalid_values(self) -> None:
        """Проверяет валидацию index_granularity_values."""
        with self.assertRaises(ValidationError):
            BenchmarkConfig.model_validate(
                {
                    "id": "bench_invalid_index_granularity_values",
                    "connection_id": "conn",
                    "strategy": "types_strategy",
                    "databases": ["analytics"],
                    "tables": ["events"],
                    "index_granularity_values": [],
                }
            )

        with self.assertRaises(ValidationError):
            BenchmarkConfig.model_validate(
                {
                    "id": "bench_invalid_index_granularity_values",
                    "connection_id": "conn",
                    "strategy": "types_strategy",
                    "databases": ["analytics"],
                    "tables": ["events"],
                    "index_granularity_values": [0, 8192],
                }
            )


class RuleResolverTests(unittest.TestCase):
    @staticmethod
    def _bank() -> RuleBankConfig:
        return RuleBankConfig(
            column_order={"user_id": 1},
            column_rules=[
                ColumnRuleConfig(
                    by_type="UInt64",
                    types=["UInt64", "UInt32"],
                )
            ],
            codec_rules=[
                CodecRuleConfig(
                    by_type="UInt64",
                    codecs=["CODEC(Delta(8), LZ4)"],
                )
            ],
            index_rules=[
                IndexRuleConfig(
                    by_type="UInt64",
                    indexes=[IndexConfig(type="minmax", granularity=4)],
                )
            ],
            order_by_rules=OrderByRulesConfig(
                first_column="event_time",
                candidates=["user_id", "country"],
                auto_generate_candidates=False,
            ),
        )

    def test_resolve_uses_default_bank_by_dbms(self) -> None:
        """Проверяет, что resolve uses default bank by dbms."""
        resolver = RuleResolver(
            banks={"bank_a": self._bank()},
            default_rule_banks={"clickhouse": "bank_a"},
        )

        resolved = resolver.resolve(RulesConfig(), dbms="clickhouse")

        self.assertEqual(resolved.source_bank, "bank_a")
        self.assertEqual(len(resolved.column_rules), 1)
        self.assertEqual(len(resolved.index_rules), 1)
        self.assertEqual(resolved.column_order, {"user_id": 1})
        self.assertEqual(resolved.order_by_first, "event_time")
        self.assertEqual(resolved.order_by_candidates, ["user_id", "country"])
        self.assertFalse(resolved.order_by_auto_generate_candidates)

    def test_inline_overrides_disable_default_bank_fallback(self) -> None:
        """Проверяет, что inline overrides disable default bank fallback."""
        resolver = RuleResolver(
            banks={"bank_a": self._bank()},
            default_rule_banks={"clickhouse": "bank_a"},
        )
        rules = RulesConfig(
            column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt32"])]
        )

        resolved = resolver.resolve(rules, dbms="clickhouse")

        self.assertIsNone(resolved.source_bank)
        self.assertEqual(len(resolved.column_rules), 1)
        self.assertEqual(len(resolved.index_rules), 0)
        self.assertEqual(resolved.column_order, {})
        self.assertIsNone(resolved.order_by_first)
        self.assertIsNone(resolved.order_by_candidates)
        self.assertTrue(resolved.order_by_auto_generate_candidates)

    def test_merge_local_rules_over_global_field_by_field(self) -> None:
        """Проверяет, что merge local rules over global field by field."""
        global_rules = RulesConfig(
            rule_bank="bank_a",
            index_rules=[
                IndexRuleConfig(
                    by_type="UInt64",
                    indexes=[IndexConfig(type="minmax", granularity=4)],
                )
            ],
        )
        local_rules = RulesConfig(
            column_rules=[
                ColumnRuleConfig(
                    by_type="DateTime",
                    codecs=["CODEC(DoubleDelta, ZSTD(1))"],
                )
            ]
        )

        merged = RuleResolver.merge(global_rules, local_rules)

        self.assertEqual(merged.rule_bank, "bank_a")
        self.assertIsNotNone(merged.column_rules)
        self.assertIsNone(merged.codec_rules)
        self.assertIsNotNone(merged.index_rules)
        self.assertEqual(merged.column_rules[0].by_type, "DateTime")
        self.assertEqual(merged.index_rules[0].by_type, "UInt64")

    def test_no_fallback_bank_when_default_absent(self) -> None:
        """Проверяет, что no fallback bank when default absent."""
        resolver = RuleResolver(banks={})
        resolved = resolver.resolve(RulesConfig(), dbms="clickhouse")

        self.assertIsNone(resolved.source_bank)
        self.assertEqual(resolved.column_rules, [])
        self.assertEqual(resolved.index_rules, [])
        self.assertEqual(resolved.column_order, {})
        self.assertIsNone(resolved.order_by_first)
        self.assertIsNone(resolved.order_by_candidates)
        self.assertTrue(resolved.order_by_auto_generate_candidates)

    def test_global_bank_only_mode_ignores_inline_rules(self) -> None:
        """Проверяет, что global bank only mode ignores inline rules."""
        resolver = RuleResolver(
            banks={"bank_a": self._bank()},
            default_rule_banks={"clickhouse": "bank_a"},
        )
        global_rules = RulesConfig(rule_bank="bank_a")
        merged = RulesConfig(
            column_rules=[ColumnRuleConfig(by_type="DateTime", codecs=["CODEC(ZSTD(1))"])],
            index_rules=[
                IndexRuleConfig(
                    by_type="DateTime",
                    indexes=[IndexConfig(type="minmax", granularity=8)],
                )
            ],
            column_order={},
        )

        resolved = resolver.resolve(
            merged,
            dbms="clickhouse",
            column_rules_mode="global_bank_only",
            index_rules_mode="global_bank_only",
            global_rules=global_rules,
        )

        self.assertEqual(len(resolved.column_rules), 1)
        self.assertEqual(resolved.column_rules[0].by_type, "UInt64")
        self.assertEqual(
            resolved.column_rules[0].alternatives.codecs,
            ["CODEC(Delta(8), LZ4)"],
        )
        self.assertEqual(len(resolved.index_rules), 1)
        self.assertEqual(resolved.index_rules[0].by_type, "UInt64")
        self.assertEqual(resolved.order_by_first, "event_time")
        self.assertFalse(resolved.order_by_auto_generate_candidates)

    def test_global_bank_with_inline_priority_prepends_inline(self) -> None:
        """Проверяет, что global bank with inline priority prepends inline."""
        resolver = RuleResolver(
            banks={"bank_a": self._bank()},
            default_rule_banks={"clickhouse": "bank_a"},
        )
        global_rules = RulesConfig(rule_bank="bank_a")
        merged = RulesConfig(
            column_rules=[ColumnRuleConfig(by_type="DateTime", codecs=["CODEC(ZSTD(1))"])],
            index_rules=[
                IndexRuleConfig(
                    by_type="DateTime",
                    indexes=[IndexConfig(type="minmax", granularity=8)],
                )
            ],
            column_order={},
        )

        resolved = resolver.resolve(
            merged,
            dbms="clickhouse",
            column_rules_mode="global_bank_with_inline_priority",
            index_rules_mode="global_bank_with_inline_priority",
            global_rules=global_rules,
        )

        self.assertEqual([rule.by_type for rule in resolved.column_rules], ["DateTime", "UInt64"])
        self.assertEqual([rule.by_type for rule in resolved.index_rules], ["DateTime", "UInt64"])
        self.assertEqual(resolved.order_by_first, "event_time")

    def test_inline_only_mode_uses_only_inline_rules(self) -> None:
        """Проверяет, что inline only mode uses only inline rules."""
        resolver = RuleResolver(
            banks={"bank_a": self._bank()},
            default_rule_banks={"clickhouse": "bank_a"},
        )
        global_rules = RulesConfig(rule_bank="bank_a")
        merged = RulesConfig(
            column_rules=[ColumnRuleConfig(by_type="DateTime", codecs=["CODEC(ZSTD(1))"])],
            index_rules=[
                IndexRuleConfig(
                    by_type="DateTime",
                    indexes=[IndexConfig(type="minmax", granularity=8)],
                )
            ],
            column_order={},
        )

        resolved = resolver.resolve(
            merged,
            dbms="clickhouse",
            column_rules_mode="inline_only",
            index_rules_mode="inline_only",
            global_rules=global_rules,
        )

        self.assertEqual(len(resolved.column_rules), 1)
        self.assertEqual(resolved.column_rules[0].by_type, "DateTime")
        self.assertEqual(len(resolved.index_rules), 1)
        self.assertEqual(resolved.index_rules[0].by_type, "DateTime")
        self.assertIsNone(resolved.order_by_first)

    def test_global_bank_mode_raises_when_global_bank_is_missing(self) -> None:
        """Проверяет, что global bank mode raises when global bank is missing."""
        resolver = RuleResolver(banks={"bank_a": self._bank()}, default_rule_banks={})
        merged = RulesConfig(
            column_rules=[ColumnRuleConfig(by_type="DateTime", codecs=["CODEC(ZSTD(1))"])],
            column_order={},
        )

        with self.assertRaisesRegex(ValueError, "требующий глобальный rule bank"):
            resolver.resolve(
                merged,
                dbms="clickhouse",
                column_rules_mode="global_bank_only",
                index_rules_mode="inline_only",
                global_rules=RulesConfig(),
            )

    def test_auto_generate_alternatives_adds_codecs_from_legacy_generator(self) -> None:
        """Проверяет, что auto_generate_alternatives добавляет legacy-кодеки."""
        resolver = RuleResolver(banks={})
        rules = RulesConfig(
            column_rules=[
                ColumnRuleConfig(
                    by_type="String",
                    types=["String", "LowCardinality(String)"],
                    auto_generate_alternatives=True,
                    auto_compressions_datatype="String",
                )
            ]
        )

        resolved = resolver.resolve(rules, dbms="clickhouse")
        self.assertEqual(len(resolved.column_rules), 1)
        alternatives = resolved.column_rules[0].alternatives

        self.assertIn("String", alternatives.types)
        self.assertIn("LowCardinality(String)", alternatives.types)
        self.assertIn("CODEC(LZ4)", alternatives.codecs)
        self.assertIn("CODEC(ZSTD(1))", alternatives.codecs)
        self.assertIn("CODEC(ZSTD(5))", alternatives.codecs)

    def test_auto_generate_alternatives_uses_by_type_when_types_empty(self) -> None:
        """Проверяет fallback на by_type для авто-генерации, если types пустой."""
        resolver = RuleResolver(banks={})
        rules = RulesConfig(
            column_rules=[
                ColumnRuleConfig(
                    by_type="Int32",
                    auto_generate_alternatives=True,
                )
            ]
        )

        resolved = resolver.resolve(rules, dbms="clickhouse")
        alternatives = resolved.column_rules[0].alternatives
        self.assertIn("Int32", alternatives.types)
        self.assertIn("CODEC(LZ4)", alternatives.codecs)
        self.assertIn("CODEC(Delta, ZSTD(1))", alternatives.codecs)

    def test_codec_rules_merge_into_column_rules_by_matcher(self) -> None:
        """Проверяет merge `codec_rules` в `column_rules` по matcher."""
        resolver = RuleResolver(banks={})
        rules = RulesConfig(
            column_rules=[
                ColumnRuleConfig(
                    by_type="String",
                    types=["String", "LowCardinality(String)"],
                )
            ],
            codec_rules=[
                CodecRuleConfig(
                    by_type="String",
                    codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
                )
            ],
        )

        resolved = resolver.resolve(rules, dbms="clickhouse")
        self.assertEqual(len(resolved.column_rules), 1)
        merged_rule = resolved.column_rules[0]
        self.assertEqual(merged_rule.by_type, "String")
        self.assertEqual(merged_rule.alternatives.types, ["String", "LowCardinality(String)"])
        self.assertEqual(
            merged_rule.alternatives.codecs,
            ["CODEC(LZ4)", "CODEC(ZSTD(1))"],
        )

    def test_codec_rules_auto_generate_adds_codecs(self) -> None:
        """Проверяет авто-генерацию кодеков через отдельный блок codec_rules."""
        resolver = RuleResolver(banks={})
        rules = RulesConfig(
            codec_rules=[
                CodecRuleConfig(
                    by_type="Int32",
                    auto_generate_alternatives=True,
                )
            ]
        )

        resolved = resolver.resolve(rules, dbms="clickhouse")
        self.assertEqual(len(resolved.column_rules), 1)
        codecs = resolved.column_rules[0].alternatives.codecs
        self.assertIn("CODEC(LZ4)", codecs)
        self.assertIn("CODEC(Delta, ZSTD(1))", codecs)

    def test_order_by_rules_inline_override_bank_in_priority_mode(self) -> None:
        """Проверяет частичный override order_by_rules в global_bank_with_inline_priority."""
        resolver = RuleResolver(
            banks={"bank_a": self._bank()},
            default_rule_banks={"clickhouse": "bank_a"},
        )
        global_rules = RulesConfig(rule_bank="bank_a")
        merged = RulesConfig(
            order_by_rules=OrderByRulesConfig(candidates=["device_type"]),
        )

        resolved = resolver.resolve(
            merged,
            dbms="clickhouse",
            column_rules_mode="global_bank_with_inline_priority",
            index_rules_mode="global_bank_with_inline_priority",
            global_rules=global_rules,
        )

        self.assertEqual(resolved.order_by_first, "event_time")
        self.assertEqual(resolved.order_by_candidates, ["device_type"])
        self.assertFalse(resolved.order_by_auto_generate_candidates)

    def test_auto_generate_indexes_uses_by_type_when_indexes_empty(self) -> None:
        """Проверяет fallback на by_type для авто-генерации индексов."""
        resolver = RuleResolver(banks={})
        rules = RulesConfig(
            index_rules=[
                IndexRuleConfig(
                    by_type="String",
                    auto_generate_indexes=True,
                )
            ]
        )

        resolved = resolver.resolve(rules, dbms="clickhouse")
        self.assertEqual(len(resolved.index_rules), 1)
        variants = resolved.index_rules[0].alternatives.variants
        variant_pairs = {(item.index_type, item.granularity) for item in variants}

        self.assertIn(("ngrambf_v1(3, 256, 2, 0)", 1), variant_pairs)

    def test_auto_generate_indexes_adds_minmax_for_range_types(self) -> None:
        """Проверяет minmax в авто-индексах для range-типов."""
        resolver = RuleResolver(banks={})
        datatypes = [
            "Int8",
            "Int16",
            "Int32",
            "Int64",
            "Float32",
            "Float64",
            "Decimal(10, 2)",
            "Date",
            "DateTime",
        ]

        for datatype in datatypes:
            with self.subTest(datatype=datatype):
                rules = RulesConfig(
                    index_rules=[
                        IndexRuleConfig(
                            by_type=datatype,
                            auto_generate_indexes=True,
                        )
                    ]
                )
                resolved = resolver.resolve(rules, dbms="clickhouse")
                variants = resolved.index_rules[0].alternatives.variants
                variant_pairs = {(item.index_type, item.granularity) for item in variants}
                self.assertIn(("minmax", 4), variant_pairs)

    def test_auto_generate_indexes_merges_with_manual_and_deduplicates(self) -> None:
        """Проверяет merge ручных и auto-индексов с удалением дублей."""
        resolver = RuleResolver(banks={})
        rules = RulesConfig(
            index_rules=[
                IndexRuleConfig(
                    by_type="UInt64",
                    auto_generate_indexes=True,
                    indexes=[
                        IndexConfig(type="set(200)", granularity=4),
                        IndexConfig(type="set(200)", granularity=4),
                    ],
                )
            ]
        )

        resolved = resolver.resolve(rules, dbms="clickhouse")
        variants = resolved.index_rules[0].alternatives.variants
        variant_pairs = [(item.index_type, item.granularity) for item in variants]

        self.assertEqual(variant_pairs[0], ("set(200)", 4))
        self.assertEqual(
            sorted(set(variant_pairs)),
            sorted(
                {
                    ("minmax", 4),
                    ("set(200)", 4),
                }
            ),
        )

    def test_deduplicate_indexes_keeps_different_per_index_granularity_values(self) -> None:
        """Проверяет, что дубликаты учитывают per-index table index_granularity."""
        resolver = RuleResolver(banks={})
        rules = RulesConfig(
            index_rules=[
                IndexRuleConfig(
                    by_type="UInt64",
                    indexes=[
                        IndexConfig(
                            type="minmax",
                            granularity=4,
                            index_granularity_values=[8192],
                        ),
                        IndexConfig(
                            type="minmax",
                            granularity=4,
                            index_granularity_values=[16384],
                        ),
                    ],
                )
            ]
        )

        resolved = resolver.resolve(rules, dbms="clickhouse")
        variants = resolved.index_rules[0].alternatives.variants
        self.assertEqual(len(variants), 2)
        self.assertEqual(variants[0].table_index_granularity_values, [8192])
        self.assertEqual(variants[1].table_index_granularity_values, [16384])

    def test_index_rule_expands_granularity_array_into_multiple_variants(self) -> None:
        """Проверяет раскрытие granularity-массива в отдельные индекс-варианты."""
        resolver = RuleResolver(banks={})
        rules = RulesConfig(
            index_rules=[
                IndexRuleConfig(
                    by_type="UInt64",
                    indexes=[
                        IndexConfig.model_validate(
                            {
                                "type": "minmax",
                                "granularity": [2, 4, 2],
                                "index_granularity_values": [8192],
                            }
                        )
                    ],
                )
            ]
        )

        resolved = resolver.resolve(rules, dbms="clickhouse")
        variants = resolved.index_rules[0].alternatives.variants
        variant_pairs = [(item.index_type, item.granularity) for item in variants]
        self.assertEqual(variant_pairs, [("minmax", 2), ("minmax", 4)])
        self.assertEqual(
            [item.table_index_granularity_values for item in variants],
            [[8192], [8192]],
        )


if __name__ == "__main__":
    unittest.main()
