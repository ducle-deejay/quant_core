---
doc_id: PLAN-003
title: Batch Verification Script Specification
type: specification
owner: research
status: approved
version: 1.0
components: [0, 1, 2]
tags: [verification, batch, throughput, screening-funnel]
source: "discussion: framework testing via mass parallel batch instead of sequential single-alpha"
---

# Batch Verification Script Specification

## 1. Purpose

Validate that the QuantCore framework handles production-scale load by running
a large batch of alpha expressions through the entire pipeline on real VN30F1M
data in a single execution. Measures throughput at every step and reports the
screening survival funnel.

This is how Chinese shops test their infrastructure: not one alpha at a time,
but mass parallel batches measuring system-level performance.

## 2. Script flow

    Step 1  Load VN30F1M.csv                    -> data map {close, volume}
    Step 2  GA breeds 200+ expressions           -> population from seed crossover
    Step 3  Parse all -> ASTs                   -> measure parse throughput
    Step 4  Build shared DAG                    -> measure dedup ratio
    Step 5  Execute batch -> score matrix        -> measure throughput (alphas/sec)
    Step 6  Canonical mapping (vectorised)       -> positions for ALL alphas
    Step 7  PnL identity (broadcasting)          -> net PnL matrix
    Step 8  Metrics for ALL                     -> Sharpe, IC, TO per alpha
    Step 9  Screening funnel                    -> % passing each gate condition

## 3. Output report format

    === THROUGHPUT ===
      Expressions parsed:     N in X ms       (N expr/ms)
      Unique DAG nodes:       M (dedup saved Y% of computation)
      Score matrix:           N x T bars computed in X ms
      Canonical mapping:      N alphas in X ms
      Metrics computed:       N in X ms
      TOTAL WALL TIME:        X seconds for N alphas

    === SCREENING FUNNEL ===
      Total candidates:            N
      IC abs(mean) > 0.02:         ~N survive
      Cost drag < 40% gross:       ~N survive
      Walk-forward > 60% positive: ~N survive
      All gates combined:          ~N FINAL SURVIVORS

    === TOP 5 CANDIDATES BY FITNESS ===
      #1: fitness=X.XX, IC=0.0XX, Sharpe=X.XX, TO=XXXX
          DSL: "ts_rank(volume, 15) * ts_zscore(...)"

## 4. What each measurement validates

| Measurement | Question answered |
|---|---|
| Dedup ratio | Does the shared computation graph actually save work? |
| Parse throughput | Can the parser handle hundreds of expressions fast enough? |
| Execution throughput | Is batch faster than per-alpha loop? By how much? |
| Canonical mapping speed | Is vectorised mapping viable at production scale? |
| Screening funnel | What percentage of candidates survive each gate? |
| Top candidates | Are any worth deeper evaluation, or is everything noise? |

These questions cannot be answered by testing one alpha at a time.

## 5. Implementation notes

- File: research/batch_verify.py or src/bin/batch_verify.rs (Rust preferred)
- Data source: data/VN30F1M.csv (472809 one-minute bars, real data)
- Expression generation: GA breeding engine from seed_ga.rs using real data fitness
- Minimum population: 200 expressions (enough to exercise dedup meaningfully)
- All timing measured with std::time::Instant (monotonic clock)
- Memory usage reported if possible (allocation tracking)

## 6. Acceptance criteria

The batch verification passes when:

1. Zero panics during execution
2. Total wall time < sixty seconds for two hundred fifty alphas
3. Dedup ratio > fifty percent (shared graph saves meaningful computation)
4. At least one candidate survives all screening gates
5. No NaN in final metrics for surviving candidates

If acceptance criteria are not met, the bottleneck step is identified from
the per-step throughput measurements and targeted for optimisation before
re-running.
