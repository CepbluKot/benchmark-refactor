"""
Pydantic-модели JSON-конфига бенчмарка.

Этот модуль описывает весь контракт входной конфигурации:
  - источники подключений к СУБД;
  - правила генерации DDL-вариантов (банки и inline override);
  - селекторы БД/таблиц;
  - параметры выполнения бенчмарка и Celery.
"""

from __future__ import annotations

import keyword
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator


BenchmarkMode = Literal["types", "indexes", "sequential", "combined"]
BenchmarkStrategy = Literal[
    "types_strategy",
    "indexes_strategy",
    "combined_strategy",
    "sequential_topn_strategy",
    "sequential_phased_topn_strategy",
]
SelectQueryCacheMode = Literal["warm", "cold"]
ScoringMode = Literal["expression"]
ScoreTopSelectionMode = Literal["max", "min"]
ColumnOrderMode = Literal["compressed_size_desc"]
RuleSourceMode = Literal[
    "global_bank_only",
    "global_bank_with_inline_priority",
    "inline_only",
]
DatabasesSelector = Union[Literal["*"], List[str]]
TableListSelector = Union[Literal["*"], List[str]]
TablesSelector = Union[Literal["*"], List[str], Dict[str, TableListSelector]]

DEFAULT_SCORE_EXPRESSION = (
    "pow("
    "safe_div(medians.source_insert_time_ms, medians.tested_insert_time_ms, 1.0) "
    "* safe_div(medians.source_select_time_ms, medians.tested_select_time_ms, 1.0) "
    "* safe_div(source_size_bytes, tested_size_bytes, 1.0), "
    "1 / 3)"
)


STRATEGY_TO_MODE: Dict[BenchmarkStrategy, BenchmarkMode] = {
    "types_strategy": "types",
    "indexes_strategy": "indexes",
    "combined_strategy": "combined",
    "sequential_topn_strategy": "sequential",
    "sequential_phased_topn_strategy": "sequential",
}


