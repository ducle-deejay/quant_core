"""Cross-role artifact schemas + IO (pool, weights, trial ledger, reports)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .instruments import Instrument

#: Repository root (src/core/artifacts.py -> parents[2]).
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Default artifact roots (all under <repo>/data).
DEFAULT_RESEARCH_DIR = REPO_ROOT / "data" / "research"
DEFAULT_POOL_DIR = REPO_ROOT / "data" / "pool"

#: Only pool schema this module reads/writes.
POOL_SCHEMA_VERSION = "2"

__all__ = [
    "DEFAULT_POOL_DIR",
    "DEFAULT_RESEARCH_DIR",
    "POOL_SCHEMA_VERSION",
    "AlphaPool",
    "Composite",
    "PoolEntry",
    "PoolSchemaError",
    "SpecSheet",
    "TargetSeries",
    "TearSheet",
    "WeightsArtifact",
    "Window",
    "append_trial_ledger",
]


class PoolSchemaError(ValueError):
    """Raised when a pool file carries a ``schema_version`` other than "2"."""


class WindowMismatch(ValueError):
    """Raised when an artifact's :class:`Window` does not match the data it
    is applied to (instrument, bar type, start, end, or bar count differ)."""


@dataclass(frozen=True)
class Window:
    """The exact data window an artifact was computed over.

    Attributes
    ----------
    instrument_id : str
        Nautilus instrument id, e.g. ``"VN30F1M.HNX"``.
    bar_type : str
        Nautilus bar type string, e.g. ``"VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL"``.
    start : pandas.Timestamp
        Window start (UTC).
    end : pandas.Timestamp
        Window end inclusive (UTC).
    n_bars : int
        Number of bars in the window.
    """

    instrument_id: str
    bar_type: str
    start: pd.Timestamp
    end: pd.Timestamp
    n_bars: int


@dataclass(frozen=True)
class TearSheet:
    """Evaluation report for one alpha (Component 1 + Component 2 output)."""

    alpha_id: str
    dsl: str
    metrics: dict  # sharpe, max drawdown, IC ladder, walk-forward, cost drag, ...
    verdict: str  # "IN" | "OUT"
    reasons: tuple[str, ...] = ()
    provenance: dict = field(default_factory=dict)  # method/config versions
    generated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        """Return a JSON-safe dict (tuples -> lists)."""
        d = asdict(self)
        d["reasons"] = list(self.reasons)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TearSheet":
        """Rebuild from :meth:`to_dict` output (lists -> tuples)."""
        return cls(**{**d, "reasons": tuple(d.get("reasons", ()) or ())})

    def to_json(self, path: str | Path) -> Path:
        """Write the report to ``path`` and return it."""
        p = Path(path)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n")
        return p


@dataclass(frozen=True)
class SpecSheet:
    """Component 2 PASS artifact: expectations consumed by portfolio
    (capacity, expected Sharpe, holding period), risk (divergence gauges,
    expected IC and the cost model in bp) and the live kill criteria."""

    alpha_id: str
    expected_holding_period_bars: int
    expected_net_sharpe: float
    capacity_contracts: int
    regime_notes: str = ""
    kill_criteria: dict = field(default_factory=dict)
    expected_ic: dict[str, float] = field(default_factory=dict)  # horizon -> IC
    cost_model_bps: float = 2.294

    def to_dict(self) -> dict:
        """Return a JSON-safe dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SpecSheet":
        """Rebuild from :meth:`to_dict` output."""
        return cls(**d)


