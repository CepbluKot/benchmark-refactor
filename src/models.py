"""
Pydantic-модели JSON-конфига бенчмарка.

Этот модуль описывает весь контракт входной конфигурации:
  - источники подключений к СУБД;
  - правила генерации DDL-вариантов (банки и inline override);
  - селекторы БД/таблиц;
  - параметры выполнения бенчмарка и Celery.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


BenchmarkMode = Literal["types", "indexes", "sequential", "combined"]
ColumnOrderMode = Literal["compressed_size_desc"]
DatabasesSelector = Union[Literal["*"], List[str]]
TableListSelector = Union[Literal["*"], List[str]]
TablesSelector = Union[Literal["*"], List[str], Dict[str, TableListSelector]]


class _Base(BaseModel):
    """Базовая модель конфига: запрещает неизвестные поля."""

    model_config = {"extra": "forbid"}


class ColumnRuleConfig(_Base):
    """
    JSON-описание одного правила для подбора альтернатив колонок.

    Используется в `rule_banks` и в inline `rules.column_rules`.
    """

    by_type: Optional[str] = None
    by_name: Optional[str] = None
    types: List[str] = Field(default_factory=list)
    codecs: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_matchers(self) -> "ColumnRuleConfig":
        """
        Валидирует корректность матчинга.

        Правило должно быть привязано минимум к типу колонки;
        `by_name` без `by_type` запрещён, чтобы избежать слишком широких совпадений.
        """
        if self.by_name is None and self.by_type is None:
            raise ValueError("нужно задать хотя бы by_type или by_name")
        if self.by_name is not None and self.by_type is None:
            raise ValueError(
                f"by_name={self.by_name!r} задан без by_type — укажи тип колонки явно"
            )
        return self


class IndexConfig(_Base):
    """Конфигурация одного skip-индекса (тип + гранулярность)."""

    type: str
    granularity: int = Field(default=1, ge=1)


class IndexRuleConfig(_Base):
    """
    JSON-описание правила генерации индексных вариантов для колонки.

    Аналог `ColumnRuleConfig`, но вместо type/codec управляет набором индексов.
    """

    by_type: Optional[str] = None
    by_name: Optional[str] = None
    indexes: List[IndexConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_matchers(self) -> "IndexRuleConfig":
        """Проверяет, что правило содержит валидный набор матчеров."""
        if self.by_name is None and self.by_type is None:
            raise ValueError("нужно задать хотя бы by_type или by_name")
        if self.by_name is not None and self.by_type is None:
            raise ValueError(
                f"by_name={self.by_name!r} задан без by_type — укажи тип колонки явно"
            )
        return self


class RuleBankConfig(_Base):
    """
    Именованный банк правил.

    Банк можно переиспользовать в нескольких бенчмарках через `rules.rule_bank`.
    """

    column_rules: List[ColumnRuleConfig] = Field(default_factory=list)
    index_rules: List[IndexRuleConfig] = Field(default_factory=list)
    column_order: Dict[str, int] = Field(default_factory=dict)


class RulesConfig(_Base):
    """
    Универсальный контейнер правил для global/table-level настроек.

    Поддерживает два источника:
      1) ссылка на `rule_bank`;
      2) inline-переопределения (`column_rules`, `index_rules`, `column_order`).
    """

    rule_bank: Optional[str] = None
    column_rules: Optional[List[ColumnRuleConfig]] = None
    index_rules: Optional[List[IndexRuleConfig]] = None
    column_order: Optional[Dict[str, int]] = None

    def has_inline_overrides(self) -> bool:
        """True, если задано хотя бы одно inline-поле поверх банка."""
        return any(
            value is not None
            for value in (self.column_rules, self.index_rules, self.column_order)
        )

    def is_empty(self) -> bool:
        """True, если правила полностью отсутствуют (ни банка, ни inline override)."""
        return self.rule_bank is None and not self.has_inline_overrides()

    def merged_over(self, base: "RulesConfig") -> "RulesConfig":
        """
        Строит объединение `self` поверх `base`.

        Используется для merge глобальных и локальных правил:
        каждое поле локального блока перезаписывает одноимённое глобальное.
        """
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
    """Конфигурация одного тестового SQL-запроса и его веса в scoring."""

    query: str
    weight: float = Field(default=1.0, gt=0)


class QueriesConfig(_Base):
    """
    Настройки генерации/выбора query-плана для замеров.

    Режимы:
      - auto: автогенерированные запросы;
      - manual: только пользовательские;
      - auto_with_manual: объединение обоих наборов.
    """

    mode: Literal["auto", "manual", "auto_with_manual"] = "auto"
    warmup_queries: List[str] = Field(default_factory=list)
    test_queries: List[TestQueryConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_manual_has_queries(self) -> "QueriesConfig":
        """Гарантирует, что `manual` режим не запущен с пустым списком запросов."""
        if self.mode == "manual" and not self.test_queries:
            raise ValueError("mode=manual требует хотя бы одного test_query")
        return self


class CeleryConfig(_Base):
    """Параметры запуска Celery-воркеров для бенчмарк-джоб."""

    workers: int = Field(default=4, gt=0)
    threads_per_worker: int = Field(default=2, gt=0)


class TableRuleConfig(_Base):
    """
    Локальные override для конкретной таблицы `database.table`.

    Может переопределять:
      - rules;
      - column_order_mode;
      - max_iterations;
      - sequential_top_n;
      - mode;
      - queries.
    """

    database: str
    table: str
    rules: RulesConfig = Field(default_factory=RulesConfig)
    column_order_mode: Optional[ColumnOrderMode] = None
    queries: Optional[QueriesConfig] = None
    max_iterations: Optional[int] = Field(default=None, gt=0)
    sequential_top_n: Optional[int] = Field(default=None, gt=0)
    mode: Optional[BenchmarkMode] = None

    @field_validator("database", "table")
    @classmethod
    def non_empty_table_target(cls, value: str) -> str:
        """Проверяет, что имя БД/таблицы не пустое после trim."""
        value = value.strip()
        if not value:
            raise ValueError("database/table не должны быть пустыми")
        return value


class ConnectionConfig(_Base):
    """Параметры подключения к конкретной СУБД для запуска бенчмарка."""

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
        """Нормализует текстовые токены до lower-case без пробелов по краям."""
        token = value.strip().lower()
        if not token:
            raise ValueError("значение не должно быть пустым")
        return token


class BenchmarkConfig(_Base):
    """
    Конфигурация одного логического бенчмарка.

    Описывает:
      - какое подключение использовать (`connection_id`);
      - какие БД/таблицы включить;
      - глобальные правила и table-level override;
      - режим вычисления `column_order` (опционально);
      - ограничение по итерациям и режим комбинатора.
      - `sequential_top_n` для двухфазного режима sequential.
    """

    id: str
    connection_id: str
    mode: BenchmarkMode
    global_rules: RulesConfig = Field(default_factory=RulesConfig)
    column_order_mode: Optional[ColumnOrderMode] = None

    databases: DatabasesSelector = "*"
    tables: TablesSelector = "*"

    max_iterations: int = Field(default=100, gt=0)
    sequential_top_n: int = Field(default=1, gt=0)
    queries: QueriesConfig = Field(default_factory=QueriesConfig)
    table_rules: List[TableRuleConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_selectors(self) -> "BenchmarkConfig":
        """
        Проверяет валидность селекторов databases/tables и table_rules.

        Цель: отловить ошибки до этапа планирования (пустые списки, лишние БД, дубликаты).
        """
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
    """
    Корневая конфигурация, с которой работает planner/engine.

    Это уже собранный и валидированный объект после загрузки project-конфига.
    """

    connections: List[ConnectionConfig]
    benchmarks: List[BenchmarkConfig]
    rule_banks: Dict[str, RuleBankConfig] = Field(default_factory=dict)
    default_rule_banks: Dict[str, str] = Field(default_factory=dict)
    celery: CeleryConfig = Field(default_factory=CeleryConfig)

    @field_validator("default_rule_banks")
    @classmethod
    def normalize_default_rule_banks(cls, value: Dict[str, str]) -> Dict[str, str]:
        """Нормализует ключи DBMS в lower-case для предсказуемого lookup."""
        return {dbms.strip().lower(): bank_id for dbms, bank_id in value.items()}

    @model_validator(mode="after")
    def validate_uniqueness(self) -> "BenchmarkRootConfig":
        """Проверяет уникальность id у connections и benchmarks."""
        connection_ids = [c.id for c in self.connections]
        if len(connection_ids) != len(set(connection_ids)):
            raise ValueError("connections содержит дублирующиеся id")

        benchmark_ids = [b.id for b in self.benchmarks]
        if len(benchmark_ids) != len(set(benchmark_ids)):
            raise ValueError("benchmarks содержит дублирующиеся id")

        return self


class ConnectionsFileConfig(_Base):
    """Структура файла `connections.json` в project-режиме."""

    connections: List[ConnectionConfig]

    @model_validator(mode="after")
    def validate_non_empty(self) -> "ConnectionsFileConfig":
        """Запрещает пустой файл подключений."""
        if not self.connections:
            raise ValueError("connections файл не должен быть пустым")
        return self


class RuleBanksFileConfig(_Base):
    """Структура файла `rule_banks.json` в project-режиме."""

    rule_banks: Dict[str, RuleBankConfig] = Field(default_factory=dict)
    default_rule_banks: Dict[str, str] = Field(default_factory=dict)

    @field_validator("default_rule_banks")
    @classmethod
    def normalize_default_rule_banks(cls, value: Dict[str, str]) -> Dict[str, str]:
        """Нормализует DBMS-ключи до lower-case."""
        return {dbms.strip().lower(): bank_id for dbms, bank_id in value.items()}


class BenchmarksFileConfig(_Base):
    """Структура файла `benchmarks.json` в project-режиме."""

    benchmarks: List[BenchmarkConfig]

    @model_validator(mode="after")
    def validate_non_empty(self) -> "BenchmarksFileConfig":
        """Запрещает пустой список бенчмарков в отдельном файле."""
        if not self.benchmarks:
            raise ValueError("benchmarks файл не должен быть пустым")
        return self


class BenchmarkProjectConfig(_Base):
    """
    "Лёгкий" проектный конфиг-обёртка.

    Идея: крупные секции (`connections`, `rule_banks`, иногда `benchmarks`)
    хранятся в отдельных JSON-файлах и склеиваются `loader.ConfigLoader`.
    """

    connections_file: str
    rule_banks_file: str
    benchmarks: Optional[List[BenchmarkConfig]] = None
    benchmarks_file: Optional[str] = None
    celery: CeleryConfig = Field(default_factory=CeleryConfig)

    @field_validator("connections_file", "rule_banks_file", "benchmarks_file")
    @classmethod
    def normalize_file_refs(cls, value: Optional[str]) -> Optional[str]:
        """Нормализует строки путей и отсекает пустые значения."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("путь к файлу не должен быть пустым")
        return cleaned

    @model_validator(mode="after")
    def validate_benchmarks_source(self) -> "BenchmarkProjectConfig":
        """Требует ровно один источник `benchmarks`: inline или файл."""
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
