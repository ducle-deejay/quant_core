"""Extension registries (one :class:`Registry` per method slot)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeVar, cast

T = TypeVar("T")

__all__ = ["Method", "Registry"]


@dataclass(frozen=True)
class Method:
    """One registered method with provenance."""

    name: str
    fn: object
    source: str  # "engine" (Rust-backed default) | "python" (research)
    description: str = ""
    capability: str | None = None


class Registry:
    """Name -> Method store with strict duplicate handling."""

    def __init__(
        self,
        slot: str,
        *,
        contract: type | None = None,
        capability: str | None = None,
        adapter: Callable[[Callable[..., Any]], object] | None = None,
    ) -> None:
        self.slot = slot
        self.contract = contract
        self.capability = capability
        self.adapter = adapter
        self._methods: dict[str, Method] = {}

    def register(
        self,
        name: str,
        fn: T,
        *,
        source: str = "python",
        description: str = "",
        replace: bool = False,
    ) -> T:
        if not name or not isinstance(name, str):
            raise ValueError(f"method name must be a non-empty string (got {name!r})")
        implementation: object = fn
        if self.contract is not None and not isinstance(fn, self.contract):
            if not callable(fn) or self.adapter is None:
                required = self.capability or self.contract.__name__
                raise ValueError(
                    f"{self.slot} method {name!r} must implement {required}; "
                    "register an object with the required method or a callable "
                    "supported by this registry's narrow adapter"
                )
            implementation = self.adapter(cast(Callable[..., Any], fn))
        if self.contract is None and not callable(fn):
            raise ValueError(f"{self.slot} method {name!r} must be callable")
        if self.contract is not None:
            capability = self.capability
            if capability and not callable(getattr(implementation, capability, None)):
                raise ValueError(
                    f"{self.slot} method {name!r} must provide callable {capability}(...); "
                    f"got {type(fn).__name__}"
                )
        if source not in ("engine", "python"):
            raise ValueError(f"source must be 'engine' or 'python' (got {source!r})")
        if name in self._methods and not replace:
            raise ValueError(
                f"{self.slot} method {name!r} already registered"
                f" (source={self._methods[name].source})"
            )
        self._methods[name] = Method(name, implementation, source, description, self.capability)
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
        method = self.get(name)
        if method.capability is not None:
            return getattr(method.fn, method.capability)(*args, **kwargs)
        if callable(method.fn):
            return method.fn(*args, **kwargs)
        raise TypeError(f"registered {self.slot} method {name!r} is not callable")

    def names(self) -> list[str]:
        return sorted(self._methods)

    def describe(self) -> list[dict[str, str]]:
        return [
            {"name": m.name, "source": m.source, "description": m.description}
            for m in self._methods.values()
        ]