@dataclass
class PoolEntry:
    """One passing alpha in the pool folder (JSON round-trippable)."""

    alpha_id: str
    dsl: str  # canonical DSL string (validate_expression_py round-trip)
    author: str = "research"
    tags: tuple[str, ...] = ()
    family: str | None = None
    source: str = "seed"  # "seed" (hand-written) | "ga" (bred)
    created: str = field(default_factory=lambda: date.today().isoformat())
    schema_version: str = POOL_SCHEMA_VERSION
    tear_sheet: TearSheet | None = None
    spec_sheet: SpecSheet | None = None

    def to_dict(self) -> dict:
        """Return a nested, JSON-safe dict (tuples -> lists)."""
        return {
            "alpha_id": self.alpha_id,
            "dsl": self.dsl,
            "author": self.author,
            "tags": list(self.tags),
            "family": self.family,
            "source": self.source,
            "created": self.created,
            "schema_version": self.schema_version,
            "tear_sheet": self.tear_sheet.to_dict() if self.tear_sheet else None,
            "spec_sheet": self.spec_sheet.to_dict() if self.spec_sheet else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PoolEntry":
        """Rebuild from :meth:`to_dict` output (lists -> tuples)."""
        tear_sheet = d.get("tear_sheet")
        spec_sheet = d.get("spec_sheet")
        return cls(
            alpha_id=d["alpha_id"],
            dsl=d["dsl"],
            author=d.get("author", "research"),
            tags=tuple(d.get("tags", ()) or ()),
            family=d.get("family"),
            source=d.get("source", "seed"),
            created=d.get("created", date.today().isoformat()),
            schema_version=d.get("schema_version", POOL_SCHEMA_VERSION),
            tear_sheet=TearSheet.from_dict(tear_sheet) if tear_sheet else None,
            spec_sheet=SpecSheet.from_dict(spec_sheet) if spec_sheet else None,
        )


@dataclass
class AlphaPool:
    """The research -> portfolio handoff pool (folder-backed).

    Attributes
    ----------
    instrument : str
        Instrument symbol the pool was bred for (e.g. ``"VN30F1M"``).
    entries : list[PoolEntry]
        Pool entries in index order.
    """

    instrument: str
    entries: list[PoolEntry] = field(default_factory=list)

    def add(self, entry: PoolEntry) -> None:
        """Append one entry in memory; call :meth:`save` to persist.

        Parameters
        ----------
        entry : PoolEntry
            The entry to append.
        """
        self.entries.append(entry)

    def save(self, root: Path | None = None) -> Path:
        """Write ``alphas/<alpha_id>.json`` per entry plus ``index.json``.

        Parameters
        ----------
        root : pathlib.Path | None
            Pool folder; ``None`` uses :data:`DEFAULT_POOL_DIR`.

        Returns
        -------
        pathlib.Path
            The pool folder that was written.
        """
        pool_root = Path(root) if root is not None else DEFAULT_POOL_DIR
        alphas_dir = pool_root / "alphas"
        alphas_dir.mkdir(parents=True, exist_ok=True)
        for entry in self.entries:
            path = alphas_dir / f"{entry.alpha_id}.json"
            path.write_text(
                json.dumps(entry.to_dict(), indent=2, ensure_ascii=False) + "\n"
            )
        index = {
            "generated": date.today().isoformat(),
            "instrument": self.instrument,
            "schema_version": POOL_SCHEMA_VERSION,
            "count": len(self.entries),
            "alphas": [entry.to_dict() for entry in self.entries],
        }
        (pool_root / "index.json").write_text(
            json.dumps(index, indent=2, ensure_ascii=False) + "\n"
        )
        return pool_root

    @classmethod
    def load(cls, root: Path | None = None) -> "AlphaPool":
        """Load every alpha file from the pool folder (sorted by alpha_id).

        Parameters
        ----------
        root : pathlib.Path | None
            Pool folder; ``None`` uses :data:`DEFAULT_POOL_DIR`.

        Returns
        -------
        AlphaPool
            The loaded pool; ``instrument`` comes from ``index.json`` when
            present, else ``""``.

        Raises
        ------
        PoolSchemaError
            If an alpha file's ``schema_version`` is not ``"2"``; the
            message instructs re-delivery with the current schema.
        ValueError
            If an alpha file is not readable JSON.
        """
        pool_root = Path(root) if root is not None else DEFAULT_POOL_DIR
        index_path = pool_root / "index.json"
        instrument = ""
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
            instrument = str(index.get("instrument", ""))
        entries: list[PoolEntry] = []
        for path in sorted((pool_root / "alphas").glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            schema_version = payload.get("schema_version")
            if schema_version != POOL_SCHEMA_VERSION:
                raise PoolSchemaError(
                    f"pool entry {path.name} has schema_version "
                    f"{schema_version!r}, expected {POOL_SCHEMA_VERSION!r}; "
                    "re-deliver the pool with the current schema"
                )
            entries.append(PoolEntry.from_dict(payload))
        return cls(instrument=instrument, entries=entries)


@dataclass(frozen=True)
class Composite:
    """One composite score series plus full provenance of its construction.

    Raises
    ------
    ValueError
        If ``alpha_ids``/``weights`` lengths differ or ``scores`` is not
        finite.
    """

    alpha_ids: tuple[str, ...]
    weights: tuple[float, ...]
    scores: np.ndarray  # z-units
    window: Window
    method: str

    def __post_init__(self) -> None:
        if len(self.alpha_ids) != len(self.weights):
            raise ValueError(
                "alpha_ids and weights must have equal length "
                f"({len(self.alpha_ids)} != {len(self.weights)})"
            )
        if not np.all(np.isfinite(np.asarray(self.scores))):
            raise ValueError("scores must be finite")


@dataclass(frozen=True)
class TargetSeries:
    """A signed target-contract series over one data window."""

    ts: pd.DatetimeIndex  # UTC, sorted
    target_contracts: np.ndarray  # int
    window: Window
    instrument: Instrument

    def to_frame(self) -> pd.DataFrame:
        """Return a DataFrame with columns ``ts`` and ``target_contracts``.

        Returns
        -------
        pandas.DataFrame
            One row per timestamp, targets as int.
        """
        return pd.DataFrame(
            {
                "ts": self.ts,
                "target_contracts": np.asarray(self.target_contracts, dtype=np.int64),
            }
        )

    @classmethod
    def from_arrays(
        cls,
        ts: pd.DatetimeIndex,
        target_contracts: np.ndarray,
        window: Window,
        instrument: Instrument,
    ) -> "TargetSeries":
        """Build from aligned arrays with validation.

        Parameters
        ----------
        ts : pandas.DatetimeIndex
            Timezone-aware timestamps; normalized to UTC and required to be
            sorted ascending.
        target_contracts : numpy.ndarray
            Signed integer contract counts, same length as ``ts``.
        window : Window
            The data window the series was computed over.
        instrument : Instrument
            Instrument the targets are denominated in.

        Returns
        -------
        TargetSeries
            The validated series.

        Raises
        ------
        ValueError
            If ``ts`` is timezone-naive, unsorted, or its length differs
            from ``target_contracts``.
        """
        ts_index = pd.DatetimeIndex(ts)
        if ts_index.tz is None:
            raise ValueError("ts must be timezone-aware (UTC)")
        ts_index = ts_index.tz_convert("UTC")
        if not ts_index.is_monotonic_increasing:
            raise ValueError("ts must be sorted ascending")
        contracts = np.asarray(target_contracts).astype(np.int64)
        if len(contracts) != len(ts_index):
            raise ValueError(
                f"ts and target_contracts lengths differ ({len(ts_index)} != {len(contracts)})"
            )
        return cls(
            ts=ts_index,
            target_contracts=contracts,
            window=window,
            instrument=instrument,
        )


@dataclass(frozen=True)
class WeightsArtifact:
    """Refit weights handed from research to the live portfolio config."""

    generated: str
    method: str
    weights: dict[str, float]
    window: Window | None

    def save(self, root: Path | None = None) -> Path:
        """Persist to ``<root>/weights.json`` (JSON-safe, nested window).

        Parameters
        ----------
        root : pathlib.Path | None
            Folder to write into; ``None`` uses :data:`DEFAULT_POOL_DIR`.

        Returns
        -------
        pathlib.Path
            The ``weights.json`` path that was written.
        """
        folder = Path(root) if root is not None else DEFAULT_POOL_DIR
        path = folder / "weights.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated": self.generated,
            "method": self.method,
            "weights": self.weights,
            "window": _window_to_dict(self.window),
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return path

    @classmethod
    def load(cls, root: Path | None = None) -> "WeightsArtifact":
        """Load from ``<root>/weights.json``.

        Parameters
        ----------
        root : pathlib.Path | None
            Folder to read from; ``None`` uses :data:`DEFAULT_POOL_DIR`.

        Returns
        -------
        WeightsArtifact
            The loaded artifact.

        Raises
        ------
        FileNotFoundError
            If ``weights.json`` does not exist under ``root``.
        """
        folder = Path(root) if root is not None else DEFAULT_POOL_DIR
        path = folder / "weights.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            generated=payload["generated"],
            method=payload["method"],
            weights=dict(payload["weights"]),
            window=_window_from_dict(payload.get("window")),
        )


def append_trial_ledger(entry: dict, root: Path | None = None) -> Path:
    """Append one trial record as a JSONL line (append-only).

    Consumers: deflated-threshold trial count, mining family priors,
    post-mortem. Entry should carry at least: alpha_id, dsl, date, verdict,
    metrics summary, provenance.

    Parameters
    ----------
    entry : dict
        JSON-serializable trial record.
    root : pathlib.Path | None
        Folder holding ``trial_ledger.jsonl``; ``None`` uses
        :data:`DEFAULT_RESEARCH_DIR`.

    Returns
    -------
    pathlib.Path
        The ledger path that was appended to.
    """
    path = Path(root or DEFAULT_RESEARCH_DIR) / "trial_ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def _window_to_dict(window: Window | None) -> dict | None:
    """Serialize a Window (timestamps -> ISO strings); None-safe."""
    if window is None:
        return None
    return {
        "instrument_id": window.instrument_id,
        "bar_type": window.bar_type,
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "n_bars": window.n_bars,
    }


def _window_from_dict(payload: dict | None) -> Window | None:
    """Rebuild a Window from :func:`_window_to_dict` output; None-safe."""
    if payload is None:
        return None
    return Window(
        instrument_id=payload["instrument_id"],
        bar_type=payload["bar_type"],
        start=pd.Timestamp(payload["start"]),
        end=pd.Timestamp(payload["end"]),
        n_bars=int(payload["n_bars"]),
    )
