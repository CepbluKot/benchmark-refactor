from __future__ import annotations

import os
import re
from dataclasses import dataclass


_RELEASE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"required setting {name} is missing")
    return value


def _release_pairs(name: str, default: str) -> frozenset[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for item in os.environ.get(name, default).split(","):
        core_release, separator, plugin_release = item.strip().partition(":")
        if (
            separator != ":"
            or not _RELEASE_ID.fullmatch(core_release)
            or not _RELEASE_ID.fullmatch(plugin_release)
        ):
            raise ValueError(f"invalid release compatibility pair in {name}")
        pairs.add((core_release, plugin_release))
    if not pairs:
        raise ValueError(f"{name} must not be empty")
    return frozenset(pairs)


@dataclass(frozen=True, slots=True)
class ProductSettings:
    database_url: str
    active_study_limit: int
    allowed_release_pairs: frozenset[tuple[str, str]]

    @classmethod
    def from_env(cls) -> ProductSettings:
        limit = int(os.environ.get("M0_ACTIVE_STUDY_LIMIT", "100"))
        if limit < 1 or limit > 100:
            raise ValueError("M0_ACTIVE_STUDY_LIMIT must be between 1 and 100")
        return cls(
            database_url=_required("PRODUCT_DATABASE_URL"),
            active_study_limit=limit,
            allowed_release_pairs=_release_pairs(
                "M0_ALLOWED_RELEASE_PAIRS", "m0-a:m0-a"
            ),
        )


@dataclass(frozen=True, slots=True)
class HatchetSettings:
    token_file: str
    host_port: str
    server_url: str
    tls_strategy: str

    @classmethod
    def from_env(cls) -> HatchetSettings:
        return cls(
            token_file=os.environ.get(
                "HATCHET_CLIENT_TOKEN_FILE", "/run/secrets/hatchet_worker_token"
            ),
            host_port=os.environ.get("HATCHET_CLIENT_HOST_PORT", "hatchet-engine:7070"),
            server_url=os.environ.get(
                "HATCHET_CLIENT_SERVER_URL", "http://hatchet-api:8080"
            ),
            tls_strategy=os.environ.get("HATCHET_CLIENT_TLS_STRATEGY", "none"),
        )