def _normalize_positive_int_sequence(values: Optional[List[int]]) -> Optional[List[int]]:
    """Нормализует список положительных int: trim/дедупликация с сохранением порядка."""
    if values is None:
        return None
    if not values:
        raise ValueError("список не должен быть пустым")
    normalized: list[int] = []
    seen: set[int] = set()
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("каждое значение должно быть целым числом > 0")
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


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
    auto_generate_alternatives: bool = False
    auto_compressions_datatype: Optional[str] = None

    @field_validator("auto_compressions_datatype")
    @classmethod
    def normalize_auto_compressions_datatype(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        """Нормализует hint datatype для legacy-автогенерации кодеков."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("auto_compressions_datatype не должен быть пустым")
        return cleaned

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
    """Конфигурация одного skip-индекса (тип + гранулярность/перебор гранулярностей)."""

    type: str
    granularity: int = Field(default=1, ge=1)
    granularity_values: Optional[List[int]] = Field(
        default=None,
        validation_alias=AliasChoices("granularity_values"),
        serialization_alias="granularity_values",
    )
    table_index_granularity_values: Optional[List[int]] = Field(
        default=None,
        validation_alias=AliasChoices("index_granularity_values"),
        serialization_alias="index_granularity_values",
    )

    @field_validator("table_index_granularity_values")
    @classmethod
    def normalize_table_index_granularity_values(
        cls,
        values: Optional[List[int]],
    ) -> Optional[List[int]]:
        """
        Проверяет список перебора `SETTINGS index_granularity` для одного индекса.

        Поддерживает конфиг вида:
          {"type": "...", "granularity": 2, "index_granularity_values": [8192, 16384]}.
        """
        return _normalize_positive_int_sequence(values)

    @field_validator("granularity_values")
    @classmethod
    def normalize_granularity_values(
        cls,
        values: Optional[List[int]],
    ) -> Optional[List[int]]:
        """
        Нормализует дополнительный перебор granularities для skip-индекса.

        Поддерживает конфиг вида:
          {"type": "...", "granularity_values": [1, 2, 4]}.
        """
        return _normalize_positive_int_sequence(values)

    @model_validator(mode="before")
    @classmethod
    def accept_granularity_array_in_granularity_field(
        cls,
        data: Any,
    ) -> Any:
        """
        Поддерживает запись `granularity` как массива.

        Пример:
          {"type": "minmax", "granularity": [1, 2, 4]}.
        """
        if not isinstance(data, dict):
            return data

        granularity = data.get("granularity")
        if not isinstance(granularity, list):
            return data
        if not granularity:
            raise ValueError("granularity как массив не должен быть пустым")

        normalized = dict(data)
        if normalized.get("granularity_values") is None:
            normalized["granularity_values"] = granularity
        normalized["granularity"] = granularity[0]
        return normalized

    @model_validator(mode="after")
    def synchronize_granularity_with_values(self) -> "IndexConfig":
        """
        Если задан `granularity_values`, базовый `granularity` синхронизируется
        с первым значением, чтобы сериализация и отладка были консистентными.
        """
        if self.granularity_values is not None:
            self.granularity = self.granularity_values[0]
        return self

    def iter_granularity_values(self) -> List[int]:
        """Возвращает эффективный список granularities для перебора индекса."""
        if self.granularity_values is not None:
            return list(self.granularity_values)
        return [self.granularity]


class IndexRuleConfig(_Base):
    """
    JSON-описание правила генерации индексных вариантов для колонки.

    Аналог `ColumnRuleConfig`, но вместо type/codec управляет набором индексов.
    """

    by_type: Optional[str] = None
    by_name: Optional[str] = None
    indexes: List[IndexConfig] = Field(default_factory=list)
    auto_generate_indexes: bool = False
    auto_indexes_datatype: Optional[str] = None

    @field_validator("auto_indexes_datatype")
    @classmethod
    def normalize_auto_indexes_datatype(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        """Нормализует hint datatype для авто-генерации индексов."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("auto_indexes_datatype не должен быть пустым")
        return cleaned

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


class CodecRuleConfig(_Base):
    """
    JSON-описание одного правила подбора только кодеков для колонки.

    Поддерживает автогенерацию кодеков по legacy-логике (через datatype hint).
    """

    by_type: Optional[str] = None
    by_name: Optional[str] = None
    codecs: List[str] = Field(default_factory=list)
    auto_generate_alternatives: bool = False
    auto_compressions_datatype: Optional[str] = None

    @field_validator("auto_compressions_datatype")
    @classmethod
    def normalize_auto_compressions_datatype(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        """Нормализует hint datatype для legacy-автогенерации кодеков."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("auto_compressions_datatype не должен быть пустым")
        return cleaned

    @model_validator(mode="after")
    def check_matchers(self) -> "CodecRuleConfig":
        """Валидирует матчеры как у column rule."""
        if self.by_name is None and self.by_type is None:
            raise ValueError("нужно задать хотя бы by_type или by_name")
        if self.by_name is not None and self.by_type is None:
            raise ValueError(
                f"by_name={self.by_name!r} задан без by_type — укажи тип колонки явно"
            )
        return self


class OrderByRulesConfig(_Base):
    """Правила генерации кандидатов ORDER BY для phased-стратегии."""

    first_column: Optional[str] = None
    candidates: Optional[List[str]] = None
    auto_generate_candidates: Optional[bool] = None

    @field_validator("first_column")
    @classmethod
    def non_empty_first_column(cls, value: Optional[str]) -> Optional[str]:
        """Проверяет, что first_column не пустой, если задан."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("order_by_rules.first_column не должен быть пустым")
        return cleaned

    @field_validator("candidates")
    @classmethod
    def normalize_candidates(
        cls,
        values: Optional[List[str]],
    ) -> Optional[List[str]]:
        """Нормализует и дедуплицирует order_by_rules.candidates."""
        if values is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            candidate = value.strip()
            if not candidate:
                raise ValueError(
                    "order_by_rules.candidates не должен содержать пустые значения"
                )
            if candidate in seen:
                continue
            seen.add(candidate)
            cleaned.append(candidate)
        if not cleaned:
            raise ValueError("order_by_rules.candidates не должен быть пустым")
        return cleaned

    def merged_over(self, base: Optional["OrderByRulesConfig"]) -> "OrderByRulesConfig":
        """Объединяет частичный inline override поверх базового блока."""
        if base is None:
            return self.model_copy(deep=True)
        return OrderByRulesConfig(
            first_column=(
                self.first_column if self.first_column is not None else base.first_column
            ),
            candidates=self.candidates if self.candidates is not None else base.candidates,
            auto_generate_candidates=(
                self.auto_generate_candidates
                if self.auto_generate_candidates is not None
                else base.auto_generate_candidates
            ),
        )


class RuleBankConfig(_Base):
    """
    Именованный банк правил.

    Банк можно переиспользовать в нескольких бенчмарках через `rules.rule_bank`.
    """

    column_rules: List[ColumnRuleConfig] = Field(default_factory=list)
    codec_rules: List[CodecRuleConfig] = Field(default_factory=list)
    index_rules: List[IndexRuleConfig] = Field(default_factory=list)
    order_by_rules: Optional[OrderByRulesConfig] = None
    column_order: Dict[str, int] = Field(default_factory=dict)


class RulesConfig(_Base):
    """
    Универсальный контейнер правил для global/table-level настроек.

    Поддерживает два источника:
      1) ссылка на `rule_bank`;
      2) inline-переопределения
         (`column_rules`, `codec_rules`, `index_rules`, `order_by_rules`, `column_order`).
    """

    rule_bank: Optional[str] = None
    column_rules: Optional[List[ColumnRuleConfig]] = None
    codec_rules: Optional[List[CodecRuleConfig]] = None
    index_rules: Optional[List[IndexRuleConfig]] = None
    order_by_rules: Optional[OrderByRulesConfig] = None
    column_order: Optional[Dict[str, int]] = None

    def has_inline_overrides(self) -> bool:
        """True, если задано хотя бы одно inline-поле поверх банка."""
        return any(
            value is not None
            for value in (
                self.column_rules,
                self.codec_rules,
                self.index_rules,
                self.order_by_rules,
                self.column_order,
            )
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
            codec_rules=(
                self.codec_rules if self.codec_rules is not None else base.codec_rules
            ),
            index_rules=(
                self.index_rules if self.index_rules is not None else base.index_rules
            ),
            order_by_rules=(
                self.order_by_rules
                if self.order_by_rules is not None
                else base.order_by_rules
            ),
            column_order=(
                self.column_order if self.column_order is not None else base.column_order
            ),
        )
        return merged.model_copy(deep=True)


class TestQueryConfig(_Base):
    """Конфигурация одного тестового SQL-запроса."""

    query_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("query_id"),
        serialization_alias="query_id",
    )
    query: str
    query_type: Literal["hit", "miss", "manual", "generic"] = "manual"
    cache_mode: SelectQueryCacheMode = "warm"
    select_operations_count: int = Field(default=1, gt=0)
    warmup_queries: List[str] = Field(default_factory=list)

    @field_validator("query_id")
    @classmethod
    def normalize_query_id(cls, value: Optional[str]) -> Optional[str]:
        """Нормализует query_id и запрещает пустой id."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query_id не должен быть пустым")
        return cleaned

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        """Нормализует SQL-запрос и запрещает пустую строку."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query не должен быть пустым")
        return cleaned

    @model_validator(mode="after")
    def validate_cache_mode_config(self) -> "TestQueryConfig":
        """
        Проверяет согласованность cache_mode и warmup-настроек.

        Для `cold` query-level warmup не применяется, поэтому такой конфиг запрещён.
        """
        if self.cache_mode == "cold" and self.warmup_queries:
            raise ValueError(
                "warmup_queries нельзя задавать для query с cache_mode=cold"
            )
        return self


