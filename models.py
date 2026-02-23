"""Pydantic v2 модели JSON-конфига бенчмарка."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


BenchmarkMode = Literal["types", "indexes", "sequential", "combined"]
DatabasesSelector = Union[Literal["*"], List[str]]
TableListSelector = Union[Literal["*"], List[str]]
TablesSelector = Union[Literal["*"], List[str], Dict[str, TableListSelector]]


class _Base(BaseModel):
    model_config = {"extra": "forbid"}


class ColumnRuleConfig(_Base):
    by_type: Optional[str] = None
    by_name: Optional[str] = None
    types: List[str] = Field(default_factory=list)
    codecs: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_matchers(self) -> "ColumnRuleConfig":
        if self.by_name is None and self.by_type is None:
            raise ValueError("нужно задать хотя бы by_type или by_name")
        if self.by_name is not None and self.by_type is None:
            raise ValueError(
                f"by_name={self.by_name!r} задан без by_type — укажи тип колонки явно"
            )
        return self


class IndexConfig(_Base):
    type: str
    granularity: int = Field(default=1, ge=1)


class IndexRuleConfig(_Base):
    by_type: Optional[str] = None
    by_name: Optional[str] = None
    indexes: List[IndexConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_matchers(self) -> "IndexRuleConfig":
        if self.by_name is None and self.by_type is None:
            raise ValueError("нужно задать хотя бы by_type или by_name")
        if self.by_name is not None and self.by_type is None:
            raise ValueError(
                f"by_name={self.by_name!r} задан без by_type — укажи тип колонки явно"
            )
        return self


class RuleBankConfig(_Base):
    column_rules: List[ColumnRuleConfig] = Field(default_factory=list)
    index_rules: List[IndexRuleConfig] = Field(default_factory=list)
    column_order: Dict[str, int] = Field(default_factory=dict)


class RulesConfig(_Base):
    rule_bank: Optional[str] = None
    column_rules: Optional[List[ColumnRuleConfig]] = None
    index_rules: Optional[List[IndexRuleConfig]] = None
    column_order: Optional[Dict[str, int]] = None

    def has_inline_overrides(self) -> bool:
        return any(
            value is not None
            for value in (self.column_rules, self.index_rules, self.column_order)
        )

    def is_empty(self) -> bool:
        return self.rule_bank is None and not self.has_inline_overrides()

    def merged_over(self, base: "RulesConfig") -> "RulesConfig":
        merged = RulesConfig(
            rule_bank=self.rule_bank if self.rule_bank is not None else base.rule_bank,
            column_rules=(
                self.column_rules if self.column_rules is not None else base.column_rules
            ),
            index_rules=(
                self.index_rules if self.index_rules is not None else base.index_rules
            ),
            column_order=(
                self.column_order if self.column_order is not None else base.column_order
            ),
        )
        return merged.model_copy(deep=True)


class TestQueryConfig(_Base):
    query: str
    weight: float = Field(default=1.0, gt=0)


class QueriesConfig(_Base):
    mode: Literal["auto", "manual", "auto_with_manual"] = "auto"
    warmup_queries: List[str] = Field(default_factory=list)
    test_queries: List[TestQueryConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_manual_has_queries(self) -> "QueriesConfig":
        if self.mode == "manual" and not self.test_queries:
            raise ValueError("mode=manual требует хотя бы одного test_query")
        return self


class CeleryConfig(_Base):
    workers: int = Field(default=4, gt=0)
    threads_per_worker: int = Field(default=2, gt=0)


class TableRuleConfig(_Base):
    database: str
    table: str
    rules: RulesConfig = Field(default_factory=RulesConfig)
    queries: Optional[QueriesConfig] = None
    max_iterations: Optional[int] = Field(default=None, gt=0)
    mode: Optional[BenchmarkMode] = None

    @field_validator("database", "table")
    @classmethod
    def non_empty_table_target(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("database/table не должны быть пустыми")
        return value


class ConnectionConfig(_Base):
    id: str
    dbms: str = "clickhouse"
    credential_type: str = "password"
    host: str
    port: int = Field(gt=0, lt=65536)
    login: str
    password: str

    @field_validator("dbms", "credential_type")
    @classmethod
    def normalize_tokens(cls, value: str) -> str:
        token = value.strip().lower()
        if not token:
            raise ValueError("значение не должно быть пустым")
        return token


class BenchmarkConfig(_Base):
    id: str
    connection_id: str
    mode: BenchmarkMode
    global_rules: RulesConfig = Field(default_factory=RulesConfig)

    databases: DatabasesSelector = "*"
    tables: TablesSelector = "*"

    max_iterations: int = Field(default=100, gt=0)
    queries: QueriesConfig = Field(default_factory=QueriesConfig)
    table_rules: List[TableRuleConfig] = Field(default_factory=list)
    celery: Optional[CeleryConfig] = None

    @model_validator(mode="after")
    def validate_selectors(self) -> "BenchmarkConfig":
        if isinstance(self.databases, list) and not self.databases:
            raise ValueError("databases не может быть пустым списком")

        if isinstance(self.tables, list) and not self.tables:
            raise ValueError("tables не может быть пустым списком")

        if isinstance(self.tables, dict):
            if not self.tables:
                raise ValueError("tables map не может быть пустым")
            if isinstance(self.databases, list):
                extra_db_keys = sorted(set(self.tables.keys()) - set(self.databases))
                if extra_db_keys:
                    raise ValueError(
                        "tables содержит БД вне databases: " + ", ".join(extra_db_keys)
                    )
            for db_name, table_selector in self.tables.items():
                if isinstance(table_selector, list) and not table_selector:
                    raise ValueError(
                        f"tables[{db_name!r}] не может быть пустым списком"
                    )

        seen = set()
        for tr in self.table_rules:
            key = (tr.database, tr.table)
            if key in seen:
                raise ValueError(
                    f"table_rules содержит дубликат для {tr.database}.{tr.table}"
                )
            seen.add(key)
        return self


class BenchmarkRootConfig(_Base):
    connections: List[ConnectionConfig]
    benchmarks: List[BenchmarkConfig]
    rule_banks: Dict[str, RuleBankConfig] = Field(default_factory=dict)
    default_rule_banks: Dict[str, str] = Field(default_factory=dict)
    celery: CeleryConfig = Field(default_factory=CeleryConfig)

    @field_validator("default_rule_banks")
    @classmethod
    def normalize_default_rule_banks(cls, value: Dict[str, str]) -> Dict[str, str]:
        return {dbms.strip().lower(): bank_id for dbms, bank_id in value.items()}

    @model_validator(mode="after")
    def validate_uniqueness(self) -> "BenchmarkRootConfig":
        connection_ids = [c.id for c in self.connections]
        if len(connection_ids) != len(set(connection_ids)):
            raise ValueError("connections содержит дублирующиеся id")

        benchmark_ids = [b.id for b in self.benchmarks]
        if len(benchmark_ids) != len(set(benchmark_ids)):
            raise ValueError("benchmarks содержит дублирующиеся id")

        return self


class ConnectionsFileConfig(_Base):
    connections: List[ConnectionConfig]

    @model_validator(mode="after")
    def validate_non_empty(self) -> "ConnectionsFileConfig":
        if not self.connections:
            raise ValueError("connections файл не должен быть пустым")
        return self


class RuleBanksFileConfig(_Base):
    rule_banks: Dict[str, RuleBankConfig] = Field(default_factory=dict)
    default_rule_banks: Dict[str, str] = Field(default_factory=dict)

    @field_validator("default_rule_banks")
    @classmethod
    def normalize_default_rule_banks(cls, value: Dict[str, str]) -> Dict[str, str]:
        return {dbms.strip().lower(): bank_id for dbms, bank_id in value.items()}


class BenchmarksFileConfig(_Base):
    benchmarks: List[BenchmarkConfig]

    @model_validator(mode="after")
    def validate_non_empty(self) -> "BenchmarksFileConfig":
        if not self.benchmarks:
            raise ValueError("benchmarks файл не должен быть пустым")
        return self


class BenchmarkProjectConfig(_Base):
    """
    Проектный конфиг: тяжелые секции лежат в отдельных JSON-файлах.
    """

    connections_file: str
    rule_banks_file: str
    benchmarks: Optional[List[BenchmarkConfig]] = None
    benchmarks_file: Optional[str] = None
    celery: CeleryConfig = Field(default_factory=CeleryConfig)

    @field_validator("connections_file", "rule_banks_file", "benchmarks_file")
    @classmethod
    def normalize_file_refs(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("путь к файлу не должен быть пустым")
        return cleaned

    @model_validator(mode="after")
    def validate_benchmarks_source(self) -> "BenchmarkProjectConfig":
        has_inline = self.benchmarks is not None
        has_file = self.benchmarks_file is not None
        if has_inline == has_file:
            raise ValueError(
                "нужно указать ровно один источник benchmarks: "
                "benchmarks (inline) или benchmarks_file"
            )
        if self.benchmarks is not None and not self.benchmarks:
            raise ValueError("benchmarks не может быть пустым")
        return self
