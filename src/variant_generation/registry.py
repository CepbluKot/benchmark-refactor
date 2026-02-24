"""Registry of variant-generation strategies by mode key."""

from __future__ import annotations

from typing import Dict

from .contracts import VariantGenerationStrategy
from .implementations import (
    CombinedVariantGenerationStrategy,
    IndexesVariantGenerationStrategy,
    SequentialVariantGenerationStrategy,
    TypesVariantGenerationStrategy,
)


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
    """Registers strategy for `mode` in the global registry."""
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
    """Returns registered strategy by mode key."""
    try:
        return MODE_VARIANT_STRATEGIES[mode]
    except KeyError as exc:
        raise ValueError(f"Неизвестный mode: {mode!r}") from exc
