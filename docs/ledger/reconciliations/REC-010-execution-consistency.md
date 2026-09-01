---
doc_id: REC-010
title: Execution API consistency findings - urgency convention, order-state gaps, pessimistic fill stance
type: reconciliation
owner: research
status: resolved
version: 1.0
components: [6]
tags: [execution, urgency, order-state-machine, consistency, quant-api]
source: "practitioner review 2026-09-01: five consistency findings on the execution module against Component 6 - Trade Scheduling; code fixes applied where cheap, the rest recorded"
design: []
code: [src/quant_api/execution.py]
test: [src/quant_api/tests/test_execution.py]
---

# REC-010 - Execution API consistency findings

## 1. Findings and verdicts

1. **Urgency formula convention.** Canon section 3.1 writes
   `cost_of_waiting = abs(gap) * alpha_decay_speed * value_of_1bp` and
   `cost_of_acting = half_spread + impact(gap)`; the canon's own worked
   example (gap 2, `2 x half_spread`) implies gap-scaled acting cost - the
   formula line and the example disagree. The API follows the worked
   example: both costs are gap-scaled, `impact_bps` is a flat per-contract
   input (no depth-relative impact function yet). Verdict: API convention
   recorded as the interpretation; a depth-relative impact function is
   phase-2.
2. **Order state machine gaps.** The backtest strategy never cancels,
   expires or times out (canon states CANCELLED/REJECTED/TIMEOUT);
   backtest LO has default GTC while the live bridge LO is LIMIT+DAY. The
   offline engine is therefore not a full state-machine mirror. Verdict:
   documented limitation; working-order invariant itself is fixed (the
   guard now clears only on terminal fills).
3. **Pessimistic fill stance (canon 3.3).** "fills count only when price
   crosses an extra tick" is not implemented; LO fills at the limit price
   show zero/benign slippage by construction. Verdict: deferred (fill-model
   customization is phase-2); bar-mode slippage remains uninformative and
   tick-mode MAK is the trustworthy leg.
4. **Provenance honesty.** `marketable_limit` was labelled source="engine"
   although it is a Python plan function (the Rust engine has no execution
   machinery). Fixed: source="python", description states the mirror
   relationship.
5. **Doc drift.** DEC-017's "Nautilus ExecAlgorithm" wording vs the
   strategy-based implementation - the code uses a Nautilus `Strategy`
   subclass (the v1 ExecAlgorithm attach path proved unfit for the
   target-following loop); docstring now states the strategy approach.

## 2. Code fixes applied in this review wave

- No-stacking invariant: `on_order_filled` clears the working guard only on
  terminal fills (partial fills keep the order working).
- `slippage_report`: size buckets by fill QUANTITY (not slippage), adds the
  promised vol-regime split, normalizes the session-hour axis to
  Asia/Ho_Chi_Minh (strings = Hanoi local, ts_ns = UTC), reads
  `fills.jsonl` from session dirs and raises an actionable error for
  bridge-style decisions-only logs.
- `backtest_execution`: guards the catalog tick/depth query against
  cross-instrument leaks; reports realized PnL from the strategy's own fill
  accounting (account balances do not move in the zero-fee sim); enforces
  `max_contracts` on targets; TWAP chunks are time-gated
  (`twap_interval_secs`) in tick mode so `slice_bars` means a horizon, not
  ~0.1s of ticks.

## Related notes

- [DEC-017](DEC-017-quant-api-role-modules.md) - the quant_api contract
- [OBS-017](OBS-017-drawdown-boundary-roundtrip.md) - same review wave
