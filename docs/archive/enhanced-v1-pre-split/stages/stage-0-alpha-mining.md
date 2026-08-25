---
doc_id: STG-0-ALPHA-MINING
title: Component 0 - Alpha Mining
type: specification
owner: research
status: approved
version: 2.0
components: [0]
tags: [mining, stage-hub]
source: "synthesized from discussion: formulaic-alpha breakdown; DSL anatomy; seed illustration. No standalone original file exists. Reformatted per REF-STYLE."
---

# 0. Alpha Mining

## 1. Summary

Component 0 is a factory that converts hypotheses into thousands of stateless
score functions through a DSL grammar, hand-written seeds, and genetic search.
Survivors are funneled, clustered into families, and handed to
[[stages/stage-1-canonical-simulation.md]]. This hub synthesizes several discussion
exchanges; there is no frozen original file for this component. The runnable
companion is `research/seed_alpha_demo.py` (see [[case-studies/seed-alpha-demo.md]]).

Component 0 documents two signal-generation families - interpretable formulaic
expressions (current mode: hand-written seeds bred by genetic search) and
ML-based generators (future research direction, entry conditions recorded).
Family taxonomy and expansion triggers: [[concepts/mining/alpha-generation-methods.md]].

## 2. What formulaic alpha is

2.1 An alpha expressed as an explicit formula over price/volume/book data using
standard operators. Each expression encodes one behavioral hypothesis in a few
characters. Canonical reference: "101 Formulaic Alphas" (Kakushadze, WorldQuant,
2015), for example `Alpha#6 = -correlation(open, volume, 10)`.

2.2 The operator grammar has two families. Time-series operators act on one
instrument's history: ts_mean, ts_std, delay, delta, ts_rank, rolling
correlation. Cross-sectional operators rank or standardize across instruments.
Single-instrument time-series trading uses only the time-series family.

2.3 Three binding constraints make an expression factory-grade. It must be
causal (data at time t or earlier only), stateless (no position memory), and
vectorizable (entire history computed in one pass).

2.4 Rule-based alphas (minus-one/zero/plus-one entry-exit signals) are a subset:
formulaic alpha passed through sign(), thresholds, and state memory. Modern
factories prefer continuous stateless scores because they combine cleanly,
measure by IC directly, and vectorize. Discretization belongs to downstream
sizing, never inside the alpha.

## 3. DSL anatomy

    metadata   -> name / author / tags
    data       -> field bindings (close, high, low, book fields)
    params     -> tunable constants, separated from logic
    features   -> intermediate expressions
    rules      -> boolean conditions
    signals    -> entry/exit events (rule-based style)

The purpose of a DSL is that formulas become data: storable, comparable, and
machine-generatable.

## 4. How Chinese shops run this assembly line

4.1 Raw material. Level-2 tick and order-book depth, minute bars, flow data.
Data advantage outweighs formula cleverness.

4.2 Grammar and breeding. Humans supply hypothesis seeds; machines enumerate or
genetically breed millions of expressions; vectorized backtests screen tens of
thousands per day on multi-component fitness (net Sharpe, decay, turnover,
capacity). See [[concepts/mining/ga-machinery.md]].

4.3 Orthogonalization. A new alpha must show incremental value after regressing
out existing pool PnL. See [[stages/stage-3-orthogonalization.md]].

4.4 Combination and exploitation. Hundreds of weak factors combined by linear
weights or ML stacking; execution quality converts forecasts to money.

4.5 Why this works in China specifically. Retail-dominated flow preserves
exploitable behavioral patterns; post-2015 regulation fenced out foreign speed
competition; inexpensive research labor sustains the conveyor. The cost:
published or crowded formulas die within months. The product being sold is the
factory itself, not any single strategy.

4.6 Transferability to VN30F1M. Transferable: the methodology applied over
time-series operators times local raw materials (price, volume, bid-ask, open
interest, cash-futures basis). Not transferable: cross-sectional layers, T0
execution tricks, and published formulas themselves.

## 5. Search fitness versus acceptance criteria

5.1 Search fitness (internal to mining) uses cheap score-level metrics - IC,
ICIR, decay, signal autocorrelation - as selection pressure for pruning and
breeding. Its results are never final judgments.

5.2 Acceptance criteria are formal gates applied later
([[stages/stage-2-evaluation-screening.md]]): canonical-PnL Sharpe, walk-forward stability,
parameter plateau, deflated thresholds.

5.3 GA fitness designs come in three kinds. A scalarized composite such as the
WorldQuant form:

    fitness = ICIR * sqrt(abs(annual_return)) / max(turnover, 0.125)

multiplicative so any zero component kills the candidate. A single objective plus
hard constraint filters - cleanest, no cross-objective tuning. True
multi-objective Pareto fronts (NSGA-II) - expensive; downstream stages pick from
the front.

5.4 Two laws. The GA exploits every loophole in its fitness function (Goodhart's
law); linear weighted sums are the most exploitable shape. Every weighted
component flattens selection pressure and adds an overfitting degree of freedom.
Rule: one primary objective plus hard constraints, never more.

## 6. From millions to families

6.1 Funnel first. Deduplicate on canonical expression-tree form (identical trees
differing only in params are one idea), apply complexity penalty, run cheap
vectorized screening. Roughly one percent survives; millions become tens of
thousands.

6.2 Similarity without full correlation matrices. Compress score series by
random projection or PCA; find near-duplicates with locality-sensitive hashing
or approximate nearest neighbor search; compute exact correlation distance only
inside candidate neighborhoods.

6.3 Cluster hierarchically (Ward linkage on correlation distance, cut around
correlation 0.7), then label semantically. Shared subtrees in DSL trees are a
strong same-idea signal regardless of surface parameters.

6.4 Promote exactly one representative per family into Stage 1; new batches
assign to existing families by nearest centroid; genuinely novel clusters spawn
new families. Realistic numbers: mine one million per day, about ten thousand
survive screening, hundreds to thousands of families, tens to hundreds of pool
alphas after Stage 3.

6.5 The same machinery estimates N_eff for deflated thresholds: count clusters,
or participation ratio over eigenvalues of the trial-PnL correlation matrix,

    N_eff = (sum of lambda)^2 / sum of lambda^2

---
## Related notes
- [[stages/stage-1-canonical-simulation.md]] - where survivors go next
- [[concepts/mining/formulaic-alpha-and-seeds.md]] - definitions and grammar detail
- [[concepts/mining/ic-metrics-and-horizon-ladder.md]] - how forecast quality is measured here
- [[concepts/mining/ga-machinery.md]] - breeding engines and fitness design
- [[stages/stage-0-alpha-mining.md]] - survivor organization (section 6)
- [[case-studies/seed-alpha-demo.md]] - worked case study with runnable script