class QueriesConfig(_Base):
    """
    Настройки генерации/выбора query-плана для замеров.

    Режимы:
      - auto: автогенерированные запросы;
      - manual: только пользовательские;
      - auto_with_manual: объединение обоих наборов.
    """

    mode: Literal["auto", "manual", "auto_with_manual"] = "auto"
    test_queries: List[TestQueryConfig] = Field(default_factory=list)
    auto_like_on_measured_columns: bool = Field(
        default=False,
        validation_alias=AliasChoices("auto_like_on_measured_columns"),
        serialization_alias="auto_like_on_measured_columns",
    )
    auto_like_replace_default_auto_queries: bool = Field(
        default=False,
        validation_alias=AliasChoices("auto_like_replace_default_auto_queries"),
        serialization_alias="auto_like_replace_default_auto_queries",
    )
    auto_like_sample_rows_per_column: int = Field(
        default=20,
        gt=0,
        validation_alias=AliasChoices("auto_like_sample_rows_per_column"),
        serialization_alias="auto_like_sample_rows_per_column",
    )
    auto_select_limit: int = Field(
        default=10,
        gt=0,
        validation_alias=AliasChoices("auto_select_limit"),
        serialization_alias="auto_select_limit",
    )
    auto_like_min_token_length: int = Field(
        default=3,
        gt=0,
        validation_alias=AliasChoices("auto_like_min_token_length"),
        serialization_alias="auto_like_min_token_length",
    )
    auto_like_max_token_length: int = Field(
        default=24,
        gt=0,
        validation_alias=AliasChoices("auto_like_max_token_length"),
        serialization_alias="auto_like_max_token_length",
    )

    @model_validator(mode="after")
    def check_manual_has_queries(self) -> "QueriesConfig":
        """Гарантирует, что `manual` режим не запущен с пустым списком запросов."""
        if self.mode == "manual" and not self.test_queries:
            raise ValueError("mode=manual требует хотя бы одного test_query")
        if self.auto_like_max_token_length < self.auto_like_min_token_length:
            raise ValueError(
                "auto_like_max_token_length должен быть >= auto_like_min_token_length"
            )
        seen_query_ids: set[str] = set()
        for query in self.test_queries:
            if query.query_id is None:
                continue
            if query.query_id in seen_query_ids:
                raise ValueError(
                    f"query_id={query.query_id!r} повторяется в test_queries"
                )
            seen_query_ids.add(query.query_id)
        return self


