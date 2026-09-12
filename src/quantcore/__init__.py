"""quantcore - role-scoped research API for the quant_core framework.
Entry points take their data explicitly; only caller-invoked ``save()`` writes artifacts.
"""

from __future__ import annotations

import importlib

__version__ = "0.1.0"

_ROLE_MODULES = ("alpha", "execution", "portfolio", "risk")


def __getattr__(name: str):
    """Lazily bind a role module on first access (PEP 562)."""
    if name in _ROLE_MODULES:
        module = importlib.import_module(f"quantcore.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_ROLE_MODULES))
