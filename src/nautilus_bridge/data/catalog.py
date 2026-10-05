from __future__ import annotations

import os
from pathlib import Path

from dotenv import find_dotenv
from dotenv import load_dotenv


def catalog_path() -> Path:
    load_dotenv(find_dotenv(usecwd=True))
    data_root = os.environ.get("DATA_ROOT")
    if not data_root:
        raise ValueError("DATA_ROOT is not set")
    return Path(data_root) / "catalog"
