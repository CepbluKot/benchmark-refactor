"""Shared DTOs for DDL variant generation."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from src.column_variants import ColumnVariantMeta
from src.index_variants import IndexVariantMeta


class VariantMeta(BaseModel):
    """Metadata of one generated table variant."""

    global_index: int
    mode: str
    execution_uuid: Optional[str] = None
    parent_variant_table: Optional[str] = None
    phase_name: Optional[str] = None
    stage_column_name: Optional[str] = None
    merged_columns: Optional[List[str]] = None
    table_index_granularity: Optional[int] = None
    column_meta: Optional[ColumnVariantMeta] = None
    index_meta: Optional[IndexVariantMeta] = None

    @property
    def column_choices(self):
        """Returns selected column alternatives for this variant, if present."""
        return self.column_meta.column_choices if self.column_meta else {}

    @property
    def index_choices(self):
        """Returns selected index alternatives for this variant, if present."""
        return self.index_meta.index_choices if self.index_meta else {}
