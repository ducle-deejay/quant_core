"""Pool folder - the research -> portfolio handoff artifact (DEC-017).

One JSON file per passing alpha (canonical DSL string + metadata + spec
sheet), plus an ``index.json`` listing every entry. The Portfolio Researcher
loads the pool by folder path; the live configuration is generated from the
same folder, so the folder is the single source of truth for the pool.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from quant_api.core.config import REPO_ROOT

#: Default pool folder (<repo>/data/pool).
DEFAULT_POOL_DIR = REPO_ROOT / "data" / "pool"


@dataclass(frozen=True)
class PoolEntry:
    """One passing alpha in the pool folder."""

    alpha_id: str
    dsl: str  # canonical DSL string (validate_expression_py round-trip)
    author: str = "research"
    tags: tuple[str, ...] = ()
    family: str | None = None
    source: str = "seed"  # "seed" (hand-written) | "ga" (bred)
    created: str = field(default_factory=lambda: date.today().isoformat())
    spec_sheet: dict | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tags"] = list(self.tags)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PoolEntry":
        fields = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        fields["tags"] = tuple(fields.get("tags", ()) or ())
        return cls(**fields)


def _pool_root(root: Path | None) -> Path:
    return Path(root) if root is not None else DEFAULT_POOL_DIR


def write_pool_entry(entry: PoolEntry, root: Path | None = None) -> Path:
    """Write one alpha file; does not touch the index (see write_pool_index)."""
    alphas_dir = _pool_root(root) / "alphas"
    alphas_dir.mkdir(parents=True, exist_ok=True)
    path = alphas_dir / f"{entry.alpha_id}.json"
    path.write_text(json.dumps(entry.to_dict(), indent=2, ensure_ascii=False) + "\n")
    return path


def write_pool_index(entries: list[PoolEntry], root: Path | None = None) -> Path:
    """(Re)generate ``index.json`` from the given entries (usually all pool)."""
    d = _pool_root(root)
    d.mkdir(parents=True, exist_ok=True)
    index = {
        "generated": date.today().isoformat(),
        "count": len(entries),
        "alphas": [e.to_dict() for e in entries],
    }
    path = d / "index.json"
    path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    return path


def load_pool(root: Path | None = None) -> list[PoolEntry]:
    """Load every alpha file from the pool folder (sorted by alpha_id)."""
    alphas_dir = _pool_root(root) / "alphas"
    if not alphas_dir.exists():
        return []
    entries = []
    for f in sorted(alphas_dir.glob("*.json")):
        try:
            entries.append(PoolEntry.from_dict(json.loads(f.read_text())))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"corrupt pool entry {f}: {exc}") from exc
    return entries


def load_index(root: Path | None = None) -> dict:
    """Load ``index.json`` if present, else {} (index is a cache of the folder)."""
    path = _pool_root(root) / "index.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())
