#!/usr/bin/env python3
"""Idempotently add only Benchmark Studio entries to the live private host files."""

from __future__ import annotations

import json
import argparse
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any


CADDY_SITE = """benchmark.lan.awesomeio.ru {
\timport private_site

\thandle /api/* {
\t\treverse_proxy http://192.168.20.68:18900 {
\t\t\theader_up X-Forwarded-Proto https
\t\t\theader_up X-Forwarded-Host {host}
\t\t}
\t}

\thandle {
\t\treverse_proxy http://192.168.20.68:18901 {
\t\t\theader_up X-Forwarded-Proto https
\t\t\theader_up X-Forwarded-Host {host}
\t\t}
\t}
}
"""

PORTAL_SERVICE: dict[str, Any] = {
    "name": "benchmark.lan.awesomeio.ru",
    "label": "DB Benchmark Preview",
    "role": "Private benchmark Studio preview",
    "location": "VPS → Application VM",
    "links": [{"label": "Open", "url": "https://benchmark.lan.awesomeio.ru/"}],
    "probes": [
        {"type": "https", "url": "https://benchmark.lan.awesomeio.ru/", "timeout": 5},
        {"type": "certificate", "host": "benchmark.lan.awesomeio.ru", "port": 443, "timeout": 5},
    ],
}


def _atomic_write(path: Path, contents: str) -> None:
    original_mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, original_mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def patch_caddyfile(path: Path) -> bool:
    contents = path.read_text(encoding="utf-8")
    domain_header = re.compile(r"(?m)^benchmark\.lan\.awesomeio\.ru\s*\{")
    if domain_header.search(contents):
        if CADDY_SITE.rstrip() in contents:
            return False
        raise ValueError("existing Benchmark Caddy site conflicts with this release")
    separator = "" if not contents or contents.endswith("\n\n") else "\n"
    _atomic_write(path, f"{contents}{separator}{CADDY_SITE}")
    return True


def patch_inventory(path: Path) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("portal inventory schema is not supported")
    services = payload.get("services")
    if not isinstance(services, list):
        raise ValueError("portal inventory has no services list")
    matching = [item for item in services if isinstance(item, dict) and item.get("name") == PORTAL_SERVICE["name"]]
    if matching:
        if len(matching) == 1 and matching[0] == PORTAL_SERVICE:
            return False
        raise ValueError("existing Benchmark portal service conflicts with this release")
    services.append(PORTAL_SERVICE)
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("caddyfiles", nargs=2, type=Path)
    parser.add_argument("inventory", type=Path)
    args = parser.parse_args()
    changed = [patch_caddyfile(path) for path in args.caddyfiles]
    changed.append(patch_inventory(args.inventory))
    print(f"Hosting files updated: {sum(changed)}; existing content preserved.")


if __name__ == "__main__":
    main()
