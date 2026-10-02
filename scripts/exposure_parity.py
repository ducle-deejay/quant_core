from __future__ import annotations

import pandas as pd


def exposure_mismatches(baseline: pd.Series, candidate: pd.Series) -> pd.DataFrame:
    frame = pd.concat({"baseline": baseline, "candidate": candidate}, axis=1)
    same = (frame["baseline"] == frame["candidate"]) | (
        frame["baseline"].isna() & frame["candidate"].isna()
    )
    return frame[~same]
