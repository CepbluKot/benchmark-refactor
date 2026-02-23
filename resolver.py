"""Резолвер правил и merge глобальных/локальных override'ов."""

from __future__ import annotations

from typing import Dict, List, Optional

from column_rules import ColumnAlternatives, ColumnRule
from default_rule_banks import BUILTIN_RULE_BANKS_BY_DBMS
from index_rules import IndexAlternatives, IndexRule, IndexVariant
from models import ColumnRuleConfig, IndexRuleConfig, RuleBankConfig, RulesConfig


def _column_rule_from_config(cfg: ColumnRuleConfig) -> ColumnRule:
    return ColumnRule(
        by_type=cfg.by_type,
        by_name=cfg.by_name,
        alternatives=ColumnAlternatives(
            types=list(cfg.types),
            codecs=list(cfg.codecs),
        ),
    )


def _index_rule_from_config(cfg: IndexRuleConfig) -> IndexRule:
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
    """Итоговые правила после резолвинга банка + инлайна."""

    def __init__(
        self,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Dict[str, int],
        source_bank: Optional[str] = None,
    ) -> None:
        self.column_rules = column_rules
        self.index_rules = index_rules
        self.column_order = column_order
        self.source_bank = source_bank

    def __repr__(self) -> str:
        return (
            f"ResolvedRules("
            f"column_rules={len(self.column_rules)}, "
            f"index_rules={len(self.index_rules)}, "
            f"column_order={self.column_order}, "
            f"source_bank={self.source_bank!r})"
        )


class RuleResolver:
    """Классический resolver с поддержкой default rule banks по DBMS."""

    def __init__(
        self,
        banks: Dict[str, RuleBankConfig],
        default_rule_banks: Optional[Dict[str, str]] = None,
        builtin_rule_banks: Optional[Dict[str, RuleBankConfig]] = None,
    ) -> None:
        self._banks = dict(banks)
        self._default_rule_banks = {
            dbms.lower(): bank_id for dbms, bank_id in (default_rule_banks or {}).items()
        }
        self._builtin_rule_banks = dict(
            builtin_rule_banks or BUILTIN_RULE_BANKS_BY_DBMS
        )

    @staticmethod
    def merge(global_rules: RulesConfig, local_rules: Optional[RulesConfig]) -> RulesConfig:
        """Локальные правила перезатирают глобальные по полям."""
        if local_rules is None:
            return global_rules.model_copy(deep=True)
        return local_rules.merged_over(global_rules)

    def resolve(self, rules_config: RulesConfig, dbms: Optional[str] = None) -> ResolvedRules:
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
    """Обратная совместимость со старым API."""
    resolver = RuleResolver(
        banks=banks,
        default_rule_banks=default_rule_banks,
    )
    return resolver.resolve(rules_config, dbms=dbms)
