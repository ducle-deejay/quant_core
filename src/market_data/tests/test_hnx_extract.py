from __future__ import annotations

from datetime import date

from market_data.sources.hnx.extract import ExchangeDay
from market_data.sources.hnx.extract import extract_day
from market_data.sources.hnx.extract import front_contract


def _row(symbol: str, underlying: str, expiry: str, high: str, low: str, open_: str, close: str, put_through: str, total: str) -> str:
    cells = ["", symbol, underlying, "F", expiry, high, low, open_, close, "1.157,9", "1.006,5",
             "3.161", "0", "151.413", "0", "28", "0", put_through, "0", total, "0", "33.205", close, "-75,7"]
    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


# Values of 2021-01-28 from the HNX derivatives trading results page
RESULTS = "<table>" + "".join([
    _row("VN30F2103", "VN30", "2103", "1.059,5", "1.013,8", "1.058,1", "1.013,8", "0", "756"),
    _row("VN30F2102", "VN30", "2102", "1.050", "1.006,5", "1.050", "1.006,5", "0", "154.602"),
    _row("VN100F2102", "VN100", "2102", "1.200", "1.100", "1.150", "1.120", "0", "10"),
]) + "</table>"


def test_front_contract_is_the_nearest_vn30_expiry_and_volume_excludes_put_through(tmp_path):
    path = tmp_path / "2021-01-28.html"
    path.write_text(RESULTS.replace("<td>154.602</td>", "<td>154.627</td>").replace(
        "<td>0</td><td>0</td><td>154.627</td>", "<td>25</td><td>0</td><td>154.627</td>",
    ))
    assert front_contract(path) == ExchangeDay("VN30F2102", 1050.0, 1050.0, 1006.5, 1006.5, 154_602)


def test_an_unpublished_day_is_not_retained(tmp_path):
    assert extract_day(raw_root=tmp_path, day=date(2026, 11, 5), request=lambda day: "<table></table>") is None
    assert not any(tmp_path.iterdir())
    assert extract_day(raw_root=tmp_path, day=date(2021, 1, 28), request=lambda day: RESULTS) == tmp_path / "2021-01-28.html"


def test_open_zero_marks_the_exchange_day_incomplete():
    assert not ExchangeDay("VN41I1G70004", 0.0, 2012.4, 1981.5, 1991.4, 204_326).has_values
