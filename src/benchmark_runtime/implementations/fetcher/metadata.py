"""Fetcher-backed metadata provider implementation."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from src.clickhouse_ddl import TableDDL

from ...contracts.metadata import MetadataProvider


class FetcherMetadataProvider(MetadataProvider):
    """Adapter over existing Fetcher-like objects."""

    def __init__(self, fetcher: Any) -> None:
        self._fetcher = fetcher

    def list_databases(self) -> List[str]:
        return self._fetcher.list_databases()

    def list_tables(self, database: str) -> List[str]:
        return self._fetcher.list_tables(database)

    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        return self._fetcher.fetch_ddl(database, table)

    def fetch_column_sizes(self, database: str, table: str) -> Dict[str, int]:
        fetch_method = getattr(self._fetcher, "fetch_column_sizes", None)
        if fetch_method is None:
            return {}
        return fetch_method(database, table)

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
        fetch_method = getattr(self._fetcher, "fetch_like_tokens", None)
        if fetch_method is None:
            return {}
        return fetch_method(
            database,
            table,
            columns,
            sample_rows_per_column=sample_rows_per_column,
            min_token_length=min_token_length,
            max_token_length=max_token_length,
        )

    def fetch_column_ranges(
        self,
        database: str,
        table: str,
        columns: Sequence[str],
    ) -> Dict[str, Dict[str, str]]:
        fetch_method = getattr(self._fetcher, "fetch_column_ranges", None)
        if fetch_method is None:
            return {}
        return fetch_method(
            database,
            table,
            columns,
        )
