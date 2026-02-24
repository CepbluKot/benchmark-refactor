"""Metadata provider contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from clickhouse_ddl import TableDDL


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