def _normalize_scoring_expression(
    value: Optional[str],
    *,
    field_path: str,
) -> Optional[str]:
    """Нормализует и валидирует текст scoring expression."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_path} не должен быть пустым")
    if len(cleaned) > 4000:
        raise ValueError(f"{field_path} слишком длинный (максимум 4000 символов)")
    return cleaned


def _validate_scoring_mode_and_expression(
    *,
    mode: ScoringMode,
    expression: Optional[str],
    field_path: str,
) -> None:
    """Проверяет согласованность пары scoring.mode/scoring.expression."""
    if mode != "expression":
        raise ValueError(f"{field_path}.mode поддерживает только значение expression")
    if expression is None:
        raise ValueError(f"{field_path}.mode=expression требует непустой {field_path}.expression")


def _normalize_scoring_variable_name(
    value: str,
    *,
    field_path: str,
) -> str:
    """Нормализует и валидирует имя переменной scoring."""
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError(f"{field_path} содержит пустое имя переменной")
    if not cleaned.isidentifier() or keyword.iskeyword(cleaned):
        raise ValueError(
            f"{field_path} содержит недопустимое имя переменной {cleaned!r}: "
            "используй валидный Python-идентификатор"
        )
    if cleaned.startswith("_"):
        raise ValueError(
            f"{field_path} содержит недопустимое имя переменной {cleaned!r}: "
            "имя не должно начинаться с '_'"
        )
    return cleaned


def _normalize_scoring_variables(
    value: Optional[Dict[str, str]],
    *,
    field_path: str,
) -> Optional[Dict[str, str]]:
    """Нормализует map переменных scoring: имя -> expression."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_path} должен быть объектом")
    normalized: dict[str, str] = {}
    for raw_name, raw_expression in value.items():
        variable_name = _normalize_scoring_variable_name(
            raw_name,
            field_path=field_path,
        )
        variable_expression = _normalize_scoring_expression(
            raw_expression,
            field_path=f"{field_path}.{variable_name}",
        )
        if variable_expression is None:
            raise ValueError(f"{field_path}.{variable_name} не должен быть пустым")
        normalized[variable_name] = variable_expression
    if not normalized:
        raise ValueError(f"{field_path} не должен быть пустым")
    return normalized


