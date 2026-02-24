import unittest

from pydantic import ValidationError

from src.models import (
    BenchmarkConfig,
    BenchmarkProjectConfig,
    ColumnRuleConfig,
    InsertRowsLimitsConfig,
    IndexConfig,
    IndexRuleConfig,
    QueriesConfig,
    RuleBankConfig,
    RulesConfig,
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

    def test_queries_manual_requires_test_queries(self) -> None:
        """Проверяет, что queries manual requires test queries."""
        with self.assertRaises(ValidationError):
            QueriesConfig(mode="manual")

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

    def test_benchmark_config_accepts_sequential_dispatch_strategies(self) -> None:
        """Проверяет, что benchmark config принимает sequential dispatch strategies."""
        stage1 = BenchmarkConfig(
            id="bench_seq_stage1",
            connection_id="conn",
            strategy="sequential_topn_stage1_dispatch_strategy",
            databases=["analytics"],
            tables=["events"],
            global_rules=RulesConfig(
                column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64"])]
            ),
        )
        stage2 = stage1.model_copy(
            update={"id": "bench_seq_stage2", "strategy": "sequential_topn_stage2_dispatch_strategy"}
        )
        self.assertEqual(stage1.strategy, "sequential_topn_stage1_dispatch_strategy")
        self.assertEqual(stage2.strategy, "sequential_topn_stage2_dispatch_strategy")

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
                insert_rows_limit=0,
            )

        with self.assertRaises(ValidationError):
            TableRuleConfig(
                database="analytics",
                table="events",
                insert_rows_limit=0,
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
                insert_rows_limits=InsertRowsLimitsConfig(types=0),
            )

        with self.assertRaises(ValidationError):
            TableRuleConfig(
                database="analytics",
                table="events",
                insert_rows_limits=InsertRowsLimitsConfig(indexes=0),
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
                "insert_rows_limits": {
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
                    "insert_rows_limits": {
                        "future_mode_x": 0,
                    },
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
                    codecs=["CODEC(Delta(8), LZ4)"],
                )
            ],
            index_rules=[
                IndexRuleConfig(
                    by_type="UInt64",
                    indexes=[IndexConfig(type="minmax", granularity=4)],
                )
            ],
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
        self.assertEqual(len(resolved.index_rules), 1)
        self.assertEqual(resolved.index_rules[0].by_type, "UInt64")

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


if __name__ == "__main__":
    unittest.main()
