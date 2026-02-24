import unittest

from src.clickhouse_ddl import TableDDL
from src.column_rules import ColumnAlternatives, ColumnRule
from src.combiner import (
    MODE_VARIANT_STRATEGIES,
    VariantGenerationStrategy,
    VariantMeta,
    iter_variants,
    register_variant_generation_strategy,
    total_variants,
)
from src.index_rules import IndexAlternatives, IndexRule, IndexVariant
from src.naming import is_variant_table, parse_variant_name, variant_table_name


DDL = """
CREATE TABLE analytics.events
(
    `user_id` UInt64 CODEC(Delta(8), LZ4),
    `event_time` DateTime CODEC(DoubleDelta, ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (user_id, event_time)
"""


class CombinerAndNamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = TableDDL.from_ddl(DDL)
        self.column_rules = [
            ColumnRule(
                by_type="UInt64",
                by_name="user_id",
                alternatives=ColumnAlternatives(
                    types=["UInt64", "UInt32"],
                    codecs=["CODEC(Delta(8), LZ4)"],
                ),
            ),
            ColumnRule(
                by_type="DateTime",
                by_name="event_time",
                alternatives=ColumnAlternatives(
                    types=["DateTime"],
                    codecs=[
                        "CODEC(DoubleDelta, ZSTD(1))",
                        "CODEC(DoubleDelta, LZ4)",
                    ],
                ),
            ),
        ]
        self.index_rules = [
            IndexRule(
                by_type="UInt64",
                by_name="user_id",
                alternatives=IndexAlternatives(
                    variants=[
                        IndexVariant(index_type="minmax", granularity=4),
                        IndexVariant(index_type="bloom_filter(0.01)", granularity=2),
                    ]
                ),
            )
        ]

    def test_total_variants_by_mode(self) -> None:
        """Проверяет, что total variants by mode."""
        self.assertEqual(
            total_variants(
                self.table,
                mode="types",
                column_rules=self.column_rules,
                index_rules=self.index_rules,
            ),
            4,
        )
        self.assertEqual(
            total_variants(
                self.table,
                mode="indexes",
                column_rules=self.column_rules,
                index_rules=self.index_rules,
            ),
            3,
        )
        self.assertEqual(
            total_variants(
                self.table,
                mode="sequential",
                column_rules=self.column_rules,
                index_rules=self.index_rules,
            ),
            7,
        )
        self.assertEqual(
            total_variants(
                self.table,
                mode="combined",
                column_rules=self.column_rules,
                index_rules=self.index_rules,
            ),
            12,
        )

    def test_iter_variants_respects_max_iterations(self) -> None:
        """Проверяет, что iter variants respects max iterations."""
        variants = list(
            iter_variants(
                self.table,
                mode="combined",
                column_rules=self.column_rules,
                index_rules=self.index_rules,
                max_iterations=2,
            )
        )
        self.assertEqual(len(variants), 2)
        self.assertEqual([meta.global_index for _, meta in variants], [0, 1])

    def test_indexes_mode_uses_column_order_for_iteration_priority(self) -> None:
        """Проверяет, что indexes mode uses column order for iteration priority."""
        index_rules = [
            IndexRule(
                by_type="DateTime",
                by_name="event_time",
                alternatives=IndexAlternatives(
                    variants=[IndexVariant(index_type="minmax", granularity=4)]
                ),
            ),
            IndexRule(
                by_type="UInt64",
                by_name="user_id",
                alternatives=IndexAlternatives(
                    variants=[IndexVariant(index_type="minmax", granularity=4)]
                ),
            ),
        ]

        # event_time приоритетнее user_id: второй вариант меняет user_id.
        prioritized_event_time = list(
            iter_variants(
                self.table,
                mode="indexes",
                column_rules=[],
                index_rules=index_rules,
                column_order={"event_time": 1, "user_id": 2},
                max_iterations=2,
            )
        )
        _, meta_first = prioritized_event_time[0]
        _, meta_second = prioritized_event_time[1]
        self.assertIsNone(meta_first.index_choices["event_time"])
        self.assertIsNone(meta_first.index_choices["user_id"])
        self.assertIsNone(meta_second.index_choices["event_time"])
        self.assertIsNotNone(meta_second.index_choices["user_id"])

        # user_id приоритетнее event_time: второй вариант меняет event_time.
        prioritized_user_id = list(
            iter_variants(
                self.table,
                mode="indexes",
                column_rules=[],
                index_rules=index_rules,
                column_order={"user_id": 1, "event_time": 2},
                max_iterations=2,
            )
        )
        _, meta_second_reversed = prioritized_user_id[1]
        self.assertIsNotNone(meta_second_reversed.index_choices["event_time"])
        self.assertIsNone(meta_second_reversed.index_choices["user_id"])

    def test_variant_name_roundtrip(self) -> None:
        """Проверяет, что variant name roundtrip."""
        name = variant_table_name("user-events", "bench prod", 42)

        self.assertEqual(name, "user_events__bench__bench_prod__0042")
        self.assertEqual(
            parse_variant_name(name), ("user_events", "bench_prod", 42)
        )
        self.assertTrue(is_variant_table(name))

    def test_variant_name_is_truncated_to_clickhouse_limit(self) -> None:
        """Проверяет, что variant name is truncated to clickhouse limit."""
        name = variant_table_name("a" * 200, "bench", 1)
        self.assertLessEqual(len(name), 64)
        self.assertTrue(name.endswith("__bench__bench__0001"))

    def test_variant_name_raises_for_too_long_benchmark_id(self) -> None:
        """Проверяет, что variant name raises for too long benchmark id."""
        with self.assertRaises(ValueError):
            variant_table_name("events", "b" * 100, 0)

    def test_custom_variant_strategy_can_be_registered(self) -> None:
        """Проверяет, что custom variant strategy can be registered."""
        mode = "__test_custom_mode__"
        previous_strategy = MODE_VARIANT_STRATEGIES.get(mode)

        class SingleVariantStrategy(VariantGenerationStrategy):
            def iter_variants(self, table, column_rules, index_rules, column_order=None):
                del column_rules, index_rules, column_order
                yield table.copy(), VariantMeta(global_index=0, mode=mode)

            def total_variants(self, table, column_rules, index_rules, column_order=None):
                del table, column_rules, index_rules, column_order
                return 1

        def cleanup() -> None:
            if previous_strategy is None:
                MODE_VARIANT_STRATEGIES.pop(mode, None)
            else:
                MODE_VARIANT_STRATEGIES[mode] = previous_strategy

        self.addCleanup(cleanup)
        register_variant_generation_strategy(
            mode=mode,
            strategy=SingleVariantStrategy(),
            overwrite=True,
        )

        variants = list(
            iter_variants(
                self.table,
                mode=mode,
                column_rules=self.column_rules,
                index_rules=self.index_rules,
            )
        )

        self.assertEqual(len(variants), 1)
        self.assertEqual(total_variants(
            self.table,
            mode=mode,
            column_rules=self.column_rules,
            index_rules=self.index_rules,
        ), 1)
        self.assertEqual(variants[0][1].mode, mode)
        self.assertEqual(variants[0][1].global_index, 0)

    def test_register_variant_strategy_rejects_duplicate_without_overwrite(self) -> None:
        """Проверяет, что register variant strategy rejects duplicate without overwrite."""

        class DummyStrategy(VariantGenerationStrategy):
            def iter_variants(self, table, column_rules, index_rules, column_order=None):
                del table, column_rules, index_rules, column_order
                return iter(())

            def total_variants(self, table, column_rules, index_rules, column_order=None):
                del table, column_rules, index_rules, column_order
                return 0

        with self.assertRaisesRegex(ValueError, "уже зарегистрирована"):
            register_variant_generation_strategy("types", DummyStrategy())

    def test_iter_variants_raises_for_unknown_mode(self) -> None:
        """Проверяет, что iter variants raises for unknown mode."""
        with self.assertRaisesRegex(ValueError, "Неизвестный mode"):
            list(
                iter_variants(
                    self.table,
                    mode="unknown_mode",
                    column_rules=self.column_rules,
                    index_rules=self.index_rules,
                )
            )

    def test_total_variants_raises_for_unknown_mode(self) -> None:
        """Проверяет, что total variants raises for unknown mode."""
        with self.assertRaisesRegex(ValueError, "Неизвестный mode"):
            total_variants(
                self.table,
                mode="unknown_mode",
                column_rules=self.column_rules,
                index_rules=self.index_rules,
            )

    def test_register_variant_strategy_rejects_empty_mode(self) -> None:
        """Проверяет, что register variant strategy rejects empty mode."""

        class DummyStrategy(VariantGenerationStrategy):
            def iter_variants(self, table, column_rules, index_rules, column_order=None):
                del table, column_rules, index_rules, column_order
                return iter(())

            def total_variants(self, table, column_rules, index_rules, column_order=None):
                del table, column_rules, index_rules, column_order
                return 0

        with self.assertRaisesRegex(ValueError, "не должен быть пустым"):
            register_variant_generation_strategy("   ", DummyStrategy())


if __name__ == "__main__":
    unittest.main()