class ScoringConfig(_Base):
    """
    Конфигурация вычисления итогового `score`.

    Режим:
      - `expression`: кастомное безопасное выражение.
    """

    mode: ScoringMode = "expression"
    top_selection: ScoreTopSelectionMode = Field(
        default="max",
        validation_alias=AliasChoices("top_selection"),
        serialization_alias="top_selection",
    )
    expression: Optional[str] = Field(
        default=DEFAULT_SCORE_EXPRESSION,
        validation_alias=AliasChoices("expression"),
        serialization_alias="expression",
    )
    on_error_score: Optional[float] = None
    variables: Optional[Dict[str, str]] = Field(
        default=None,
        validation_alias=AliasChoices("variables"),
        serialization_alias="variables",
    )
    by_stage: Optional[Dict[str, "StageScoringConfig"]] = Field(
        default=None,
        validation_alias=AliasChoices("by_stage"),
        serialization_alias="by_stage",
    )

    @field_validator("expression")
    @classmethod
    def normalize_expression(cls, value: Optional[str]) -> Optional[str]:
        """Нормализует и валидирует строку expression."""
        return _normalize_scoring_expression(value, field_path="scoring.expression")

    @field_validator("variables")
    @classmethod
    def normalize_variables(
        cls,
        value: Optional[Dict[str, str]],
    ) -> Optional[Dict[str, str]]:
        """Нормализует map переменных scoring."""
        return _normalize_scoring_variables(value, field_path="scoring.variables")

    @field_validator("by_stage")
    @classmethod
    def normalize_by_stage(
        cls,
        value: Optional[Dict[str, "StageScoringConfig"]],
    ) -> Optional[Dict[str, "StageScoringConfig"]]:
        """Нормализует словарь stage-specific scoring overrides."""
        if value is None:
            return None
        normalized: dict[str, StageScoringConfig] = {}
        for raw_stage_name, stage_scoring in value.items():
            stage_name = raw_stage_name.strip().lower()
            if not stage_name:
                raise ValueError("scoring.by_stage содержит пустое имя стадии")
            normalized[stage_name] = stage_scoring
        if not normalized:
            raise ValueError("scoring.by_stage не должен быть пустым")
        return normalized

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "ScoringConfig":
        """Проверяет согласованность `mode` и полей expression."""
        _validate_scoring_mode_and_expression(
            mode=self.mode,
            expression=self.expression,
            field_path="scoring",
        )
        return self

    def stage_override(self, stage_name: Optional[str]) -> Optional["StageScoringConfig"]:
        """Возвращает override scoring для стадии (если задан)."""
        if stage_name is None or self.by_stage is None:
            return None
        normalized_stage_name = stage_name.strip().lower()
        if not normalized_stage_name:
            return None
        return self.by_stage.get(normalized_stage_name)


class StageScoringConfig(_Base):
    """Stage-specific override формулы score."""

    mode: ScoringMode = "expression"
    top_selection: ScoreTopSelectionMode = Field(
        default="max",
        validation_alias=AliasChoices("top_selection"),
        serialization_alias="top_selection",
    )
    expression: Optional[str] = Field(
        default=DEFAULT_SCORE_EXPRESSION,
        validation_alias=AliasChoices("expression"),
        serialization_alias="expression",
    )
    on_error_score: Optional[float] = None
    variables: Optional[Dict[str, str]] = Field(
        default=None,
        validation_alias=AliasChoices("variables"),
        serialization_alias="variables",
    )

    @field_validator("expression")
    @classmethod
    def normalize_expression(cls, value: Optional[str]) -> Optional[str]:
        """Нормализует и валидирует строку stage expression."""
        return _normalize_scoring_expression(
            value,
            field_path="scoring.by_stage.*.expression",
        )

    @field_validator("variables")
    @classmethod
    def normalize_variables(
        cls,
        value: Optional[Dict[str, str]],
    ) -> Optional[Dict[str, str]]:
        """Нормализует map stage-переменных scoring."""
        return _normalize_scoring_variables(
            value,
            field_path="scoring.by_stage.*.variables",
        )

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "StageScoringConfig":
        """Проверяет согласованность `mode` и полей expression."""
        _validate_scoring_mode_and_expression(
            mode=self.mode,
            expression=self.expression,
            field_path="scoring.by_stage.*",
        )
        return self


class CeleryConfig(_Base):
    """Параметры запуска Celery-воркеров для бенчмарк-джоб."""

    workers: int = Field(default=4, gt=0)
    threads_per_worker: int = Field(default=2, gt=0)


