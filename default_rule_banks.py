"""Встроенные наборы правил по типу СУБД."""

from __future__ import annotations

from typing import Dict

from models import (
    ColumnRuleConfig,
    IndexConfig,
    IndexRuleConfig,
    RuleBankConfig,
)


CLICKHOUSE_DEFAULT_RULE_BANK = RuleBankConfig(
    column_order={"event_time": 1, "user_id": 2},
    column_rules=[
        ColumnRuleConfig(
            by_type="UInt64",
            types=["UInt64", "UInt32"],
            codecs=["CODEC(Delta(8), LZ4)", "CODEC(T64, ZSTD(1))"],
        ),
        ColumnRuleConfig(
            by_type="UInt32",
            types=["UInt32", "UInt16"],
            codecs=["CODEC(Delta(4), LZ4)", "CODEC(T64, ZSTD(1))"],
        ),
        ColumnRuleConfig(
            by_type="DateTime",
            codecs=["CODEC(DoubleDelta, LZ4)", "CODEC(DoubleDelta, ZSTD(1))"],
        ),
        ColumnRuleConfig(
            by_type="LowCardinality",
            codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
        ),
        ColumnRuleConfig(
            by_type="Nullable",
            codecs=["CODEC(ZSTD(1))", "CODEC(ZSTD(3))"],
        ),
    ],
    index_rules=[
        IndexRuleConfig(
            by_type="UInt64",
            indexes=[
                IndexConfig(type="minmax", granularity=4),
                IndexConfig(type="bloom_filter(0.01)", granularity=2),
            ],
        ),
        IndexRuleConfig(
            by_type="DateTime",
            indexes=[IndexConfig(type="minmax", granularity=4)],
        ),
        IndexRuleConfig(
            by_type="LowCardinality",
            indexes=[
                IndexConfig(type="set(200)", granularity=4),
                IndexConfig(type="bloom_filter(0.01)", granularity=2),
            ],
        ),
    ],
)


BUILTIN_RULE_BANKS_BY_DBMS: Dict[str, RuleBankConfig] = {
    "clickhouse": CLICKHOUSE_DEFAULT_RULE_BANK
}

