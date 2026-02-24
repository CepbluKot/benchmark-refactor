"""Compatibility bridge package for `src.variant_generation`."""

from __future__ import annotations

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
_src_pkg = Path(__file__).resolve().parent.parent / "src" / "variant_generation"
if _src_pkg.exists():
    __path__.append(str(_src_pkg))

from src.variant_generation import *  # noqa: F401,F403
