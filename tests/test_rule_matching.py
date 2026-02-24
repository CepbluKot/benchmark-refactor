import unittest

from src.clickhouse_ddl import ColumnDef
from src.column_rules import ColumnAlternatives, ColumnRule
from src.index_rules import IndexAlternatives, IndexRule, IndexVariant


class RuleMatchingTests(unittest.TestCase):
    def test_column_rule_matches_by_type_strictly(self) -> None:
        """Проверяет, что column rule matches by type strictly."""
        col = ColumnDef(name="country", type="LowCardinality(String)", codec=None)
        broad_rule = ColumnRule(
            by_type="LowCardinality",
            alternatives=ColumnAlternatives(codecs=["CODEC(ZSTD(1))"]),
        )
        exact_rule = ColumnRule(
            by_type="LowCardinality(String)",
            alternatives=ColumnAlternatives(codecs=["CODEC(ZSTD(1))"]),
        )

        self.assertFalse(broad_rule.matches(col))
        self.assertTrue(exact_rule.matches(col))

    def test_index_rule_matches_by_type_strictly(self) -> None:
        """Проверяет, что index rule matches by type strictly."""
        col = ColumnDef(name="country", type="LowCardinality(String)", codec=None)
        broad_rule = IndexRule(
            by_type="LowCardinality",
            alternatives=IndexAlternatives(
                variants=[IndexVariant(index_type="set(100)", granularity=4)]
            ),
        )
        exact_rule = IndexRule(
            by_type="LowCardinality(String)",
            alternatives=IndexAlternatives(
                variants=[IndexVariant(index_type="set(100)", granularity=4)]
            ),
        )

        self.assertFalse(broad_rule.matches(col))
        self.assertTrue(exact_rule.matches(col))


if __name__ == "__main__":
    unittest.main()
