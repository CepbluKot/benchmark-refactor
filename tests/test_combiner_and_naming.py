import unittest

from clickhouse_ddl import TableDDL
from column_rules import ColumnAlternatives, ColumnRule
from combiner import iter_variants, total_variants
from index_rules import IndexAlternatives, IndexRule, IndexVariant
from naming import is_variant_table, parse_variant_name, variant_table_name


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

    def test_variant_name_roundtrip(self) -> None:
        name = variant_table_name("user-events", "bench prod", 42)

        self.assertEqual(name, "user_events__bench__bench_prod__0042")
        self.assertEqual(
            parse_variant_name(name), ("user_events", "bench_prod", 42)
        )
        self.assertTrue(is_variant_table(name))

    def test_variant_name_is_truncated_to_clickhouse_limit(self) -> None:
        name = variant_table_name("a" * 200, "bench", 1)
        self.assertLessEqual(len(name), 64)
        self.assertTrue(name.endswith("__bench__bench__0001"))

    def test_variant_name_raises_for_too_long_benchmark_id(self) -> None:
        with self.assertRaises(ValueError):
            variant_table_name("events", "b" * 100, 0)


if __name__ == "__main__":
    unittest.main()

