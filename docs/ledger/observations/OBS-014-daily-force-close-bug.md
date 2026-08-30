---
doc_id: OBS-014
title: Bridge force-closes the position every day at 14:00 instead of only on the contract expiry day
type: observation
owner: research
status: resolved
version: 1.0
components: [6]
tags: [execution, expiry, futures, force-close, milestone-1]
source: "milestone-1 checklist review with owner, 2026-08-30"
design: [STG-6-TRADE-SCHEDULING]
code: [src/trading/strategies/bridge.py]
test: [src/trading/tests/test_bridge.py]
---

# OBS-014 - Bridge Force-Closes Every Day Instead of Only on the Expiry Day

## 1. Finding

The milestone-1 bridge (DEC-008 wiring) calls the force-close branch whenever
local VN time is at/after `force_close_local_time` ("14:00") - i.e. it flattens
the position EVERY trading day. The owner's intended futures semantics: flatten
only on the held contract's expiry day (before settlement, at 14:00, market
close 14:45), block same-day re-entry, and re-enter the next session if the
signal persists. The earlier nox system carried this intent
(`close_positions_on_expiry_day` in its runtime config); the quant_core wiring
dropped it silently (DEC-008 contains no expiry handling; grep for
expiry/settlement/rollover in src/trading found nothing). A daily 14:00 flatten
would make the paper run misrepresent normal-day behavior and distort every
acceptance measurement.

## 2. Resolution

Recorded decision DEC-013: force-close fires only on configured expiry dates
(`force_close_dates`, Asia/Ho_Chi_Minh ISO dates; empty = never), with a
reduce-only entry rule on the expiry day before 14:00, same-day re-entry
blocked by the existing session-closed mechanism, and automatic re-arm the
next day. A declared-date mechanism (`force_close_dates: ["2026-09-03"]`)
simulates an expiry session for the first paper run instead of waiting for the
real contract expiry.

## 3. Impact

- Normal trading days no longer flatten at 14:00.
- The 2026-09-03 paper session can exercise the expiry-day path end to end.
