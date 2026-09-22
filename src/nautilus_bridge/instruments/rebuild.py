import argparse
import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.core.datetime import unix_nanos_to_iso8601
from nautilus_trader.model import FuturesContract, PerpetualContract
from nautilus_trader.persistence import ParquetDataCatalog


CATALOG_PATH = Path(__file__).resolve().parents[3] / "data" / "catalog"
INSTRUMENTS_PATH = CATALOG_PATH / "data" / "instruments"
PRESERVED_FIELDS = {"activation_ns", "expiration_ns", "ts_event", "ts_init", "info"}


def load_spec(filename: str):
    matches = list(Path(__file__).parent.rglob(filename))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one specification named {filename}, found {len(matches)}")

    spec = importlib.util.spec_from_file_location("instrument_spec", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def matches(instrument, current: dict, specification) -> bool:
    specification_definition = specification.to_dict()
    return (
        instrument.id.venue == specification.id.venue
        and current["underlying"] == specification_definition["underlying"]
        and current["asset_class"] == specification_definition["asset_class"]
    )


def build_definition(module, instrument, current: dict) -> dict:
    if isinstance(instrument, FuturesContract):
        return module.build_monthly_futures_contract(
            current["raw_symbol"],
            activation=unix_nanos_to_iso8601(current["activation_ns"]),
            expiration=unix_nanos_to_iso8601(current["expiration_ns"]),
            ts_event=current["ts_event"],
            ts_init=current["ts_init"],
            info=current["info"],
        ).to_dict()

    if isinstance(instrument, PerpetualContract):
        return module.build_continuous_futures_contract(
            symbol=current["raw_symbol"],
            ts_event=current["ts_event"],
            ts_init=current["ts_init"],
        ).to_dict()

    return {}


def changed_fields(current: dict, rebuilt_definition: dict) -> dict:
    return {
        name: value
        for name, value in rebuilt_definition.items()
        if name in current and name not in PRESERVED_FIELDS and current[name] != value
    }


def instrument_path(current: dict, output: Path = INSTRUMENTS_PATH) -> Path:
    stamp = unix_nanos_to_iso8601(current["ts_init"]).replace(":", "-").replace(".", "-")
    directory = current["id"].replace("/", "").replace("^", "_")
    return output / directory / f"{stamp}_{stamp}.parquet"


def write_changes(source: Path, output: Path, changes: dict) -> None:
    table = pq.read_table(source)
    row = table.to_pylist()[0]
    for name, value in changes.items():
        row[name] = json.dumps(value, separators=(",", ":")).encode() if name == "info" else value
    output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([row], schema=table.schema), output)


def rebuild(spec_filename: str, output: Path, apply: bool) -> None:
    module = load_spec(spec_filename)
    specification = module.build_continuous_futures_contract()

    catalog = ParquetDataCatalog(str(CATALOG_PATH))
    for instrument in catalog.instruments():
        current = instrument.to_dict()
        if not matches(instrument, current, specification):
            continue

        rebuilt_definition = build_definition(module, instrument, current)
        changes = changed_fields(current, rebuilt_definition)
        if not changes:
            continue

        source = instrument_path(current)
        destination = instrument_path(current, output)
        print(f"{destination}: {', '.join(changes)}")
        if apply:
            write_changes(source, destination, changes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec_filename")
    parser.add_argument("--output", type=Path, default=INSTRUMENTS_PATH)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rebuild(args.spec_filename, args.output, args.apply)


if __name__ == "__main__":
    main()
