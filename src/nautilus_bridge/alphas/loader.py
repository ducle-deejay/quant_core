from __future__ import annotations

import importlib.util
from pathlib import Path

from nautilus_bridge.alphas.sources import AlphaFn

ALPHA_FUNCTION = "alpha"


def load_alpha(path: str) -> AlphaFn:
    file = Path(path)
    spec = importlib.util.spec_from_file_location(file.stem, file)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load alpha file {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    alpha = getattr(module, ALPHA_FUNCTION, None)
    if not callable(alpha):
        raise ValueError(f"Alpha file {path} must define a function named {ALPHA_FUNCTION!r}")
    return alpha
