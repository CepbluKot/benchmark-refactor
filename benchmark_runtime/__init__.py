"""Compatibility bridge package for `src.benchmark_runtime`."""

from __future__ import annotations

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
_src_pkg = Path(__file__).resolve().parent.parent / "src" / "benchmark_runtime"
if _src_pkg.exists():
    __path__.append(str(_src_pkg))

from src.benchmark_runtime import *  # noqa: F401,F403
