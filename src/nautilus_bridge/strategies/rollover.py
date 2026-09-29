"""Signal when a futures strategy should close before expiry and when it may re-enter.

``update(ts_ns)`` returns CLOSE at ``close_time`` on the expiry day given by
``expiry_date``, is ``frozen`` until the next day, and returns OPEN on the first update
of that day. It reads only the timestamp passed in and the expiry calendar.

Example of wiring in a strategy::

    self.rollover = FuturesRollover()

    def on_bar(self, bar):
        action = self.rollover.update(bar.ts_init)
        if action is RollAction.CLOSE:
            self.on_roll_close()
        elif action is RollAction.OPEN:
            self.on_roll_open(bar)
        if self.rollover.frozen:
            return
        ...  # normal signal handling
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from datetime import time
from enum import Enum

import pandas as pd

from nautilus_bridge.instruments.derivatives.futures.vn30f1m import vn30f_expiry_date

VN_TZ = "Asia/Ho_Chi_Minh"


class RollAction(Enum):
    CLOSE = "close"  # flatten the expiring contract and stop opening positions
    OPEN = "open"  # first bar of the next trading day: re-enter in the new contract


class FuturesRollover:
    """Emit CLOSE at ``close_time`` on the expiry day and OPEN on the next trading day."""

    def __init__(
        self,
        *,
        close_time: time = time(14, 0),
        timezone: str = VN_TZ,
        expiry_date: Callable[[int, int], date] = vn30f_expiry_date,
    ) -> None:
        self._close_time = close_time
        self._timezone = timezone
        self._expiry_date = expiry_date
        self._rolling_since: date | None = None

    @property
    def frozen(self) -> bool:
        """True from the roll close until the first bar of the next trading day."""
        return self._rolling_since is not None

    def update(self, ts_ns: int) -> RollAction | None:
        """Advance with the time of the latest bar; return the roll action due, if any."""
        local = pd.Timestamp(ts_ns, tz="UTC").tz_convert(self._timezone)
        day = local.date()
        if self._rolling_since is not None:
            if day > self._rolling_since:
                self._rolling_since = None
                return RollAction.OPEN
            return None
        if day == self._expiry_date(day.year, day.month) and local.time() >= self._close_time:
            self._rolling_since = day
            return RollAction.CLOSE
        return None