class InsertRowsLimitsConfig(_Base):
    """
    Лимиты строк за одну insert-операцию из source в variant по режимам бенчмарка.

    Каждый ключ опционален:
      - `types`
      - `indexes`
      - `combined`
      - `sequential`
      - любые дополнительные ключи для будущих mode.
    """

    model_config = {"extra": "allow"}

    types: Optional[int] = Field(default=None, gt=0)
    indexes: Optional[int] = Field(default=None, gt=0)
    combined: Optional[int] = Field(default=None, gt=0)
    sequential: Optional[int] = Field(default=None, gt=0)

    def merged_over(self, base: Optional["InsertRowsLimitsConfig"]) -> "InsertRowsLimitsConfig":
        """
        Объединяет локальные mode-лимиты поверх базовых.

        Локальное не-None значение перезаписывает соответствующий базовый ключ.
        """
        if base is None:
            return self.model_copy(deep=True)
        merged: Dict[str, int] = dict(base.model_extra or {})
        merged.update(dict(self.model_extra or {}))
        payload: Dict[str, Optional[int]] = {
            "types": self.types if self.types is not None else base.types,
            "indexes": self.indexes if self.indexes is not None else base.indexes,
            "combined": self.combined if self.combined is not None else base.combined,
            "sequential": self.sequential if self.sequential is not None else base.sequential,
        }
        payload.update(merged)
        return InsertRowsLimitsConfig.model_validate(payload)

    def for_mode(self, mode: str) -> Optional[int]:
        """Возвращает лимит для конкретного mode или `None`, если не задан."""
        if mode in {"types", "indexes", "combined", "sequential"}:
            return getattr(self, mode)
        return (self.model_extra or {}).get(mode)

    @model_validator(mode="after")
    def validate_future_mode_values(self) -> "InsertRowsLimitsConfig":
        """
        Проверяет, что дополнительные mode-ключи имеют целое значение > 0.

        Это нужно, чтобы будущие mode работали так же строго, как встроенные.
        """
        for mode, value in (self.model_extra or {}).items():
            if not mode or not mode.strip():
                raise ValueError(
                    "ключ режима в insert_rows_per_operation_limits не должен быть пустым"
                )
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(
                    f"insert_rows_per_operation_limits[{mode!r}] должен быть целым числом > 0"
                )
        return self


