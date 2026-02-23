"""
Резолвер правил для этапа планирования бенчмарка.

Задача модуля:
  - объединить глобальные и локальные правила;
  - выбрать источник правил (явный bank, default bank по DBMS, builtin bank);
  - преобразовать config-модели в runtime-правила генератора вариантов.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from column_rules import ColumnAlternatives, ColumnRule
from default_rule_banks import BUILTIN_RULE_BANKS_BY_DBMS
from index_rules import IndexAlternatives, IndexRule, IndexVariant
from models import ColumnRuleConfig, IndexRuleConfig, RuleBankConfig, RulesConfig


def _column_rule_from_config(cfg: ColumnRuleConfig) -> ColumnRule:
    """Конвертирует `ColumnRuleConfig` в runtime `ColumnRule`."""
    return ColumnRule(
        by_type=cfg.by_type,
        by_name=cfg.by_name,
        alternatives=ColumnAlternatives(
            types=list(cfg.types),
            codecs=list(cfg.codecs),
        ),
    )


def _index_rule_from_config(cfg: IndexRuleConfig) -> IndexRule:
    """Конвертирует `IndexRuleConfig` в runtime `IndexRule`."""
    return IndexRule(
        by_type=cfg.by_type,
        by_name=cfg.by_name,
        alternatives=IndexAlternatives(
            variants=[
                IndexVariant(index_type=idx.type, granularity=idx.granularity)
                for idx in cfg.indexes
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
    Основной resolver с поддержкой default/builtin rule bank по DBMS.

    Приоритет источников:
      1) `rules_config.rule_bank` (явно указанный банк);
      2) inline override без банка (работаем только с inline);
      3) `default_rule_banks[dbms]`;
      4) builtin bank для DBMS (например clickhouse).
    """

    def __init__(
        self,
        banks: Dict[str, RuleBankConfig],
        default_rule_banks: Optional[Dict[str, str]] = None,
        builtin_rule_banks: Optional[Dict[str, RuleBankConfig]] = None,
    ) -> None:
        """Инициализирует resolver пользовательскими, default и builtin банками."""
        self._banks = dict(banks)
        self._default_rule_banks = {
            dbms.lower(): bank_id for dbms, bank_id in (default_rule_banks or {}).items()
        }
        self._builtin_rule_banks = dict(
            builtin_rule_banks or BUILTIN_RULE_BANKS_BY_DBMS
        )

    @staticmethod
    def merge(global_rules: RulesConfig, local_rules: Optional[RulesConfig]) -> RulesConfig:
        """
        Объединяет глобальные и локальные правила.

        Поля локальных правил перезаписывают одноимённые поля глобальных.
        """
        if local_rules is None:
            return global_rules.model_copy(deep=True)
        return local_rules.merged_over(global_rules)

    def resolve(self, rules_config: RulesConfig, dbms: Optional[str] = None) -> ResolvedRules:
        """
        Резолвит `RulesConfig` в финальные runtime-правила.

        Для каждого блока правил (`column_rules`, `index_rules`, `column_order`)
        выбирает inline значение, а если его нет — берёт из выбранного банка.
        """
        source_bank = None
        bank = self._pick_bank(rules_config, dbms)
        if bank is not None:
            source_bank = self._resolve_bank_name(rules_config, dbms)

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

        return ResolvedRules(
            column_rules=column_rules,
            index_rules=index_rules,
            column_order=column_order,
            source_bank=source_bank,
        )

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

        if dbms_key and dbms_key in self._builtin_rule_banks:
            return self._builtin_rule_banks[dbms_key]
        return None

    def _resolve_bank_name(self, rules_config: RulesConfig, dbms: Optional[str]) -> Optional[str]:
        """Возвращает человекочитаемое имя банка, из которого взяты правила."""
        if rules_config.rule_bank is not None:
            return rules_config.rule_bank

        dbms_key = (dbms or "").lower()
        if dbms_key and dbms_key in self._default_rule_banks:
            return self._default_rule_banks[dbms_key]

        if dbms_key and dbms_key in self._builtin_rule_banks:
            return f"builtin:{dbms_key}"
        return None


def resolve(
    rules_config: RulesConfig,
    banks: Dict[str, RuleBankConfig],
    default_rule_banks: Optional[Dict[str, str]] = None,
    dbms: Optional[str] = None,
) -> ResolvedRules:
    """
    Функциональная обёртка над `RuleResolver` для обратной совместимости.

    Нужна в местах, где используется прежний API `resolve(...)` без класса.
    """
    resolver = RuleResolver(
        banks=banks,
        default_rule_banks=default_rule_banks,
    )
    return resolver.resolve(rules_config, dbms=dbms)
