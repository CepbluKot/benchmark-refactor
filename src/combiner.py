"""
Комбинатор вариантов по mode.

Базовые режимы:
  types      -> только варианты типов/кодеков, индексы не трогаются
  indexes    -> только варианты индексов, типы не трогаются
  sequential -> сначала все варианты типов, потом все варианты индексов
  combined   -> декартово произведение вариантов типов x вариантов индексов

Главная цель модуля: дать расширяемый реестр стратегий генерации.
Чтобы добавить новый способ перебора, достаточно реализовать интерфейс
`VariantGenerationStrategy` и зарегистрировать его через
`register_variant_generation_strategy(...)`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from pydantic import BaseModel
from typing import Dict, Generator, Iterable, List, Optional, Tuple

from clickhouse_ddl import TableDDL
from column_rules import ColumnRule
from index_rules import IndexRule
from column_variants import ColumnVariantMeta, iter_column_variants, total_column_variants
from index_variants import IndexVariantMeta, iter_index_variants, total_index_variants


# ─── метаданные итогового варианта ───────────────────────────────────────────

class VariantMeta(BaseModel):
    """Метаданные одного варианта таблицы для бенчмарка."""
    global_index: int                               # сквозной номер
    mode: str
    column_meta: Optional[ColumnVariantMeta] = None
    index_meta: Optional[IndexVariantMeta] = None

    @property
    def column_choices(self):
        """Возвращает решения по колонкам для текущего варианта (если есть)."""
        return self.column_meta.column_choices if self.column_meta else {}

    @property
    def index_choices(self):
        """Возвращает решения по индексам для текущего варианта (если есть)."""
        return self.index_meta.index_choices if self.index_meta else {}


# ─── комбинатор ──────────────────────────────────────────────────────────────


class VariantGenerationStrategy(ABC):
    """
    Контракт генерации вариантов для одного `mode`.

    Новый режим подключается через реализацию этого интерфейса и регистрацию
    в `register_variant_generation_strategy`.
    """

    @abstractmethod
    def iter_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> Iterable[Tuple[TableDDL, VariantMeta]]:
        """Лениво генерирует `(variant_ddl, meta)` для конкретного режима."""
        pass

    @abstractmethod
    def total_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> int:
        """Возвращает число вариантов для режима без materialize всего потока."""
        pass


class TypesVariantGenerationStrategy(VariantGenerationStrategy):
    """Режим `types`: меняем только типы/кодеки колонок."""

    def iter_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> Iterable[Tuple[TableDDL, VariantMeta]]:
        del index_rules
        for variant, col_meta in iter_column_variants(table, column_rules, column_order):
            yield variant, VariantMeta(
                global_index=0,
                mode="types",
                column_meta=col_meta,
            )

    def total_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> int:
        del index_rules
        return total_column_variants(table, column_rules, column_order)


class IndexesVariantGenerationStrategy(VariantGenerationStrategy):
    """Режим `indexes`: меняем только skip-индексы."""

    def iter_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> Iterable[Tuple[TableDDL, VariantMeta]]:
        del column_rules
        for variant, idx_meta in iter_index_variants(
            table,
            index_rules,
            column_order=column_order,
        ):
            yield variant, VariantMeta(
                global_index=0,
                mode="indexes",
                index_meta=idx_meta,
            )

    def total_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> int:
        del column_rules
        return total_index_variants(table, index_rules, column_order)


class SequentialVariantGenerationStrategy(VariantGenerationStrategy):
    """
    Режим `sequential` на уровне combiner.

    Здесь это последовательная выдача:
      1) всех type/codec вариантов;
      2) всех index-вариантов на исходной таблице.
    Полноценный top-N sequential orchestration выполняется в runner.
    """

    def iter_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> Iterable[Tuple[TableDDL, VariantMeta]]:
        for variant, col_meta in iter_column_variants(table, column_rules, column_order):
            yield variant, VariantMeta(
                global_index=0,
                mode="sequential",
                column_meta=col_meta,
            )
        for variant, idx_meta in iter_index_variants(
            table,
            index_rules,
            column_order=column_order,
        ):
            yield variant, VariantMeta(
                global_index=0,
                mode="sequential",
                index_meta=idx_meta,
            )

    def total_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> int:
        col_total = total_column_variants(table, column_rules, column_order)
        idx_total = total_index_variants(table, index_rules, column_order)
        return col_total + idx_total


class CombinedVariantGenerationStrategy(VariantGenerationStrategy):
    """Режим `combined`: декартово произведение types x indexes."""

    def iter_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> Iterable[Tuple[TableDDL, VariantMeta]]:
        index_variants_list = list(
            iter_index_variants(table, index_rules, column_order=column_order)
        )
        for col_variant, col_meta in iter_column_variants(table, column_rules, column_order):
            for idx_variant_base, idx_meta_base in index_variants_list:
                combined = col_variant.copy()
                combined.indexes = [idx for idx in idx_variant_base.indexes]
                final_idx_meta = IndexVariantMeta(
                    index=idx_meta_base.index,
                    index_choices=deepcopy(idx_meta_base.index_choices),
                )
                yield combined, VariantMeta(
                    global_index=0,
                    mode="combined",
                    column_meta=col_meta,
                    index_meta=final_idx_meta,
                )

    def total_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> int:
        col_total = total_column_variants(table, column_rules, column_order)
        idx_total = total_index_variants(table, index_rules, column_order)
        return col_total * idx_total


MODE_VARIANT_STRATEGIES: Dict[str, VariantGenerationStrategy] = {
    "types": TypesVariantGenerationStrategy(),
    "indexes": IndexesVariantGenerationStrategy(),
    "sequential": SequentialVariantGenerationStrategy(),
    "combined": CombinedVariantGenerationStrategy(),
}


def register_variant_generation_strategy(
    mode: str,
    strategy: VariantGenerationStrategy,
    *,
    overwrite: bool = False,
) -> None:
    """
    Регистрирует стратегию генерации вариантов для `mode`.

    Пример:
      register_variant_generation_strategy("my_mode", MyModeStrategy())
    """
    normalized_mode = mode.strip()
    if not normalized_mode:
        raise ValueError("mode не должен быть пустым")
    if normalized_mode in MODE_VARIANT_STRATEGIES and not overwrite:
        raise ValueError(
            f"Стратегия для mode={normalized_mode!r} уже зарегистрирована. "
            "Используй overwrite=True для замены."
        )
    MODE_VARIANT_STRATEGIES[normalized_mode] = strategy


def get_variant_generation_strategy(mode: str) -> VariantGenerationStrategy:
    """Возвращает зарегистрированную стратегию по имени режима."""
    try:
        return MODE_VARIANT_STRATEGIES[mode]
    except KeyError as e:
        raise ValueError(f"Неизвестный mode: {mode!r}") from e


def iter_variants(
    table: TableDDL,
    mode: str,
    column_rules: List[ColumnRule],
    index_rules: List[IndexRule],
    column_order: Optional[Dict[str, int]] = None,
    max_iterations: Optional[int] = None,
) -> Generator[Tuple[TableDDL, VariantMeta], None, None]:
    """
    Главная точка входа. Генерирует варианты TableDDL по заданному mode.

    Args:
        table:          исходная таблица.
        mode:           режим перебора.
        column_rules:   правила для типов/кодеков.
        index_rules:    правила для индексов.
        column_order:   приоритет перебора колонок (для column и index вариантов).
        max_iterations: если задан — обрезает генератор после N вариантов.

    Yields: (variant_table, meta)
    """
    strategy = get_variant_generation_strategy(mode)
    gen = strategy.iter_variants(
        table=table,
        column_rules=column_rules,
        index_rules=index_rules,
        column_order=column_order,
    )
    for idx, (variant, meta) in enumerate(gen):
        if max_iterations is not None and idx >= max_iterations:
            return
        meta.global_index = idx
        yield variant, meta


def total_variants(
    table: TableDDL,
    mode: str,
    column_rules: List[ColumnRule],
    index_rules: List[IndexRule],
    column_order: Optional[Dict[str, int]] = None,
    max_iterations: Optional[int] = None,
) -> int:
    """Подсчитывает количество вариантов без их генерации."""
    strategy = get_variant_generation_strategy(mode)
    n = strategy.total_variants(
        table=table,
        column_rules=column_rules,
        index_rules=index_rules,
        column_order=column_order,
    )

    if max_iterations is not None:
        n = min(n, max_iterations)
    return n
