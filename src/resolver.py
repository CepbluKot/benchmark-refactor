"""
Резолвер правил для этапа планирования бенчмарка.

Задача модуля:
  - объединить глобальные и локальные правила;
  - выбрать источник правил (явный bank или default bank по DBMS из конфига);
  - преобразовать config-модели в runtime-правила генератора вариантов.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from src.column_rules import ColumnAlternatives, ColumnRule
from src.datatype_alternatives import (
    generate_possible_compressions_w_preprocessings,
    generate_possible_new_datatypes,
)
from src.index_alternatives import generate_possible_indexes_by_type
from src.index_rules import IndexAlternatives, IndexRule, IndexVariant
from src.models import (
    ColumnRuleConfig,
    IndexConfig,
    IndexRuleConfig,
    RuleBankConfig,
    RuleSourceMode,
    RulesConfig,
)


def _deduplicate_preserve_order(values: List[str]) -> List[str]:
    """Удаляет дубликаты, сохраняя исходный порядок значений."""
    seen: set[str] = set()
    deduplicated: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduplicated.append(value)
    return deduplicated


def _normalize_codec_clause(codec_expression: str) -> str:
    """Приводит codec-expression к формату `CODEC(...)`."""
    normalized = codec_expression.strip()
    if not normalized:
        return normalized
    if normalized.upper().startswith("CODEC("):
        return normalized
    return f"CODEC({normalized})"


def _deduplicate_index_configs_preserve_order(
    values: List[IndexConfig],
) -> List[IndexConfig]:
    """Удаляет дубли index-конфигов, сохраняя исходный порядок."""
    seen: set[tuple[str, int, Optional[tuple[int, ...]], Optional[tuple[int, ...]]]] = set()
    deduplicated: list[IndexConfig] = []
    for value in values:
        granularity_values = (
            tuple(value.granularity_values)
            if value.granularity_values is not None
            else None
        )
        table_granularity_values = (
            tuple(value.table_index_granularity_values)
            if value.table_index_granularity_values is not None
            else None
        )
        key = (
            value.type.strip(),
            int(value.granularity),
            granularity_values,
            table_granularity_values,
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(value)
    return deduplicated


def _expand_index_granularity_configs(
    values: List[IndexConfig],
) -> List[IndexConfig]:
    """
    Раскрывает `granularity_values` в набор отдельных index-конфигов.

    Пример:
      {"type": "minmax", "granularity": [2, 4]}
    -> два runtime-конфига с granularity=2 и granularity=4.
    """
    expanded: list[IndexConfig] = []
    for value in values:
        for granularity in value.iter_granularity_values():
            expanded.append(
                IndexConfig(
                    type=value.type,
                    granularity=granularity,
                    table_index_granularity_values=value.table_index_granularity_values,
                )
            )
    return _deduplicate_index_configs_preserve_order(expanded)


def _expand_auto_column_alternatives(
    cfg: ColumnRuleConfig,
    *,
    types: List[str],
    codecs: List[str],
) -> Tuple[List[str], List[str]]:
    """
    Добавляет legacy-автогенерацию type+codec альтернатив при включённом флаге.

    Генерация следует legacy-логике:
      - compressions/preprocessings от `generate_possible_compressions_w_preprocessings`;
      - комбинации типов через `generate_possible_new_datatypes`.
    """
    if not cfg.auto_generate_alternatives:
        return types, codecs

    auto_types_seed = list(types)
    if not auto_types_seed and cfg.by_type is not None:
        auto_types_seed = [cfg.by_type]
    if not auto_types_seed:
        return types, codecs

    compression_datatype = (
        cfg.auto_compressions_datatype
        or cfg.by_type
        or auto_types_seed[0]
    )
    auto_compressions = generate_possible_compressions_w_preprocessings(
        compression_datatype
    )
    generated = generate_possible_new_datatypes(
        auto_types_seed,
        auto_compressions,
    )

    auto_types = [item.datatype for item in generated]
    auto_codecs = [_normalize_codec_clause(item.codec) for item in generated]
    merged_types = _deduplicate_preserve_order(types + auto_types)
    merged_codecs = _deduplicate_preserve_order(codecs + auto_codecs)
    return merged_types, merged_codecs


def _expand_auto_index_alternatives(
    cfg: IndexRuleConfig,
    *,
    indexes: List[IndexConfig],
) -> List[IndexConfig]:
    """
    Добавляет автогенерацию индексов по типу при включённом флаге.

    Ручные индексы сохраняются и имеют приоритет в порядке.
    """
    if not cfg.auto_generate_indexes:
        return indexes

    datatype_hint = cfg.auto_indexes_datatype or cfg.by_type
    if datatype_hint is None:
        return indexes

    generated = [
        IndexConfig(type=item.index_type, granularity=item.granularity)
        for item in generate_possible_indexes_by_type(datatype_hint)
    ]
    return _deduplicate_index_configs_preserve_order(indexes + generated)


def _column_rule_from_config(cfg: ColumnRuleConfig) -> ColumnRule:
    """Конвертирует `ColumnRuleConfig` в runtime `ColumnRule`."""
    types = list(cfg.types)
    codecs = list(cfg.codecs)
    types, codecs = _expand_auto_column_alternatives(
        cfg,
        types=types,
        codecs=codecs,
    )
    return ColumnRule(
        by_type=cfg.by_type,
        by_name=cfg.by_name,
        alternatives=ColumnAlternatives(
            types=types,
            codecs=codecs,
        ),
    )


def _index_rule_from_config(cfg: IndexRuleConfig) -> IndexRule:
    """Конвертирует `IndexRuleConfig` в runtime `IndexRule`."""
    indexes = _expand_auto_index_alternatives(
        cfg,
        indexes=list(cfg.indexes),
    )
    indexes = _expand_index_granularity_configs(indexes)
    return IndexRule(
        by_type=cfg.by_type,
        by_name=cfg.by_name,
        alternatives=IndexAlternatives(
            variants=[
                IndexVariant(
                    index_type=idx.type,
                    granularity=idx.granularity,
                    table_index_granularity_values=idx.table_index_granularity_values,
                )
                for idx in indexes
            ]
        ),
    )


class ResolvedRules:
    """
    Runtime-правила после полного резолвинга источников.

    Используется planner'ом как финальный набор для combiner:
    `column_rules`, `index_rules`, `column_order`.
    """

    def __init__(
        self,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Dict[str, int],
        source_bank: Optional[str] = None,
    ) -> None:
        """Сохраняет уже разрешённые правила и технический `source_bank` для трассировки."""
        self.column_rules = column_rules
        self.index_rules = index_rules
        self.column_order = column_order
        self.source_bank = source_bank

    def __repr__(self) -> str:
        """Короткое представление для логов и отладки."""
        return (
            f"ResolvedRules("
            f"column_rules={len(self.column_rules)}, "
            f"index_rules={len(self.index_rules)}, "
            f"column_order={self.column_order}, "
            f"source_bank={self.source_bank!r})"
        )


class RuleResolver:
    """
    Основной resolver с поддержкой default rule bank по DBMS.

    Приоритет источников:
      1) `rules_config.rule_bank` (явно указанный банк);
      2) inline override без банка (работаем только с inline);
      3) `default_rule_banks[dbms]`;
    """

    def __init__(
        self,
        banks: Dict[str, RuleBankConfig],
        default_rule_banks: Optional[Dict[str, str]] = None,
    ) -> None:
        """Инициализирует resolver пользовательскими банками и default map."""
        self._banks = dict(banks)
        self._default_rule_banks = {
            dbms.lower(): bank_id for dbms, bank_id in (default_rule_banks or {}).items()
        }

    @staticmethod
    def merge(global_rules: RulesConfig, local_rules: Optional[RulesConfig]) -> RulesConfig:
        """
        Объединяет глобальные и локальные правила.

        Поля локальных правил перезаписывают одноимённые поля глобальных.
        """
        if local_rules is None:
            return global_rules.model_copy(deep=True)
        return local_rules.merged_over(global_rules)

    def resolve(
        self,
        rules_config: RulesConfig,
        dbms: Optional[str] = None,
        column_rules_mode: Optional[RuleSourceMode] = None,
        index_rules_mode: Optional[RuleSourceMode] = None,
        global_rules: Optional[RulesConfig] = None,
    ) -> ResolvedRules:
        """
        Резолвит `RulesConfig` в финальные runtime-правила.

        Для каждого блока правил (`column_rules`, `index_rules`, `column_order`)
        выбирает inline значение, а если его нет — берёт из выбранного банка.

        Если заданы `column_rules_mode`/`index_rules_mode`, поведение становится
        явным и опирается на benchmark-level (глобальный) bank:
          - `global_bank_only`
          - `global_bank_with_inline_priority`
          - `inline_only`
        """
        source_bank = None
        bank_name: Optional[str]
        bank: Optional[RuleBankConfig]

        # Legacy path: поведение 1:1 как раньше.
        if column_rules_mode is None and index_rules_mode is None:
            bank = self._pick_bank(rules_config, dbms)
            bank_name = self._resolve_bank_name(rules_config, dbms) if bank is not None else None

            if rules_config.column_rules is not None:
                column_rules = [_column_rule_from_config(r) for r in rules_config.column_rules]
            elif bank is not None:
                column_rules = [_column_rule_from_config(r) for r in bank.column_rules]
            else:
                column_rules = []

            if rules_config.index_rules is not None:
                index_rules = [_index_rule_from_config(r) for r in rules_config.index_rules]
            elif bank is not None:
                index_rules = [_index_rule_from_config(r) for r in bank.index_rules]
            else:
                index_rules = []

            if rules_config.column_order is not None:
                column_order = dict(rules_config.column_order)
            elif bank is not None:
                column_order = dict(bank.column_order)
            else:
                column_order = {}

            source_bank = bank_name
            return ResolvedRules(
                column_rules=column_rules,
                index_rules=index_rules,
                column_order=column_order,
                source_bank=source_bank,
            )

        bank_name, bank = self._pick_global_bank(global_rules, dbms)
        requires_global_bank = (
            column_rules_mode in ("global_bank_only", "global_bank_with_inline_priority")
            or index_rules_mode in ("global_bank_only", "global_bank_with_inline_priority")
        )
        if requires_global_bank and bank is None:
            raise ValueError(
                "Выбран rules_mode, требующий глобальный rule bank, "
                "но global_rules.rule_bank не задан и default_rule_banks для DBMS не найден"
            )

        column_rules, column_used_bank = self._resolve_column_rules(
            mode=column_rules_mode,
            inline_rules=rules_config.column_rules,
            bank=bank,
        )
        index_rules, index_used_bank = self._resolve_index_rules(
            mode=index_rules_mode,
            inline_rules=rules_config.index_rules,
            bank=bank,
        )

        if rules_config.column_order is not None:
            column_order = dict(rules_config.column_order)
            column_order_used_bank = False
        elif bank is not None:
            column_order = dict(bank.column_order)
            column_order_used_bank = True
        else:
            column_order = {}
            column_order_used_bank = False

        if bank_name is not None and (column_used_bank or index_used_bank or column_order_used_bank):
            source_bank = bank_name

        return ResolvedRules(
            column_rules=column_rules,
            index_rules=index_rules,
            column_order=column_order,
            source_bank=source_bank,
        )

    def _pick_global_bank(
        self,
        global_rules: Optional[RulesConfig],
        dbms: Optional[str],
    ) -> Tuple[Optional[str], Optional[RuleBankConfig]]:
        """
        Возвращает банк правил benchmark-level (глобальный для данного benchmark).

        Приоритет:
          1) explicit `global_rules.rule_bank`;
          2) `default_rule_banks[dbms]`.
        """
        bank_id: Optional[str] = None
        if global_rules is not None and global_rules.rule_bank is not None:
            bank_id = global_rules.rule_bank
        else:
            dbms_key = (dbms or "").lower()
            if dbms_key and dbms_key in self._default_rule_banks:
                bank_id = self._default_rule_banks[dbms_key]

        if bank_id is None:
            return None, None
        return bank_id, self._banks[bank_id]

    @staticmethod
    def _resolve_column_rules(
        mode: Optional[RuleSourceMode],
        inline_rules: Optional[List[ColumnRuleConfig]],
        bank: Optional[RuleBankConfig],
    ) -> Tuple[List[ColumnRule], bool]:
        """Собирает итоговый список column_rules и признак использования bank."""
        inline = (
            [_column_rule_from_config(rule) for rule in inline_rules]
            if inline_rules is not None
            else []
        )
        bank_rules = (
            [_column_rule_from_config(rule) for rule in bank.column_rules]
            if bank is not None
            else []
        )

        if mode == "global_bank_only":
            return bank_rules, bank is not None
        if mode == "global_bank_with_inline_priority":
            return inline + bank_rules, bank is not None
        if mode == "inline_only":
            return inline, False

        # mode=None: default behavior (inline if задано, иначе bank).
        if inline_rules is not None:
            return inline, False
        return bank_rules, bank is not None

    @staticmethod
    def _resolve_index_rules(
        mode: Optional[RuleSourceMode],
        inline_rules: Optional[List[IndexRuleConfig]],
        bank: Optional[RuleBankConfig],
    ) -> Tuple[List[IndexRule], bool]:
        """Собирает итоговый список index_rules и признак использования bank."""
        inline = (
            [_index_rule_from_config(rule) for rule in inline_rules]
            if inline_rules is not None
            else []
        )
        bank_rules = (
            [_index_rule_from_config(rule) for rule in bank.index_rules]
            if bank is not None
            else []
        )

        if mode == "global_bank_only":
            return bank_rules, bank is not None
        if mode == "global_bank_with_inline_priority":
            return inline + bank_rules, bank is not None
        if mode == "inline_only":
            return inline, False

        # mode=None: default behavior (inline if задано, иначе bank).
        if inline_rules is not None:
            return inline, False
        return bank_rules, bank is not None

    def _pick_bank(
        self, rules_config: RulesConfig, dbms: Optional[str]
    ) -> Optional[RuleBankConfig]:
        """Выбирает банк правил согласно приоритетам resolver'а."""
        if rules_config.rule_bank is not None:
            return self._banks[rules_config.rule_bank]

        if rules_config.has_inline_overrides():
            return None

        dbms_key = (dbms or "").lower()
        if dbms_key and dbms_key in self._default_rule_banks:
            bank_id = self._default_rule_banks[dbms_key]
            return self._banks[bank_id]
        return None

    def _resolve_bank_name(self, rules_config: RulesConfig, dbms: Optional[str]) -> Optional[str]:
        """Возвращает человекочитаемое имя банка, из которого взяты правила."""
        if rules_config.rule_bank is not None:
            return rules_config.rule_bank

        dbms_key = (dbms or "").lower()
        if dbms_key and dbms_key in self._default_rule_banks:
            return self._default_rule_banks[dbms_key]
        return None


def resolve(
    rules_config: RulesConfig,
    banks: Dict[str, RuleBankConfig],
    default_rule_banks: Optional[Dict[str, str]] = None,
    dbms: Optional[str] = None,
    column_rules_mode: Optional[RuleSourceMode] = None,
    index_rules_mode: Optional[RuleSourceMode] = None,
    global_rules: Optional[RulesConfig] = None,
) -> ResolvedRules:
    """
    Функциональная обёртка над `RuleResolver` для обратной совместимости.

    Нужна в местах, где используется прежний API `resolve(...)` без класса.
    """
    resolver = RuleResolver(
        banks=banks,
        default_rule_banks=default_rule_banks,
    )
    return resolver.resolve(
        rules_config,
        dbms=dbms,
        column_rules_mode=column_rules_mode,
        index_rules_mode=index_rules_mode,
        global_rules=global_rules,
    )
