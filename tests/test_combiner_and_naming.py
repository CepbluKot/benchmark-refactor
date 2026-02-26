import re
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

DDL_WITH_INDEX_GRANULARITY = """
CREATE TABLE analytics.events_with_settings
(
    `user_id` UInt64 CODEC(Delta(8), LZ4),
    `event_time` DateTime CODEC(DoubleDelta, ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (user_id, event_time)
SETTINGS index_granularity = 8192, allow_nullable_key = 1
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
            2,
        )
        self.assertEqual(
            total_variants(
                self.table,
                mode="sequential",
                column_rules=self.column_rules,
                index_rules=self.index_rules,
            ),
            6,
        )
        self.assertEqual(
            total_variants(
                self.table,
                mode="combined",
                column_rules=self.column_rules,
                index_rules=self.index_rules,
            ),
            8,
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
        self.assertIsNotNone(meta_first.index_choices["user_id"])
        self.assertIsNotNone(meta_second.index_choices["event_time"])
        self.assertIsNone(meta_second.index_choices["user_id"])

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
        self.assertIsNone(meta_second_reversed.index_choices["event_time"])
        self.assertIsNotNone(meta_second_reversed.index_choices["user_id"])

    def test_indexes_mode_crosses_with_table_index_granularity_values(self) -> None:
        """Проверяет декартово произведение index-вариантов и SETTINGS index_granularity."""
        total = total_variants(
            self.table,
            mode="indexes",
            column_rules=self.column_rules,
            index_rules=self.index_rules,
            table_index_granularity_values=[8192, 16384],
        )
        self.assertEqual(total, 4)  # (2 variants) * 2 granularity values

        variants = list(
            iter_variants(
                self.table,
                mode="indexes",
                column_rules=self.column_rules,
                index_rules=self.index_rules,
                table_index_granularity_values=[8192, 16384],
            )
        )
        self.assertEqual(len(variants), 4)

        granularities = {
            meta.table_index_granularity
            for _, meta in variants
        }
        self.assertEqual(granularities, {8192, 16384})
        self.assertTrue(
            all("SETTINGS index_granularity =" in variant.to_ddl() for variant, _ in variants)
        )

    def test_combined_mode_crosses_with_table_index_granularity_values(self) -> None:
        """Проверяет, что combined учитывает table index_granularity в общем числе вариантов."""
        total = total_variants(
            self.table,
            mode="combined",
            column_rules=self.column_rules,
            index_rules=self.index_rules,
            table_index_granularity_values=[8192, 16384],
        )
        self.assertEqual(total, 16)  # 4 column variants * (2 * 2)

    def test_indexes_mode_supports_per_index_table_granularity_values(self) -> None:
        """Проверяет per-index index_granularity_values в indexes-режиме."""
        index_rules = [
            IndexRule(
                by_type="UInt64",
                by_name="user_id",
                alternatives=IndexAlternatives(
                    variants=[
                        IndexVariant(
                            index_type="minmax",
                            granularity=4,
                            table_index_granularity_values=[8192],
                        ),
                        IndexVariant(
                            index_type="bloom_filter(0.01)",
                            granularity=2,
                            table_index_granularity_values=[16384],
                        ),
                    ]
                ),
            )
        ]

        total = total_variants(
            self.table,
            mode="indexes",
            column_rules=[],
            index_rules=index_rules,
        )
        self.assertEqual(total, 2)

        variants = list(
            iter_variants(
                self.table,
                mode="indexes",
                column_rules=[],
                index_rules=index_rules,
            )
        )
        self.assertEqual(len(variants), 2)
        choices = {
            (
                meta.index_choices["user_id"].index_type
                if meta.index_choices["user_id"] is not None
                else None,
                meta.table_index_granularity,
            )
            for _, meta in variants
        }
        self.assertEqual(
            choices,
            {
                ("minmax", 8192),
                ("bloom_filter(0.01)", 16384),
            },
        )

    def test_indexes_mode_intersects_global_and_per_index_granularity_values(self) -> None:
        """Проверяет пересечение global и per-index index_granularity_values."""
        index_rules = [
            IndexRule(
                by_type="UInt64",
                by_name="user_id",
                alternatives=IndexAlternatives(
                    variants=[
                        IndexVariant(
                            index_type="minmax",
                            granularity=4,
                            table_index_granularity_values=[16384, 32768],
                        ),
                    ]
                ),
            )
        ]

        total = total_variants(
            self.table,
            mode="indexes",
            column_rules=[],
            index_rules=index_rules,
            table_index_granularity_values=[8192, 16384],
        )
        self.assertEqual(total, 1)

        variants = list(
            iter_variants(
                self.table,
                mode="indexes",
                column_rules=[],
                index_rules=index_rules,
                table_index_granularity_values=[8192, 16384],
            )
        )
        self.assertEqual(len(variants), 1)
        selected_with_index = [
            meta.table_index_granularity
            for _, meta in variants
            if meta.index_choices["user_id"] is not None
        ]
        self.assertEqual(selected_with_index, [16384])

    def test_indexes_mode_skips_conflicting_per_index_granularity_combos(self) -> None:
        """Проверяет, что конфликтующие per-index ограничения корректно отбрасываются."""
        index_rules = [
            IndexRule(
                by_type="UInt64",
                by_name="user_id",
                alternatives=IndexAlternatives(
                    variants=[
                        IndexVariant(
                            index_type="minmax",
                            granularity=4,
                            table_index_granularity_values=[8192],
                        )
                    ]
                ),
            ),
            IndexRule(
                by_type="DateTime",
                by_name="event_time",
                alternatives=IndexAlternatives(
                    variants=[
                        IndexVariant(
                            index_type="minmax",
                            granularity=4,
                            table_index_granularity_values=[16384],
                        )
                    ]
                ),
            ),
        ]

        total = total_variants(
            self.table,
            mode="indexes",
            column_rules=[],
            index_rules=index_rules,
        )
        self.assertEqual(total, 2)

        variants = list(
            iter_variants(
                self.table,
                mode="indexes",
                column_rules=[],
                index_rules=index_rules,
            )
        )
        self.assertEqual(len(variants), 2)
        self.assertTrue(
            all(
                not (
                    meta.index_choices["user_id"] is not None
                    and meta.index_choices["event_time"] is not None
                )
                for _, meta in variants
            )
        )

    def test_generated_variants_keep_single_valid_index_granularity_assignment(self) -> None:
        """Проверяет, что при исходном SETTINGS index_granularity нет конфликтов в variants."""
        table = TableDDL.from_ddl(DDL_WITH_INDEX_GRANULARITY)
        variants = list(
            iter_variants(
                table,
                mode="indexes",
                column_rules=self.column_rules,
                index_rules=self.index_rules,
                table_index_granularity_values=[4096, 16384],
            )
        )

        for variant, meta in variants:
            rendered = variant.to_ddl()
            self.assertEqual(
                len(
                    re.findall(
                        r"index_granularity\s*=",
                        rendered,
                        flags=re.IGNORECASE,
                    )
                ),
                1,
            )
            if meta.table_index_granularity is not None:
                self.assertIn(
                    f"index_granularity = {meta.table_index_granularity}",
                    rendered,
                )
            reparsed = TableDDL.from_ddl(rendered)
            self.assertEqual(
                reparsed.get_index_granularity(),
                meta.table_index_granularity,
            )

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
