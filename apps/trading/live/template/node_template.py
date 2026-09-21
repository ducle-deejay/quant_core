"""Config-driven LiveNode template.

Builds a LiveNode from a JSON file: client configs and factories are
restored by import path; configs declaring ``instrument_spec`` get it
loaded from the repo instrument definition when the JSON omits it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import get_type_hints

from nautilus_trader.common import Environment
from nautilus_trader.config import ImportableFactoryConfig, LiveNodeConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.live.config import construct_config
from nautilus_trader.model import TraderId

from nautilus_bridge.instruments.instruments import load_futures_instrument_spec

DEFAULT_SPEC_PATH = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "nautilus_bridge"
    / "instruments"
    / "instrument_definitions"
    / "vn30f1m.hnx.json"
)


def _resolve_import(path: str):
    module_name, _, attribute = path.partition(":")
    value = __import__(module_name, fromlist=[attribute])
    for part in attribute.split("."):
        value = getattr(value, part)
    return value


def _load_clients(entries: dict) -> tuple[dict, dict]:
    clients, factories = {}, {}
    for name, entry in entries.items():
        config_cls = _resolve_import(entry["config"])
        values = dict(entry["values"])
        if "instrument_spec" in get_type_hints(config_cls) and "instrument_spec" not in values:
            values["instrument_spec"] = str(
                load_futures_instrument_spec(values.pop("instrument_spec_path", DEFAULT_SPEC_PATH)),
            )
        clients[name] = construct_config(config_cls, values)
        factories[name] = ImportableFactoryConfig(entry["factory"]).create()
    return clients, factories


def load_node(path: Path) -> LiveNode:
    doc = json.loads(path.read_text())
    data_clients, data_factories = _load_clients(doc.get("data_clients", {}))
    exec_clients, exec_factories = _load_clients(doc.get("exec_clients", {}))
    node_config = LiveNodeConfig(
        environment=getattr(Environment, doc.get("environment", "live").upper()),
        trader_id=TraderId.from_str(doc["trader_id"]),
        data_clients=data_clients,
        exec_clients=exec_clients,
    )
    return LiveNode.build(
        doc["node_name"],
        node_config,
        data_factories=data_factories,
        exec_factories=exec_factories,
    )


if __name__ == "__main__":
    load_node(Path(sys.argv[1])).run()
