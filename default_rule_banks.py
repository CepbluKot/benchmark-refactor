"""Встроенные baseline-наборы правил по типу СУБД."""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

from models import (
    ColumnRuleConfig,
    IndexConfig,
    IndexRuleConfig,
    RuleBankConfig,
)


def _column_rule(
    by_type: str,
    *,
    types: Sequence[str] = (),
    codecs: Sequence[str] = (),
) -> ColumnRuleConfig:
    """Собирает `ColumnRuleConfig` с общим паттерном заполнения списков."""
    return ColumnRuleConfig(
        by_type=by_type,
        types=list(types),
        codecs=list(codecs),
    )


def _index_rule(
    by_type: str,
    indexes: Iterable[Tuple[str, int]],
) -> IndexRuleConfig:
    """Собирает `IndexRuleConfig` из списка `(index_type, granularity)`."""
    return IndexRuleConfig(
        by_type=by_type,
        indexes=[
            IndexConfig(type=index_type, granularity=granularity)
            for index_type, granularity in indexes
        ],
    )


# Универсальный baseline-блок: только by_type, без by_name.
# Важно: by_type матчится строго по полной строке типа.
CLICKHOUSE_BASELINE_COLUMN_RULES: List[ColumnRuleConfig] = [
    # Unsigned integers
    _column_rule(
        "UInt8",
        types=["UInt8"],
        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
    ),
    _column_rule(
        "UInt16",
        types=["UInt16", "UInt8"],
        codecs=[
            "CODEC(Delta(2), LZ4)",
            "CODEC(Delta(2), ZSTD(1))",
            "CODEC(T64, ZSTD(1))",
        ],
    ),
    _column_rule(
        "UInt32",
        types=["UInt32", "UInt16"],
        codecs=[
            "CODEC(Delta(4), LZ4)",
            "CODEC(Delta(4), ZSTD(1))",
            "CODEC(T64, ZSTD(1))",
        ],
    ),
    _column_rule(
        "UInt64",
        types=["UInt64", "UInt32"],
        codecs=[
            "CODEC(Delta(8), LZ4)",
            "CODEC(Delta(8), ZSTD(1))",
            "CODEC(T64, ZSTD(1))",
        ],
    ),
    # Signed integers
    _column_rule(
        "Int8",
        types=["Int8"],
        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
    ),
    _column_rule(
        "Int16",
        types=["Int16", "Int8"],
        codecs=[
            "CODEC(Delta(2), LZ4)",
            "CODEC(Delta(2), ZSTD(1))",
            "CODEC(T64, ZSTD(1))",
        ],
    ),
    _column_rule(
        "Int32",
        types=["Int32", "Int16"],
        codecs=[
            "CODEC(Delta(4), LZ4)",
            "CODEC(Delta(4), ZSTD(1))",
            "CODEC(T64, ZSTD(1))",
        ],
    ),
    _column_rule(
        "Int64",
        types=["Int64", "Int32"],
        codecs=[
            "CODEC(Delta(8), LZ4)",
            "CODEC(Delta(8), ZSTD(1))",
            "CODEC(T64, ZSTD(1))",
        ],
    ),
    # Floating point
    _column_rule(
        "Float32",
        types=["Float32"],
        codecs=[
            "CODEC(Gorilla, LZ4)",
            "CODEC(Gorilla, ZSTD(1))",
            "CODEC(ZSTD(1))",
        ],
    ),
    _column_rule(
        "Float64",
        types=["Float64", "Float32"],
        codecs=[
            "CODEC(Gorilla, LZ4)",
            "CODEC(Gorilla, ZSTD(1))",
            "CODEC(ZSTD(1))",
        ],
    ),
    # Date / time
    _column_rule(
        "Date",
        types=["Date"],
        codecs=["CODEC(Delta(2), LZ4)", "CODEC(Delta(2), ZSTD(1))"],
    ),
    _column_rule(
        "Date32",
        types=["Date32", "Date"],
        codecs=["CODEC(Delta(4), LZ4)", "CODEC(Delta(4), ZSTD(1))"],
    ),
    _column_rule(
        "DateTime",
        types=["DateTime"],
        codecs=["CODEC(DoubleDelta, LZ4)", "CODEC(DoubleDelta, ZSTD(1))"],
    ),
    _column_rule(
        "DateTime64(3)",
        types=["DateTime64(3)", "DateTime"],
        codecs=["CODEC(DoubleDelta, LZ4)", "CODEC(DoubleDelta, ZSTD(1))"],
    ),
    _column_rule(
        "DateTime64(6)",
        types=["DateTime64(6)", "DateTime64(3)", "DateTime"],
        codecs=["CODEC(DoubleDelta, LZ4)", "CODEC(DoubleDelta, ZSTD(1))"],
    ),
    # Text / categorical
    _column_rule(
        "String",
        types=["String", "LowCardinality(String)"],
        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))", "CODEC(ZSTD(3))"],
    ),
    _column_rule(
        "FixedString(16)",
        types=["FixedString(16)", "String"],
        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
    ),
    _column_rule(
        "FixedString(32)",
        types=["FixedString(32)", "String"],
        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
    ),
    _column_rule(
        "LowCardinality(String)",
        types=["LowCardinality(String)", "String"],
        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))", "CODEC(ZSTD(3))"],
    ),
    _column_rule(
        "LowCardinality(FixedString(2))",
        types=["LowCardinality(FixedString(2))", "FixedString(2)"],
        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
    ),
    _column_rule(
        "LowCardinality(FixedString(3))",
        types=["LowCardinality(FixedString(3))", "FixedString(3)"],
        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
    ),
    _column_rule(
        "LowCardinality(UInt8)",
        types=["LowCardinality(UInt8)", "UInt8"],
        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
    ),
    _column_rule(
        "LowCardinality(UInt16)",
        types=["LowCardinality(UInt16)", "UInt16"],
        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
    ),
    _column_rule(
        "LowCardinality(UInt32)",
        types=["LowCardinality(UInt32)", "UInt32"],
        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
    ),
    _column_rule(
        "LowCardinality(UInt64)",
        types=["LowCardinality(UInt64)", "UInt64"],
        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
    ),
    # Decimal
    _column_rule(
        "Decimal(9,2)",
        types=["Decimal(9,2)"],
        codecs=["CODEC(T64, ZSTD(1))", "CODEC(ZSTD(1))"],
    ),
    _column_rule(
        "Decimal(12,2)",
        types=["Decimal(12,2)", "Decimal(9,2)"],
        codecs=["CODEC(T64, ZSTD(1))", "CODEC(ZSTD(1))"],
    ),
    _column_rule(
        "Decimal(18,2)",
        types=["Decimal(18,2)", "Decimal(12,2)"],
        codecs=["CODEC(T64, ZSTD(1))", "CODEC(ZSTD(1))"],
    ),
    _column_rule(
        "Decimal(18,4)",
        types=["Decimal(18,4)", "Decimal(12,2)"],
        codecs=["CODEC(T64, ZSTD(1))", "CODEC(ZSTD(1))"],
    ),
    _column_rule(
        "Decimal(38,9)",
        types=["Decimal(38,9)", "Decimal(18,4)"],
        codecs=["CODEC(T64, ZSTD(1))", "CODEC(ZSTD(1))"],
    ),
    # Misc
    _column_rule("Bool", types=["Bool", "UInt8"], codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"]),
    _column_rule("UUID", types=["UUID"], codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"]),
    _column_rule("IPv4", types=["IPv4"], codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"]),
    _column_rule("IPv6", types=["IPv6"], codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"]),
    # Nullable wrappers (строго по полному типу)
    _column_rule(
        "Nullable(UInt8)",
        types=["Nullable(UInt8)"],
        codecs=["CODEC(ZSTD(1))", "CODEC(ZSTD(3))"],
    ),
    _column_rule(
        "Nullable(UInt16)",
        types=["Nullable(UInt16)", "Nullable(UInt8)"],
        codecs=["CODEC(ZSTD(1))", "CODEC(ZSTD(3))"],
    ),
    _column_rule(
        "Nullable(UInt32)",
        types=["Nullable(UInt32)", "Nullable(UInt16)"],
        codecs=["CODEC(ZSTD(1))", "CODEC(ZSTD(3))"],
    ),
    _column_rule(
        "Nullable(UInt64)",
        types=["Nullable(UInt64)", "Nullable(UInt32)"],
        codecs=["CODEC(ZSTD(1))", "CODEC(ZSTD(3))"],
    ),
    _column_rule(
        "Nullable(Int32)",
        types=["Nullable(Int32)", "Nullable(Int16)"],
        codecs=["CODEC(ZSTD(1))", "CODEC(ZSTD(3))"],
    ),
    _column_rule(
        "Nullable(Int64)",
        types=["Nullable(Int64)", "Nullable(Int32)"],
        codecs=["CODEC(ZSTD(1))", "CODEC(ZSTD(3))"],
    ),
    _column_rule(
        "Nullable(Float64)",
        types=["Nullable(Float64)", "Nullable(Float32)"],
        codecs=["CODEC(ZSTD(1))", "CODEC(ZSTD(3))"],
    ),
    _column_rule(
        "Nullable(DateTime)",
        types=["Nullable(DateTime)"],
        codecs=["CODEC(DoubleDelta, ZSTD(1))"],
    ),
    _column_rule(
        "Nullable(DateTime64(3))",
        types=["Nullable(DateTime64(3))", "Nullable(DateTime)"],
        codecs=["CODEC(DoubleDelta, ZSTD(1))"],
    ),
    _column_rule(
        "Nullable(String)",
        types=["Nullable(String)", "Nullable(LowCardinality(String))"],
        codecs=["CODEC(ZSTD(1))", "CODEC(ZSTD(3))"],
    ),
    _column_rule(
        "Nullable(LowCardinality(String))",
        types=["Nullable(LowCardinality(String))", "Nullable(String)"],
        codecs=["CODEC(ZSTD(1))", "CODEC(ZSTD(3))"],
    ),
    _column_rule(
        "Nullable(Decimal(18,4))",
        types=["Nullable(Decimal(18,4))", "Nullable(Decimal(12,2))"],
        codecs=["CODEC(ZSTD(1))", "CODEC(ZSTD(3))"],
    ),
]


CLICKHOUSE_BASELINE_INDEX_RULES: List[IndexRuleConfig] = [
    # Integers / numeric
    _index_rule(
        "UInt8",
        indexes=[("minmax", 4), ("set(200)", 4), ("bloom_filter(0.01)", 2)],
    ),
    _index_rule(
        "UInt16",
        indexes=[("minmax", 4), ("set(200)", 4), ("bloom_filter(0.01)", 2)],
    ),
    _index_rule(
        "UInt32",
        indexes=[("minmax", 4), ("set(200)", 4), ("bloom_filter(0.01)", 2)],
    ),
    _index_rule(
        "UInt64",
        indexes=[("minmax", 4), ("set(200)", 4), ("bloom_filter(0.01)", 2)],
    ),
    _index_rule(
        "Int32",
        indexes=[("minmax", 4), ("set(200)", 4), ("bloom_filter(0.01)", 2)],
    ),
    _index_rule(
        "Int64",
        indexes=[("minmax", 4), ("set(200)", 4), ("bloom_filter(0.01)", 2)],
    ),
    _index_rule(
        "Float32",
        indexes=[("minmax", 4), ("bloom_filter(0.01)", 2)],
    ),
    _index_rule(
        "Float64",
        indexes=[("minmax", 4), ("bloom_filter(0.01)", 2)],
    ),
    _index_rule(
        "Decimal(18,4)",
        indexes=[("minmax", 4), ("bloom_filter(0.01)", 2)],
    ),
    # Date/time
    _index_rule("Date", indexes=[("minmax", 4)]),
    _index_rule("Date32", indexes=[("minmax", 4)]),
    _index_rule("DateTime", indexes=[("minmax", 4)]),
    _index_rule("DateTime64(3)", indexes=[("minmax", 4)]),
    _index_rule("DateTime64(6)", indexes=[("minmax", 4)]),
    # Text
    _index_rule(
        "String",
        indexes=[
            ("bloom_filter(0.01)", 2),
            ("tokenbf_v1(32768, 3, 0)", 1),
            ("ngrambf_v1(3, 256, 2, 0)", 1),
        ],
    ),
    _index_rule(
        "FixedString(16)",
        indexes=[("set(500)", 4), ("bloom_filter(0.01)", 2)],
    ),
    _index_rule(
        "FixedString(32)",
        indexes=[("set(500)", 4), ("bloom_filter(0.01)", 2)],
    ),
    _index_rule(
        "LowCardinality(String)",
        indexes=[("set(500)", 4), ("bloom_filter(0.01)", 2)],
    ),
    _index_rule(
        "LowCardinality(UInt32)",
        indexes=[("set(500)", 4), ("bloom_filter(0.01)", 2)],
    ),
    # Identifiers / network
    _index_rule("UUID", indexes=[("set(500)", 4), ("bloom_filter(0.01)", 2)]),
    _index_rule("IPv4", indexes=[("set(500)", 4), ("bloom_filter(0.01)", 2)]),
    _index_rule("IPv6", indexes=[("set(500)", 4), ("bloom_filter(0.01)", 2)]),
]


CLICKHOUSE_BASELINE_RULE_BANK = RuleBankConfig(
    column_order={},
    column_rules=CLICKHOUSE_BASELINE_COLUMN_RULES,
    index_rules=CLICKHOUSE_BASELINE_INDEX_RULES,
)

# Backward-compatible alias.
CLICKHOUSE_DEFAULT_RULE_BANK = CLICKHOUSE_BASELINE_RULE_BANK


BUILTIN_RULE_BANKS_BY_DBMS: Dict[str, RuleBankConfig] = {
    "clickhouse": CLICKHOUSE_BASELINE_RULE_BANK
}

