"""Metadata contract and backward-compatible exports."""

from .contracts.metadata import MetadataProvider
from .implementations.fetcher.metadata import FetcherMetadataProvider

__all__ = ["MetadataProvider", "FetcherMetadataProvider"]
