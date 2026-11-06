from __future__ import annotations

import html
import json
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import truststore
import urllib3


# The data request behind https://hnx.vn/vi-vn/phai-sinh/ket-qua-giao-dich.html; HDTLCSCP selects index futures
HNX_RESULTS_URL = "https://hnx.vn/ModulePhaiSinh/KetQuaGiaoDichV2/ListSearch_Datas"
HNX_HEADERS = {
    "Referer": "https://hnx.vn/vi-vn/phai-sinh/ket-qua-giao-dich.html",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0",
}
# Cell positions in a result row, read from the page's column headers
SYMBOL, UNDERLYING, EXPIRY_MONTH, HIGH, LOW, OPEN, CLOSE = 1, 2, 4, 5, 6, 7, 8
PUT_THROUGH_VOLUME, TOTAL_VOLUME = 17, 19
ROW_CELLS = 24

ResultsRequest = Callable[[date], str]


@dataclass(frozen=True)
class ExchangeDay:
    """The front VN30 futures contract's daily result; volume is matched trading, put-through excluded."""

    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int

    @property
    def has_values(self) -> bool:
        # HNX has published days with open 0 for every contract while the ATO matched (docs/data_validation/vn30f1m)
        return self.volume > 0 and min(self.open, self.high, self.low, self.close) > 0


def request_hnx_results(day: date) -> str:
    """The HTML table of one day's HNX index futures results."""
    http = urllib3.PoolManager(ssl_context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    try:
        response = http.request(
            "POST",
            HNX_RESULTS_URL,
            fields={
                "p_date": f"{day:%d/%m/%Y}",
                "p_keysearch": "-1|0|",
                "p_orderby": "",
                "p_ordertype": "",
                "p_currentpage": "1",
                "p_type_sanpham": "HDTLCSCP",
                "p_record_on_page": "50",
            },
            encode_multipart=False,
            headers=HNX_HEADERS,
            timeout=urllib3.Timeout(connect=30.0, read=60.0),
        )
        if not 200 <= response.status < 300:
            raise RuntimeError(f"HNX results request failed with status={response.status}")
        payload = json.loads(response.data)
    finally:
        http.clear()
    return payload["Content"]


def extract_day(*, raw_root: Path, day: date, request: ResultsRequest = request_hnx_results) -> Path | None:
    """Retain one day's results as raw HTML; None while HNX has not published the day."""
    path = raw_root / f"{day.isoformat()}.html"
    if path.exists():
        return path
    content = request(day)
    if not _rows(content):
        return None
    raw_root.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
    return path


def front_contract(path: Path) -> ExchangeDay:
    """The VN30 futures contract with the nearest expiry month; on an expiry day, the contract expiring that day."""
    rows = [row for row in _rows(path.read_text(encoding="utf-8")) if row[UNDERLYING] == "VN30"]
    if not rows:
        raise ValueError(f"No VN30 futures row in {path}")
    row = min(rows, key=lambda cells: int(cells[EXPIRY_MONTH]))
    return ExchangeDay(
        symbol=row[SYMBOL],
        open=_number(row[OPEN]),
        high=_number(row[HIGH]),
        low=_number(row[LOW]),
        close=_number(row[CLOSE]),
        volume=int(_number(row[TOTAL_VOLUME]) - _number(row[PUT_THROUGH_VOLUME])),
    )


def _rows(content: str) -> list[list[str]]:
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", content, flags=re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", cell)).strip() for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
        if len(cells) == ROW_CELLS:
            rows.append(cells)
    return rows


def _number(text: str) -> float:
    """Parse the page's Vietnamese number format: '.' groups thousands, ',' marks decimals."""
    return float(text.replace(".", "").replace(",", ".")) if text else 0.0
