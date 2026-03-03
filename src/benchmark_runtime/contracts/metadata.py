"""Metadata provider contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Sequence

from src.clickhouse_ddl import TableDDL


class MetadataProvider(ABC):
    """Backend-agnostic metadata provider contract."""

    @abstractmethod
    def list_databases(self) -> List[str]:
        """Returns databases for selectors like `databases="*"`."""
        pass

    @abstractmethod
    def list_tables(self, database: str) -> List[str]:
        """Returns tables for a concrete database."""
        pass

    @abstractmethod
    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        """Fetches and parses table DDL to `TableDDL`."""
        pass

    def fetch_column_sizes(self, database: str, table: str) -> Dict[str, int]:
        """Returns optional `column_name -> compressed_bytes` map."""
        return {}

    def fetch_like_tokens(
        self,
        database: str,
        table: str,
        columns: Sequence[str],
        *,
        sample_rows_per_column: int = 20,
        min_token_length: int = 3,
        max_token_length: int = 24,
    ) -> Dict[str, Dict[str, str]]:
        """
        Returns optional LIKE probes per column.

        Expected payload:
          {
            "column_name": {
              "hit_token": "...",   # token guaranteed to have at least one match
              "miss_token": "...",  # token guaranteed to have zero matches
            }
          }
        """
        return {}