class TableRuleConfig(_Base):
    """
    Локальные override для конкретной таблицы `database.table`.

    Может переопределять:
      - rules;
      - column_order_mode;
      - insert_operations_count;
      - sequential_types_top_n_for_indexes;
      - sequential_top_n_limits (top-N лимиты победителей по фазам).
      - final_validation_input_top_n (сколько кандидатов брать из предыдущей
        фазы в генерацию final_validation).
      - max_winners_per_parent_limits (лимиты числа победителей на одного parent
        по фазам для `sequential_phased_topn_strategy`).
      - insert_rows_per_operation_limit;
      - source_insert_rows_per_operation_limit;
      - source_insert_rows_per_operation_limits;
      - insert_rows_per_operation_limits;
      - max_benchmarks_limits;
      - index_granularity_values (перебор `SETTINGS index_granularity`);
      - test_database;
      - strategy;
      - queries.
      - scoring.
      - order_by_first / order_by_candidates.
    """

    database: str
    table: str
    test_database: Optional[str] = None
    rules: RulesConfig = Field(default_factory=RulesConfig)
    column_order_mode: Optional[ColumnOrderMode] = None
    queries: Optional[QueriesConfig] = None
    scoring: Optional[ScoringConfig] = None
    insert_operations_count: Optional[int] = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("insert_operations_count"),
        serialization_alias="insert_operations_count",
    )
    sequential_top_n: Optional[int] = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("sequential_types_top_n_for_indexes"),
        serialization_alias="sequential_types_top_n_for_indexes",
    )
    sequential_top_n_limits: Optional[InsertRowsLimitsConfig] = Field(
        default=None,
        validation_alias=AliasChoices("sequential_top_n_limits"),
        serialization_alias="sequential_top_n_limits",
    )
    final_validation_input_top_n: Optional[int] = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("final_validation_input_top_n"),
        serialization_alias="final_validation_input_top_n",
    )
    max_winners_per_parent_limits: Optional[InsertRowsLimitsConfig] = Field(
        default=None,
        validation_alias=AliasChoices("max_winners_per_parent_limits"),
        serialization_alias="max_winners_per_parent_limits",
    )
    insert_rows_limit: Optional[int] = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("insert_rows_per_operation_limit"),
        serialization_alias="insert_rows_per_operation_limit",
    )
    source_insert_rows_limit: Optional[int] = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("source_insert_rows_per_operation_limit"),
        serialization_alias="source_insert_rows_per_operation_limit",
    )
    source_insert_rows_limits: Optional[InsertRowsLimitsConfig] = Field(
        default=None,
        validation_alias=AliasChoices("source_insert_rows_per_operation_limits"),
        serialization_alias="source_insert_rows_per_operation_limits",
    )
    insert_rows_limits: Optional[InsertRowsLimitsConfig] = Field(
        default=None,
        validation_alias=AliasChoices("insert_rows_per_operation_limits"),
        serialization_alias="insert_rows_per_operation_limits",
    )
    max_benchmarks_limits: Optional[InsertRowsLimitsConfig] = None
    index_granularity_values: Optional[List[int]] = Field(
        default=None,
        validation_alias=AliasChoices("index_granularity_values"),
        serialization_alias="index_granularity_values",
    )
    strategy: Optional[BenchmarkStrategy] = None
    order_by_first: Optional[str] = None
    order_by_candidates: Optional[List[str]] = None

    @field_validator("database", "table")
    @classmethod
    def non_empty_table_target(cls, value: str) -> str:
        """Проверяет, что имя БД/таблицы не пустое после trim."""
        value = value.strip()
        if not value:
            raise ValueError("database/table не должны быть пустыми")
        return value

    @field_validator("test_database")
    @classmethod
    def non_empty_test_database(cls, value: Optional[str]) -> Optional[str]:
        """Проверяет, что test_database не пустой, если задан."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("test_database не должен быть пустым")
        return cleaned

    @field_validator("order_by_first")
    @classmethod
    def non_empty_order_by_first(cls, value: Optional[str]) -> Optional[str]:
        """Проверяет, что order_by_first не пустой, если задан."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("order_by_first не должен быть пустым")
        return cleaned

    @field_validator("order_by_candidates")
    @classmethod
    def normalize_order_by_candidates(
        cls,
        values: Optional[List[str]],
    ) -> Optional[List[str]]:
        """Нормализует и дедуплицирует order_by_candidates."""
        if values is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            candidate = value.strip()
            if not candidate:
                raise ValueError("order_by_candidates не должен содержать пустые значения")
            if candidate in seen:
                continue
            seen.add(candidate)
            cleaned.append(candidate)
        if not cleaned:
            raise ValueError("order_by_candidates не должен быть пустым")
        return cleaned

    @field_validator("index_granularity_values")
    @classmethod
    def normalize_index_granularity_values(
        cls,
        values: Optional[List[int]],
    ) -> Optional[List[int]]:
        """Проверяет список перебора `SETTINGS index_granularity`."""
        return _normalize_positive_int_sequence(values)


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
      - strategy исполнения таблицы (table-level execution strategy);
      - режим резолвинга column/index правил относительно глобального rule bank;
      - режим вычисления `column_order` (опционально);
      - режим вычисления `score` (встроенный или expression);
      - ограничение по числу insert-замеров и режим комбинатора.
      - `sequential_types_top_n_for_indexes` для двухфазного режима sequential.
      - `sequential_top_n_limits` — top-N лимиты победителей по фазам
        (`order_by`, `types`, `codecs`, `indexes`, `final_validation`).
      - `final_validation_input_top_n` — сколько кандидатов брать из
        предыдущей фазы в генерацию final_validation.
      - `max_winners_per_parent_limits` — лимиты числа победителей на одного
        parent-варианта по фазам (`types`, `codecs`, `indexes`).
      - `insert_rows_per_operation_limit` — сколько строк
        копировать за один insert-замер из source-таблицы в variant.
      - `source_insert_rows_per_operation_limit` —
        сколько строк копировать за один insert-замер в baseline-копию
        исходной таблицы (source benchmark) перед запуском вариантов.
      - `source_insert_rows_per_operation_limits` — лимиты baseline-вставки по mode.
      - `insert_rows_per_operation_limits` —
        лимиты копирования за один insert-замер по конкретным mode.
      - `max_benchmarks_limits` — лимиты числа variant jobs по mode.
      - `index_granularity_values` — перебор `SETTINGS index_granularity`
        (декартово произведение с индексными вариантами).
      - `test_database` — БД для создания variant-таблиц (по умолчанию source БД).
      - `order_by_first` / `order_by_candidates` — настройки фазы ORDER BY
        для `sequential_phased_topn_strategy`.
    """

    id: str
    connection_id: str
    strategy: BenchmarkStrategy
    global_rules: RulesConfig = Field(default_factory=RulesConfig)
    column_order_mode: Optional[ColumnOrderMode] = None
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)

    databases: DatabasesSelector = "*"
    tables: TablesSelector = "*"
    test_database: Optional[str] = None

    insert_operations_count: int = Field(
        default=100,
        gt=0,
        validation_alias=AliasChoices("insert_operations_count"),
        serialization_alias="insert_operations_count",
    )
    sequential_top_n: int = Field(
        default=1,
        gt=0,
        validation_alias=AliasChoices("sequential_types_top_n_for_indexes"),
        serialization_alias="sequential_types_top_n_for_indexes",
    )
    sequential_top_n_limits: Optional[InsertRowsLimitsConfig] = Field(
        default=None,
        validation_alias=AliasChoices("sequential_top_n_limits"),
        serialization_alias="sequential_top_n_limits",
    )
    final_validation_input_top_n: Optional[int] = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("final_validation_input_top_n"),
        serialization_alias="final_validation_input_top_n",
    )
    max_winners_per_parent_limits: Optional[InsertRowsLimitsConfig] = Field(
        default=None,
        validation_alias=AliasChoices("max_winners_per_parent_limits"),
        serialization_alias="max_winners_per_parent_limits",
    )
    insert_rows_limit: Optional[int] = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("insert_rows_per_operation_limit"),
        serialization_alias="insert_rows_per_operation_limit",
    )
    source_insert_rows_limit: Optional[int] = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("source_insert_rows_per_operation_limit"),
        serialization_alias="source_insert_rows_per_operation_limit",
    )
    source_insert_rows_limits: Optional[InsertRowsLimitsConfig] = Field(
        default=None,
        validation_alias=AliasChoices("source_insert_rows_per_operation_limits"),
        serialization_alias="source_insert_rows_per_operation_limits",
    )
    insert_rows_limits: Optional[InsertRowsLimitsConfig] = Field(
        default=None,
        validation_alias=AliasChoices("insert_rows_per_operation_limits"),
        serialization_alias="insert_rows_per_operation_limits",
    )
    max_benchmarks_limits: Optional[InsertRowsLimitsConfig] = None
    index_granularity_values: Optional[List[int]] = Field(
        default=None,
        validation_alias=AliasChoices("index_granularity_values"),
        serialization_alias="index_granularity_values",
    )
    column_rules_mode: Optional[RuleSourceMode] = None
    index_rules_mode: Optional[RuleSourceMode] = None
    queries: QueriesConfig = Field(default_factory=QueriesConfig)
    table_rules: List[TableRuleConfig] = Field(default_factory=list)
    order_by_first: Optional[str] = None
    order_by_candidates: Optional[List[str]] = None

    @field_validator("test_database")
    @classmethod
    def non_empty_test_database(cls, value: Optional[str]) -> Optional[str]:
        """Проверяет, что test_database не пустой, если задан."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("test_database не должен быть пустым")
        return cleaned

    @field_validator("order_by_first")
    @classmethod
    def non_empty_order_by_first(cls, value: Optional[str]) -> Optional[str]:
        """Проверяет, что order_by_first не пустой, если задан."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("order_by_first не должен быть пустым")
        return cleaned

    @field_validator("order_by_candidates")
    @classmethod
    def normalize_order_by_candidates(
        cls,
        values: Optional[List[str]],
    ) -> Optional[List[str]]:
        """Нормализует и дедуплицирует order_by_candidates."""
        if values is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            candidate = value.strip()
            if not candidate:
                raise ValueError("order_by_candidates не должен содержать пустые значения")
            if candidate in seen:
                continue
            seen.add(candidate)
            cleaned.append(candidate)
        if not cleaned:
            raise ValueError("order_by_candidates не должен быть пустым")
        return cleaned

    @field_validator("index_granularity_values")
    @classmethod
    def normalize_index_granularity_values(
        cls,
        values: Optional[List[int]],
    ) -> Optional[List[int]]:
        """Проверяет список перебора `SETTINGS index_granularity`."""
        return _normalize_positive_int_sequence(values)

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
