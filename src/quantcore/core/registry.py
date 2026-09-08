"""Extension registries (DEC-017).

One registry per slot (``combine_methods``, ``sizing_methods``,
``risk_policies``, ``execution_algorithms``, ``ga_fitness``). Defaults are
pre-registered with ``source="engine"`` (they delegate to the Rust engine
bindings); practitioners register research methods as plain Python
functions (``source="python"``). Provenance is recorded so a validated
Python method can later be migrated into the Rust traits or live wiring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Method:
    """One registered method with provenance."""

    name: str
    fn: Callable[..., Any]
    source: str  # "engine" (Rust-backed default) | "python" (research)
    description: str = ""


class Registry:
    """Name -> Method store with strict duplicate handling."""

    def __init__(self, slot: str) -> None:
        self.slot = slot
        self._methods: dict[str, Method] = {}

    def register(
        self,
        name: str,
        fn: Callable[..., Any],
        *,
        source: str = "python",
        description: str = "",
        replace: bool = False,
    ) -> Callable[..., Any]:
        if not name or not isinstance(name, str):
            raise ValueError(f"method name must be a non-empty string (got {name!r})")
        if not callable(fn):
            raise ValueError(f"{self.slot} method {name!r} must be callable")
        if source not in ("engine", "python"):
            raise ValueError(f"source must be 'engine' or 'python' (got {source!r})")
        if name in self._methods and not replace:
            raise ValueError(
                f"{self.slot} method {name!r} already registered"
                f" (source={self._methods[name].source})"
            )
        self._methods[name] = Method(name, fn, source, description)
        return fn

    def get(self, name: str) -> Method:
        try:
            return self._methods[name]
        except KeyError:
            raise KeyError(
                f"unknown {self.slot} method {name!r};"
                f" registered: {sorted(self._methods)}"
            ) from None

    def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        return self.get(name).fn(*args, **kwargs)

    def names(self) -> list[str]:
        return sorted(self._methods)

    def describe(self) -> list[dict[str, str]]:
        return [
            {"name": m.name, "source": m.source, "description": m.description}
            for m in self._methods.values()
        ]
