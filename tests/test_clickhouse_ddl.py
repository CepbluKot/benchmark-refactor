import unittest

from src.clickhouse_ddl import IndexDef, TableDDL


DDL = """
CREATE TABLE analytics.events
(
    `user_id` UInt64 CODEC(Delta(8), LZ4),
    `event_time` DateTime CODEC(DoubleDelta, ZSTD(1)),
    `country` LowCardinality(String) CODEC(ZSTD(1)),
    INDEX idx_user user_id TYPE minmax GRANULARITY 4
)
ENGINE = MergeTree
ORDER BY (user_id, event_time)
"""

COMPLEX_DDL = """
-- This is a header comment
CREATE TABLE IF NOT EXISTS analytics.events_ext ON CLUSTER `main_cluster`
(
    `id` UInt64 CODEC(Delta(8), LZ4),
    `ts` DateTime DEFAULT now() CODEC(DoubleDelta, ZSTD(1)),
    `payload` Nullable(String) COMMENT 'json payload',
    `attrs` Array(Tuple(UInt8, String)),
    INDEX idx_ts_hour toStartOfHour(ts) TYPE minmax GRANULARITY 2,
    PROJECTION p_ts (SELECT id, ts ORDER BY ts),
    CONSTRAINT c_positive CHECK id > 0
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/events_ext', '{replica}')
PARTITION BY toYYYYMM(ts)
PRIMARY KEY (id, ts)
ORDER BY (id, ts)
SAMPLE BY id
TTL ts + INTERVAL 7 DAY DELETE
SETTINGS index_granularity = 8192
COMMENT 'events extension'
;
"""

NESTED_TYPES_DDL = """
CREATE TABLE analytics.nested_types
(
    `price` Decimal(18,4),
    `state` Tuple(String, UInt8),
    `meta` Array(Tuple(UInt16, String))
)
ENGINE = MergeTree
ORDER BY tuple()
"""

INDEX_WITHOUT_TYPE_DDL = """
CREATE TABLE analytics.no_type_idx
(
    `x` UInt32,
    INDEX idx_x x
)
ENGINE = MergeTree
ORDER BY x
"""

PARAM_INDEX_DDL = """
CREATE TABLE analytics.param_idx
(
    `payload` String,
    INDEX idx_payload payload TYPE bloom_filter(0.01)
)
ENGINE = MergeTree
ORDER BY tuple()
"""

COMMENTED_DDL = """
-- before
CREATE TABLE analytics.comments_test
(
    -- user id line
    `user_id` UInt64,
    `ts` DateTime -- inline trailing comment
)
ENGINE = MergeTree
ORDER BY (user_id, ts)
;
"""


