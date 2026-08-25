---
doc_id: CON-CB-META-LABELING
title: Meta-Labeling
type: specification
owner: research
status: approved
version: 1.1
components: [4, 5]
tags: [combination, sizing, machine-learning]
aliases: ["Meta Labeling", "Secondary Model Sizing"]
source: "follow-up discussion: where meta-labeling fits in the pipeline"
---

# Meta-Labeling

## 1. Summary

Prado's meta-labeling: the primary strategy decides direction; a secondary model
predicts the probability that this bet profits; position size follows that
probability. In this pipeline it is a learned multiplier m_meta in zero-to-one
inside the Component 5 sizing stack - trained on composite-level events, never on
individual alphas.

## 2. Placement

    p_final = clip( z * (vol_target/vol_est) * m_drawdown * m_regime * m_meta * m_rampup , +/-
    z           composite score from Components 0-4
    vol_est_HF  high-frequency volatility estimate, floored
    m_drawdown  pre-committed drawdown multiplier
                ([[concepts/combination/drawdown-overlay.md]])
    m_regime    regime/event lookup multiplier
    m_meta      learned probability multiplier (this note)
    m_rampup    post-go-live trust-ladder multiplier

Primary means everything from Components 0 through 4 (the composite score); the
meta-model modulates size, or vetoes below a probability threshold.

## 3. Why training per-alpha never happens

Four reasons. Real bets materialize at portfolio level only - the meaningful
question is whether this exposure profits, which exists solely after combination.
Data starvation: single alphas rarely generate enough independent events to feed a
learner. Multiple-testing explosion: tens of thousands of meta-models would blow up
trial counts and deflated thresholds system-wide. Feature economy: valid features
are market state variables - volatility regime, spread and depth state, time of
day, recent composite performance, event calendar - properties of context shared by
one learner.

A legitimate middle level exists: family-level gating. A small learner predicts
whether, say, momentum works in the current regime and adjusts that family's risk
budget - ML-flavored regime-conditioned budgets; learner count equals family count.

## 4. Correct setup for continuous intraday signals

Meta-labeling assumes discrete trades, so define events first: each crossing of the
no-trade band opens an episode. Labels use the triple-barrier method (profit
barrier, stop barrier, timeout) computed net of costs. Features are state variables
known at episode open. Validation uses purged K-fold with embargo plus walk-forward
- Prado's own anti-leakage machinery. Output mapping example: probability below
0.45 gives multiplier zero; scaling to one as probability approaches 0.7.

Fatal detail: labels must reflect net outcomes of what execution will actually do;
otherwise the learner favors high-turnover episodes whose costs eat the edge.

## 5. When it earns its place

Three conditions together: stable live composite generating real fills; thousands
of episodes of history; disciplined purge-and-embargo validation. Before that,
frozen multiplier tables plus drawdown overlay deliver about ninety percent of the
value at ten percent of the self-deception risk - a badly trained meta-model sizes
down before good episodes and up before killers.

---
## Links
- Up: [[stages/stage-4-combination.md]], [[stages/stage-5-position-construction.md]]
- Related: [[concepts/combination/supplementary-techniques.md]], [[concepts/sizing/china-sizing-stack.md]],
  [[concepts/evaluation/trial-count-and-thresholds.md]]
