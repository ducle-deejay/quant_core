---
doc_id: CON-MIN-METHODS
title: Alpha Generation Methods (Formulaic vs ML)
type: specification
owner: research
status: approved
version: 1.0
components: [0]
tags: [mining, ml, research-direction]
source: "discussion: two-family taxonomy of alpha generation; project positioning"
---

# Alpha Generation Methods (Formulaic vs ML)

## 1. Summary

Alpha generation - the search for predictive signals - has two main families: interpretable formulaic expressions and machine-learning models. This project currently operates family one (hand-written seeds bred by genetic search). Family two is documented here as a future research direction with explicit entry conditions; it is not a build item today.

Scope boundary: this note covers signal generation only, which lives in Component 0. ML usage elsewhere - combination stacking in Component 4, learned sizing overlays in Component 5 - belongs to those components and is not an alpha-generation method.

## 2. The two families

2.1 Formulaic-based alpha. Explicit operator expressions over data; every expression encodes one behavioral hypothesis.

Advantages:
- Interpretable: each expression states what market behavior it bets on, so review, debugging, and post-mortems have something concrete to read
- Auditable: gate decisions at Stage 2 can cite the mechanism, useful when an alpha must be defended or switched off
- Works on modest samples: per-alpha overfitting is controllable with few parameters and plateau checks
- Composable: stateless scores stack cleanly through the pool governance

Disadvantages:
- Limited expressiveness: misses nonlinear and high-order interactions between variables
- Discovery effort scales with researcher time or search compute
- Crowding: simple readable formulas get copied and decay fast


2.2 ML-based alpha. Models trained on features or raw data that output predictions directly, without an intermediate human-readable expression.

Advantages:
- Captures nonlinear and high-order structure invisible to hand grammar
- Higher raw predictive power once effective sample is large
- Automates feature discovery

Disadvantages:
- Uninterpretable: hard to audit, hard to explain a drawdown, regulatory and personal confidence costs
- Large effective-sample requirement; small samples produce confident noise
- Overfitting harder to control: more degrees of freedom, weaker priors
- Live failures are harder to diagnose (model, data, or regime?)


## 3. Do shops share this framing

Yes. The interpretable-versus-black-box trade-off is standard industry understanding. Where shops differ is in which weakness they choose to manage. Formulaic factories (the assembly line discussed for Stage 0) accept limited expressiveness and fight crowding by running a conveyor that replenishes dying alphas. Top ML-driven firms accept opacity and compensate with heavy statistical validation, capacity management, and infrastructure - viable only at large data scale. Hybrid setups are common: formulaic pools remain for robustness while ML layers are added where data justifies them.

## 4. Project status and expansion triggers

4.1 Current position: family one, method two - formulaic expressions mined by search (GA over the DSL grammar), evaluated through the canonical harness. See [[case-studies/seed-alpha-demo.md]] for the working loop.

4.2 Expansion trigger checklist for ML-based signal generation (research track, not a build item now):

- years of tick-level history for the traded instrument(s), collected and cleaned under one schema
- infrastructure able to train and serve models on that history
- validation machinery proven on formulaic pipelines first (walk-forward discipline transfers, nothing else does)


4.3 When triggered, the entry point is Component 0: an ML generator replaces or joins the seed-and-search engine as a score producer. Downstream stages stay unchanged - which is the payoff of the score contract designed at Stage 1.

---
## Related notes
- [[stages/stage-0-alpha-mining.md]] - the mining component this note extends
- [[concepts/mining/ic-metrics-and-horizon-ladder.md]] - forecast quality measurement shared by both families
- [[concepts/mining/ga-machinery.md]] - current search engine
- [[case-studies/seed-alpha-demo.md]] - working example of family one
