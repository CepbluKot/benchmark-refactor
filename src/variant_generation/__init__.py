"""Variant-generation contracts, registry and built-in implementations."""

from .contracts import VariantGenerationStrategy
from .implementations import (
    CombinedVariantGenerationStrategy,
    IndexesVariantGenerationStrategy,
    SequentialVariantGenerationStrategy,
    TypesVariantGenerationStrategy,
)
from .registry import (
    MODE_VARIANT_STRATEGIES,
    get_variant_generation_strategy,
    register_variant_generation_strategy,
)
from .types import VariantMeta

__all__ = [
    "CombinedVariantGenerationStrategy",
    "get_variant_generation_strategy",
    "IndexesVariantGenerationStrategy",
    "MODE_VARIANT_STRATEGIES",
    "register_variant_generation_strategy",
    "SequentialVariantGenerationStrategy",
    "TypesVariantGenerationStrategy",
    "VariantGenerationStrategy",
    "VariantMeta",
]