class ClickHouseDDLTests(unittest.TestCase):
    def test_parse_extracts_columns_indexes_and_options(self) -> None:
        """Проверяет, что parse extracts columns indexes and options."""
        table = TableDDL.from_ddl(DDL)

        self.assertEqual(table.name, "analytics.events")
        self.assertEqual(len(table.columns), 3)
        self.assertEqual(len(table.indexes), 1)
        self.assertEqual(table.column("user_id").codec, "CODEC(Delta(8), LZ4)")
        self.assertEqual(table.index("idx_user").index_type, "minmax")
        self.assertEqual(table.index("idx_user").granularity, "4")
        self.assertEqual(table.engine, "MergeTree")
        self.assertEqual(table.order_by, "(user_id, event_time)")

    def test_copy_and_to_ddl_keep_original_unchanged(self) -> None:
        """Проверяет, что copy and to ddl keep original unchanged."""
        source = TableDDL.from_ddl(DDL)
        variant = source.copy()
        variant.column("user_id").type = "UInt32"
        variant.indexes.append(
            IndexDef(
                name="idx_country_bf",
                expr="country",
                index_type="bloom_filter(0.01)",
                granularity="2",
            )
        )
        rendered = variant.to_ddl()

        self.assertEqual(source.column("user_id").type, "UInt64")
        self.assertIn("`user_id` UInt32", rendered)
        self.assertIn(
            "INDEX idx_country_bf country TYPE bloom_filter(0.01) GRANULARITY 2",
            rendered,
        )

    def test_parse_complex_ddl_extracts_cluster_body_and_table_options(self) -> None:
        """Проверяет, что parse complex ddl extracts cluster body and table options."""
        table = TableDDL.from_ddl(COMPLEX_DDL)

        self.assertEqual(table.name, "analytics.events_ext")
        self.assertEqual(table.cluster, "main_cluster")
        self.assertEqual(table.engine, "ReplicatedMergeTree('/clickhouse/tables/{shard}/events_ext', '{replica}')")
        self.assertEqual(table.partition_by, "toYYYYMM(ts)")
        self.assertEqual(table.primary_key, "(id, ts)")
        self.assertEqual(table.order_by, "(id, ts)")
        self.assertEqual(table.sample_by, "id")

        self.assertEqual(len(table.columns), 4)
        self.assertEqual(len(table.indexes), 1)
        self.assertEqual(len(table.other_body_entries), 2)
        self.assertTrue(table.other_body_entries[0].startswith("PROJECTION "))
        self.assertTrue(table.other_body_entries[1].startswith("CONSTRAINT "))

        self.assertEqual(table.column("ts").extra, "DEFAULT now()")
        self.assertEqual(table.column("ts").codec, "CODEC(DoubleDelta, ZSTD(1))")
        self.assertEqual(table.column("payload").codec, None)
        self.assertEqual(table.column("payload").extra, "COMMENT 'json payload'")
        self.assertEqual(table.index("idx_ts_hour").expr, "toStartOfHour(ts)")
        self.assertEqual(table.index("idx_ts_hour").index_type, "minmax")
        self.assertEqual(table.index("idx_ts_hour").granularity, "2")

        self.assertEqual(
            table.other_table_options,
            [
                "TTL ts + INTERVAL 7 DAY DELETE",
                "SETTINGS index_granularity = 8192",
                "COMMENT 'events extension'",
            ],
        )

    def test_parse_preserves_nested_types_with_commas(self) -> None:
        """Проверяет, что parse preserves nested types with commas."""
        table = TableDDL.from_ddl(NESTED_TYPES_DDL)

        self.assertEqual([c.name for c in table.columns], ["price", "state", "meta"])
        self.assertEqual(table.column("price").type, "Decimal(18,4)")
        self.assertEqual(table.column("state").type, "Tuple(String, UInt8)")
        self.assertEqual(table.column("meta").type, "Array(Tuple(UInt16, String))")

    def test_parse_handles_missing_index_type(self) -> None:
        """Проверяет, что parse handles missing index type."""
        table = TableDDL.from_ddl(INDEX_WITHOUT_TYPE_DDL)

        self.assertEqual(len(table.indexes), 1)
        self.assertEqual(table.index("idx_x").expr, "x")
        self.assertEqual(table.index("idx_x").index_type, "")
        self.assertIsNone(table.index("idx_x").granularity)

    def test_parse_handles_parametric_index_type_without_granularity(self) -> None:
        """Проверяет, что parse handles parametric index type without granularity."""
        table = TableDDL.from_ddl(PARAM_INDEX_DDL)

        self.assertEqual(table.index("idx_payload").index_type, "bloom_filter(0.01)")
        self.assertIsNone(table.index("idx_payload").granularity)

    def test_parse_ignores_single_line_comments_and_semicolon(self) -> None:
        """Проверяет, что parse ignores single line comments and semicolon."""
        table = TableDDL.from_ddl(COMMENTED_DDL)

        self.assertEqual(table.name, "analytics.comments_test")
        self.assertEqual(len(table.columns), 2)
        self.assertEqual(table.column("user_id").type, "UInt64")
        self.assertEqual(table.column("ts").type, "DateTime")
        self.assertEqual(table.order_by, "(user_id, ts)")

    def test_to_ddl_orders_known_clauses_and_keeps_other_options(self) -> None:
        """Проверяет, что to ddl orders known clauses and keeps other options."""
        table = TableDDL.from_ddl(COMPLEX_DDL)
        rendered = table.to_ddl()

        engine_pos = rendered.index("\nENGINE = ")
        partition_pos = rendered.index("\nPARTITION BY ")
        pk_pos = rendered.index("\nPRIMARY KEY ")
        order_pos = rendered.index("\nORDER BY ")
        sample_pos = rendered.index("\nSAMPLE BY ")
        ttl_pos = rendered.index("\nTTL ")
        settings_pos = rendered.index("\nSETTINGS ")
        comment_pos = rendered.index("\nCOMMENT ")

        self.assertLess(engine_pos, partition_pos)
        self.assertLess(partition_pos, pk_pos)
        self.assertLess(pk_pos, order_pos)
        self.assertLess(order_pos, sample_pos)
        self.assertLess(sample_pos, ttl_pos)
        self.assertLess(ttl_pos, settings_pos)
        self.assertLess(settings_pos, comment_pos)

    def test_column_and_index_lookup_return_none_when_missing(self) -> None:
        """Проверяет, что column and index lookup return none when missing."""
        table = TableDDL.from_ddl(DDL)
        self.assertIsNone(table.column("missing_col"))
        self.assertIsNone(table.index("missing_idx"))

    def test_to_ddl_omits_codec_when_column_codec_is_none(self) -> None:
        """Проверяет, что to ddl omits codec when column codec is none."""
        table = TableDDL.from_ddl(DDL)
        table.column("user_id").codec = None

        rendered = table.to_ddl()
        self.assertIn("`user_id` UInt64", rendered)
        self.assertNotIn("`user_id` UInt64 CODEC", rendered)

    def test_from_ddl_raises_on_non_create_table_statement(self) -> None:
        """Проверяет, что from ddl raises on non create table statement."""
        with self.assertRaises(ValueError):
            TableDDL.from_ddl("SELECT 1")

    def test_from_ddl_raises_on_unbalanced_parentheses(self) -> None:
        """Проверяет, что from ddl raises on unbalanced parentheses."""
        bad_ddl = """
        CREATE TABLE analytics.bad
        (
            `x` Array(UInt8)
        ENGINE = MergeTree
        ORDER BY tuple()
        """
        with self.assertRaises(ValueError):
            TableDDL.from_ddl(bad_ddl)


if __name__ == "__main__":
    unittest.main()
