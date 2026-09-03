---
doc_id: DEC-024
title: Systematic trading operating model - continuous research replenishment and recalibration
type: decision
owner: research
status: triaged
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [operating-model, lifecycle, research-roles, research-replenishment, capability-ownership]
source: "owner-approved correction plan 2026-09-03 following OBS-019 continuous research replenishment review of DEC-021"
design: [OV-LIFECYCLE, STG-0-ALPHA-MINING, STG-1-CANONICAL-SIM, STG-2-EVALUATION, STG-3-ORTHOGONALIZATION, STG-4-COMBINATION, STG-5-POSITION-CONSTRUCTION, STG-6-TRADE-SCHEDULING, STG-7-RISK-OVERLAY]
code: [src/alpha-core, src/market_data, src/quant_api, src/trading]
test: []
---

# DEC-024 - Systematic Trading Operating Model

## 1. Decision and Scope

This triaged decision is the proposed self-contained successor to DEC-021. It preserves the actor, artifact, capability, Rust, Nautilus, lifecycle, and runtime-risk boundaries from DEC-021 while extending the operating model with the continuous research replenishment and recalibration semantics recorded by OBS-019. The substantive content of DEC-019, DEC-020, and DEC-021 remains unchanged as the historical record that led to this decision.

The operating model describes actors, business activities, artifacts, system capabilities, ownership boundaries, lifecycle transitions, and feedback. It does not prescribe Python or Rust classes, public method names, method signatures, or an implementation work breakdown. Capability labels in this decision are descriptions of what the framework must accomplish, not pre-approved APIs.

The framework is a replicable systematic-trading operating system. VN30F1M intraday trading and broker paper trading are the current proving ground, not the framework's end state. The present milestone uses one alpha set to exercise the complete operating model through a broker demo account before real capital is introduced.

## 2. Operating-Model Interpretation Rule

Read every lifecycle step through five questions: who owns the decision, what activity occurs, which artifact enters, which capability performs any automated work, and which artifact or state leaves. Never infer a software method merely because an activity or capability has a name.

```text
actor
    -> business activity
    -> input artifact
    -> system capability where automation is required
    -> resulting artifact or lifecycle state
```

Model and policy ownership always has two distinct layers.

```text
owning researcher
    defines, reviews, validates, and versions a model or policy

runtime or research system
    applies the active version and records the result
```

Daily, weekly, monthly, and quarterly labels define operating cadence. They do not by themselves require a scheduled API call, automatic researcher judgment, or immediate deployment of a newly fitted artifact.

## 3. Applied Vocabulary

The operating model uses explicit names for intent, permission, realized state, research eligibility, and deployment. These names preserve the semantic corrections made in DEC-020 without treating them as method signatures.

```text
desired_target
    exposure requested by portfolio construction

allowed_target
    exposure permitted after the project risk overlay

Nautilus Position
    realized position derived from broker-confirmed fills

eligible_alpha_pool
    alphas that passed standalone evaluation and pool incrementality

active_alpha_pool
    eligible alphas selected by the active deployment policy

standardized backtest
    uniform candidate simulation producing comparable net-of-cost evidence

backtest_result
    machine-readable standardized-backtest evidence

tear_sheet
    human-readable research evidence

live_monitoring_baseline
    versioned expectations and statistical bands used for live comparison

experiment_log
    immutable research provenance and evaluation history

alpha_monitoring_history
    live alpha metrics, comparisons, and health observations

portfolio_eligibility
    evidence that an alpha adds value beyond the existing pool

live_vs_backtest_drift
    measured divergence between live evidence and research expectations

risk_intervention_policy
    versioned mapping from project risk conditions to runtime action

retirement_rules
    versioned evidence requirements for permanent removal from the lifecycle
```

The baseline operating cadence remains daily, weekly, monthly, and quarterly. `BACKTEST`, `SANDBOX`, and `LIVE` remain Nautilus node environments. Broker paper trading uses a Nautilus `LIVE` node with an Entrade `DEMO` account; real trading changes the account environment to `LIVE` without introducing a second operating model.

## 4. Business Users and Responsibilities

The current operating model has four business-user personas. Nautilus, `quant_core`, and broker adapters are system components rather than users. A Quant Developer builds the system but is not an actor in the business lifecycle. No separate operator or deployment-approver persona is introduced by this decision.

4.1 Quantitative Researcher. This user forms hypotheses, supplies hypothesis seeds, defines research constraints, designs alpha search spaces and fitness, designs experiments, interprets standardized-backtest and evaluation evidence, investigates rejected candidates, owns alpha-health interpretation, and owns proposed changes to the research harness and evaluation policy.

4.2 Portfolio Researcher. This user owns pool incrementality, pool-admission research, active-composition research, combination and weighting policy, benchmark selection, portfolio contribution analysis, pool-health review, and retirement research. The Portfolio Researcher receives alpha evidence and supplies active-composition, weight, and desired-exposure artifacts downstream.

4.3 Execution Researcher. This user owns transaction-cost assumptions, execution-cost models, urgency policy, execution-algorithm research, slippage analysis, fill-quality research, and proposed changes to scheduling parameters. The Execution Researcher supplies cost evidence to standardized backtests and position construction as well as an approved execution policy to live trading.

4.4 Risk Researcher. This user owns the model that adjusts position sizing, including risk budgets, risk multipliers, exposure constraints, drawdown policy, live intervention thresholds, and escalation rules. The Risk Researcher defines and versions risk policy; the runtime applies the active version independently.

4.5 Cross-functional post-mortems. All four researchers contribute evidence after alpha, portfolio, execution, risk, data, or infrastructure failures. Each researcher may propose a model or policy revision only within that role's ownership boundary. Accepted versions feed the next operating loop.

4.6 Continuous research ownership. Each researcher continuously maintains candidate versions of the models and policies within that role's ownership. Continuous means the research queue and feedback process remain active; it does not mean research runs on every market event or that production hot-swaps unvalidated artifacts. Runtime evidence feeds researcher-owned diagnosis and research, never direct mutation of an active production artifact.

## 5. Capability Ownership

The project wires existing quantitative primitives and Nautilus runtime capabilities into the business loop. It must not reproduce a capability already owned by either layer.

5.1 Rust quantitative core. `alpha-core` remains the source for existing expression parsing and scoring, genetic search, standardized-backtest calculations, evaluation metrics, orthogonalization, combination, and sizing primitives. Python may orchestrate and expose those primitives but does not mirror their calculations.

The research extension points remain available.

```text
ga_fitness
combine_methods
sizing_methods
risk_policies
execution_algorithms
```

The research-input and extension ownership boundary is:

```text
Quantitative Researcher
    research hypotheses
    seed expressions
    search-space or grammar version
    ga_fitness and fitness-configuration version

Portfolio Researcher
    combine_methods

Risk Researcher
    sizing_methods
    risk_policies

Execution Researcher
    execution_algorithms
    versioned cost-model artifacts
```

Research hypotheses and seed expressions are inputs to alpha mining, not outputs invented by the backbone. This artifact boundary does not imply a submission, registration, or creation API.

5.2 Nautilus runtime. Nautilus owns the node lifecycle and event loop, data and execution client connections, `DataEngine`, `Cache`, `Portfolio`, orders, fills, positions, accounts, persistence, startup and continuous reconciliation, execution clients, `ExecutionEngine`, `ExecutionAlgorithm`, runtime messages, timers, and coordinated shutdown.

Nautilus also owns last-mile order validation and `TradingState`: price and quantity validation, instrument limits, duplicate-order checks, submit and modify rate limits, maximum notional per order, reduce-only checks, and order permission while `ACTIVE`, `REDUCING`, or `HALTED`.

5.3 Project capabilities. The project owns alpha research records and lifecycle, standardized evaluation orchestration, pool eligibility, active alpha composition, score combination, desired-position construction, selection of execution policy and primary-order intent, project-specific risk policy, alpha monitoring, decision attribution, execution analytics, cost-model feedback, and deployment configuration.

Project Risk owns total exposure limits, portfolio drawdown, intraday loss, the risk multiplier, stale market data, missing heartbeat, live-versus-backtest drift, alpha health, warning and escalation policy, and reduce, flatten, or shutdown decisions. It reads Nautilus state and requests Nautilus actions; it does not build a second order ledger, position ledger, account state, profit-and-loss state machine, execution engine, or reconciliation loop.

NautilusTrader v1.231 does not perform complete account-balance risk checks for margin accounts. Project hard exposure limits and Entrade-specific validation therefore remain necessary for both paper and live trading.

## 6. Data and Artifact Ownership

Every artifact has one authoritative owner. Research and runtime evidence may refer to Nautilus state but must not duplicate its ledgers.

```text
Historical market data
    owner  ParquetDataCatalog

Current market state
    owner  Nautilus Cache

Data-health evidence
    owner  project data capability

Experiment log
    owner  project research store
    holds  candidate, parameters, dataset version, harness version,
           cost-model version, test results, and verdict

Tear sheets
    owner  project research store

Alpha library and lifecycle state
    owner  project alpha store

Live monitoring baselines
    owner  project alpha store

Alpha monitoring history and health assessments
    owner  project monitoring store

Eligible and active alpha pools
    owner  project portfolio configuration

Residual statistics and portfolio weights
    owner  project portfolio configuration

Decision attribution
    owner  project portfolio records
    holds  decision id, timestamp, alpha scores, standardized scores,
           weights, alpha contributions, composite score,
           desired target, and allowed target

Risk configuration and actions
    owner  project risk store
    holds  allocated risk budget, hard exposure limits, leverage cap,
           intervention policy, retirement rules, and risk actions

Orders, fills, positions, accounts, trading state, reconciliation state
    owner  Nautilus runtime

Execution metrics and decision-to-order attribution
    owner  project execution analytics

Session and deployment configuration
    owner  project operating-policy store

Alpha-mining research inputs
    owner  Quantitative Researcher
    holds  research hypotheses, seed expressions, search-space or grammar
           version, candidate constraints, and fitness-configuration version

Candidate model and policy versions
    owner  corresponding Quantitative, Portfolio, Execution, or Risk Researcher
    holds  proposed, evaluated, validated, accepted, and active version state
```

## 7. Alpha Lifecycle

The alpha lifecycle is retained from DEC-019 and DEC-020. Every state reference must qualify the object that owns the state.

```text
CANDIDATE
    |-- REJECTED
    `-- QUALIFIED
            `-- ELIGIBLE
                    |-- SHADOW      optional by deployment policy
                    |-- PAPER       optional by deployment policy
                    `-- ACTIVE
                            |-- DEGRADED
                            |       |-- ACTIVE
                            |       |-- DISABLED
                            |       `-- RETIRED
                            |-- DISABLED
                            |       |-- ACTIVE
                            |       `-- RETIRED
                            `-- RETIRED
```

```text
QUALIFIED
    passed standalone research evaluation

ELIGIBLE
    passed standalone evaluation and pool incrementality evaluation

SHADOW
    runs on live data and produces scores, targets, and monitoring evidence
    without affecting the active portfolio or creating orders and fills

PAPER
    participates in broker paper trading through a Nautilus LIVE node and
    an Entrade DEMO account; orders and fills use the live runtime path

ACTIVE
    selected by the active portfolio deployment policy, assigned active
    weight, and permitted to trade through an Entrade LIVE account

DEGRADED
    remains active while material deterioration is diagnosed; may recover,
    be constrained by Risk, become disabled, or be retired

DISABLED
    live trading permission removed; potentially reversible

RETIRED
    permanently removed from the investable alpha lifecycle
```

State namespaces remain independent.

```text
alpha.lifecycle_state
    CANDIDATE | REJECTED | QUALIFIED | ELIGIBLE | SHADOW | PAPER |
    ACTIVE | DEGRADED | DISABLED | RETIRED

node.environment
    BACKTEST | SANDBOX | LIVE

account.environment
    DEMO | LIVE

risk_engine.trading_state
    ACTIVE | REDUCING | HALTED

Nautilus component state
    owned independently by each Nautilus Actor, Strategy, and engine component
```

For example, an alpha may have `alpha.lifecycle_state = ACTIVE` while the node has `node.environment = LIVE`, the broker account has `account.environment = DEMO`, and the risk engine has `risk_engine.trading_state = HALTED`. None of these state words implies another.

## 8. Core Operating Invariants

The complete operating model preserves the following ownership sequence.

```text
Alpha capability
    produces forecasts

Portfolio capability
    produces desired exposure

Project Risk capability
    produces permitted exposure

Execution policy
    produces primary-order intent

Nautilus
    manages execution and produces realized exposure from confirmed fills

Portfolio analytics
    attributes realized economics to decisions and alphas

Alpha monitoring
    diagnoses live alpha behavior

Project Risk
    decides whether trading may continue under the active risk policy
```

Desired, permitted, and realized exposure are always separate. Research evidence never substitutes for broker-confirmed runtime state.

## 9. Systematic Trading Lifecycle Operating Algorithm

This algorithm is the business and capability view of the complete loop. Its labels are not software methods or signatures.

```text
ALGORITHM SYSTEMATIC_TRADING_LIFECYCLE


INITIALIZATION

    Research owners provide the active, versioned deployment package:
        active alpha composition and alpha models
        portfolio combination and weighting policy
        position-construction model
        cost model and execution policy
        risk budget, sizing overlay, limits, and intervention policy
        live monitoring baselines
        session and account configuration

    System configures a Nautilus LIVE node with:
        Entrade account environment = DEMO or LIVE
        cache persistence
        data client
        execution client
        approved execution algorithms
        streaming
        startup and continuous reconciliation

    Nautilus owns:
        cache restoration
        data and execution client connection
        startup reconciliation
        Portfolio initialization
        Strategy and Actor startup
        event loop and coordinated shutdown

    IF connection or reconciliation FAILS:
        Nautilus prevents trading components from starting


RESEARCH AND ADMISSION

    Quantitative Researcher uses:
        researcher observations
        post-mortems
        live failures
        family statistics
        market knowledge

    Quantitative Researcher defines and continuously replenishes:
        research hypotheses
        seed expressions
        search-space or grammar configuration
        candidate constraints
        fitness configuration

    Alpha-mining capability consumes:
        researcher-defined research inputs
        market data

    Alpha-mining capability enumerates or genetically breeds:
        candidate expressions with provenance

    FOR EACH candidate:

        record alpha.lifecycle_state = CANDIDATE

        Standardized-backtest capability applies:
            active harness configuration
            active Execution Researcher cost model
            versioned market data

        Standardized-backtest capability produces:
            backtest_result
            experiment evidence

        Evaluation capability applies:
            active Quantitative Researcher evaluation policy
            complete experiment history for multiple-testing control

        Evaluation capability produces:
            evaluation_result
            logged provenance and rejection evidence

        IF evaluation_result FAILS:
            record alpha.lifecycle_state = REJECTED
            CONTINUE

        record alpha.lifecycle_state = QUALIFIED

        Portfolio incrementality capability applies:
            active Portfolio Researcher pool-admission policy
            candidate daily net profit-and-loss evidence
            active-pool daily net profit-and-loss evidence

        Portfolio incrementality capability produces:
            residual returns
            residual statistics
            incrementality result

        IF incrementality result FAILS:
            record alpha.lifecycle_state = REJECTED
            CONTINUE

        Research evidence capability produces:
            tear sheet
            complete research provenance
            portfolio-eligibility evidence

        Monitoring statistics are derived from approved research evidence

        Quantitative Researcher reviews and versions:
            live monitoring baseline
            metric interpretation
            statistical confidence bands

        register candidate in eligible_alpha_pool
        record alpha.lifecycle_state = ELIGIBLE


PORTFOLIO RESEARCH AND REFIT

    Portfolio Researcher continuously researches, defines, and versions:
        composition policy
        combination and weighting policy
        benchmark policy
        deployment policy

    AT the weekly review and refit cadence:

        Portfolio refit capability applies active policies to:
            eligible_alpha_pool
            active_alpha_pool
            residual statistics
            score history
            alpha profit-and-loss volatility

        Portfolio refit capability produces:
            composition candidate
            candidate weights
            out-of-sample comparison with benchmark weights

        Active deployment policy determines whether the result:
            activates automatically under pre-approved rules
            or waits for Portfolio Researcher review

        WHEN deployment policy accepts the result:
            publish active composition and weights as one versioned artifact
            record newly active alphas with alpha.lifecycle_state = ACTIVE


LIVE MARKET EVENT

    ON each market event:

        market state comes from Nautilus Cache

        Project data policy checks:
            freshness
            expected gaps
            session validity
            project-specific data conditions

        IF data policy FAILS:
            Project Risk applies the active data-failure policy
            do not produce new exposure from the failed event
            CONTINUE

        Active alpha models consume market state
            -> alpha scores

        Active portfolio model consumes alpha scores and weights
            -> standardized scores
            -> alpha decision contributions
            -> composite score

        Active position-construction model consumes:
            composite score
            volatility estimate
            allocated risk budget

        Active position-construction model produces:
            desired_target

        Active Risk Researcher sizing and constraint policy consumes:
            desired_target
            leverage cap
            drawdown state
            Nautilus Portfolio and Cache account state
            market state

        Active Risk Researcher policy produces:
            allowed_target

        Project records one attributed decision containing:
            alpha scores
            standardized scores
            portfolio weights
            alpha contributions
            composite score
            desired_target
            allowed_target

        Active Execution Researcher policy consumes:
            attributed decision and target version
            allowed_target
            current Nautilus position
            order-book state
            alpha decay
            active cost model

        Active execution policy produces:
            primary-order intent
            optional Nautilus execution-algorithm identifier

        Nautilus Strategy submits the primary order

        IF an execution-algorithm identifier is attached:
            Nautilus ExecutionAlgorithm owns timing, slicing, and spawned orders


BROKER ORDER EVENT

    ON each broker order event:

        Nautilus ExecutionEngine processes the event
        Nautilus Cache and Portfolio update order, position, and account state

        Project execution analytics update from broker-confirmed evidence

        Nautilus continuous reconciliation owns:
            in-flight order checks
            open-order checks
            position checks
            venue-state correction


LIVE RISK

    CONTINUOUSLY and without human approval on the order path:

        Active project risk policy consumes:
            Nautilus Portfolio exposure and profit-and-loss state
            drawdown
            implementation shortfall
            position tracking error
            fill, reject, and latency evidence
            data-feed health
            process heartbeat
            alpha-health assessments

        Active project risk policy produces one condition:
            NORMAL
            DEGRADED
            SOFT_HALT
            FLATTEN
            SHUTDOWN

        CASE condition:

            NORMAL:
                project risk multiplier = 1.0
                Nautilus risk_engine.trading_state = ACTIVE

            DEGRADED:
                reduce project risk multiplier under the active policy
                warn the responsible humans

            SOFT_HALT:
                Nautilus risk_engine.trading_state = REDUCING

            FLATTEN:
                Nautilus Strategy cancels open orders
                Nautilus Strategy closes positions
                wait for confirmed fills and a flat Nautilus Portfolio
                Nautilus risk_engine.trading_state = HALTED
                send a critical alert

            SHUTDOWN:
                Nautilus Strategy cancels open orders
                Nautilus Strategy closes positions
                Nautilus TradingNode stops
                prevent restart until the active restart policy is satisfied

        IF active risk policy force-disables an alpha:
            block new exposure from that alpha
            record the reason and evidence
            record alpha.lifecycle_state = DISABLED


FEEDBACK AND RECALIBRATION

    Each research role continuously maintains candidate versions of:
        models and policies within that role's ownership

    Runtime evidence:
        feeds researcher-owned diagnosis and recalibration
        never directly mutates an active production artifact

    Only validated and accepted versions:
        become inputs to the next operating loop

    Quantitative Researcher loop:
        consumes alpha decay, live-versus-backtest drift,
        rejected-candidate statistics, family saturation,
        correlation and incrementality failures, regime changes,
        and post-mortem evidence
        replenishes research hypotheses and seed expressions
        recalibrates search, fitness, harness, evaluation,
        stability, and monitoring-baseline candidates

    Portfolio Researcher loop:
        consumes new eligible alphas, active-alpha decay,
        correlation drift, concentration, drawdown,
        marginal contribution, weight instability,
        capacity, and realized-cost evidence
        researches candidate pool-admission, composition,
        combination, weighting, benchmark, retirement,
        and deployment-policy versions

    Risk Researcher loop:
        consumes realized volatility, drawdown distribution,
        concentration, correlation spikes, tracking error,
        stress evidence, alpha-health deterioration,
        exposure differences, incidents, and post-mortems
        researches candidate sizing, risk-budget,
        limit, intervention, escalation, and restart-policy versions

    Execution Researcher loop:
        consumes broker-confirmed fills, implementation shortfall,
        slippage, reject and cancel rates, latency,
        order-book depth, fill rate, forecast decay,
        venue behavior, incidents, and post-mortems
        researches candidate cost-model, urgency,
        order-placement, capacity, scheduling,
        and execution-policy versions

    DAILY evidence production:
        attribute confirmed Nautilus fills to decisions and alphas
        compare live alpha evidence with active monitoring baselines
        record profit-and-loss attribution and alpha-health observations

    WEEKLY review cadence:
        Execution Researcher reviews slippage, fills,
        implementation shortfall, and cost-model evidence
        Portfolio Researcher reviews weight-refit evidence

    MONTHLY review cadence:
        Quantitative Researcher reviews alpha health and parameter stability
        Portfolio Researcher reviews pool health, portfolio contribution,
        and retirement evidence

        IF active retirement policy retires an alpha:
            remove it from the investable pool
            record the supporting evidence
            record alpha.lifecycle_state = RETIRED

    QUARTERLY review cadence:
        Portfolio Researcher reviews pool orthogonalization evidence
        Risk Researcher reviews risk budgets and the sizing overlay
        Quantitative Researcher reviews the standardized-backtest harness
        Execution Researcher supplies realized-cost evidence to those reviews

    Cross-functional post-mortems feed:
        Quantitative Researcher hypothesis and research-policy work
        Portfolio Researcher composition and pool-policy work
        Execution Researcher cost and execution-policy work
        Risk Researcher sizing and intervention-policy work

    FOR EACH proposed model or policy revision:
        owning researcher validates and versions the artifact
        accepted version becomes an input to the next operating loop


END ALGORITHM
```

## 10. Capability and Ownership Map

This map replaces the method table in DEC-019 and DEC-020. It records business ownership and system responsibility without approving API names.

10.1 Data capability. The project applies freshness, expected-gap, session, and validity policy to Nautilus data and Cache state. Nautilus remains the source of runtime market state.

10.2 Alpha research capability. The Quantitative Researcher owns hypotheses, seeds, research policy, and interpretation. The system supports candidate search, standardized backtests, objective evaluation, research provenance, tear sheets, lifecycle records, live-score computation, baseline comparison, and monitoring evidence.

10.3 Portfolio research capability. The Portfolio Researcher owns pool-admission, composition, combination, weighting, benchmark, deployment, contribution, and retirement policy. The system supports orthogonalization, incrementality evidence, eligible and active pool records, scheduled refits, score combination, desired-target construction, decision attribution, and portfolio monitoring evidence.

10.4 Execution research capability. The Execution Researcher owns cost and execution-policy research. The project supports primary-order intent, decision-to-order attribution, execution metrics, and cost-model evidence. Nautilus owns orders, execution algorithms, fills, positions, accounts, and reconciliation.

10.5 Risk research capability. The Risk Researcher owns sizing, budgets, limits, intervention, escalation, and restart policy. The project applies the active policy automatically to produce allowed targets and live interventions. Nautilus enforces last-mile order checks and trading state.

10.6 Core shared capability. The project maintains versioned catalogs, artifacts, lifecycle records, pool membership, experiment provenance, monitoring history, and deployment configuration without duplicating Nautilus runtime state.

10.7 Continuous research feedback capability. Production and research evidence feeds role-owned candidate work. The system supports evidence capture, offline evaluation, shadow or paper validation where required, version records, and promotion of accepted artifacts. It never treats evidence arrival as permission to mutate an active model or policy.

## 11. Implementation Boundary

This decision does not remove or approve any particular existing `quant_api` method. Existing code remains evidence of current behavior. After this operating model is approved, implementation planning must audit the code and classify each existing method as one of four outcomes: retain as a valid capability boundary, wire to an existing Rust primitive, delegate to Nautilus, or remove because it represents researcher work or duplicate runtime ownership.

Do not invent replacement methods for researcher-owned activities. Research hypotheses, seed expressions, search configuration, fitness configuration, and candidate model or policy versions are artifact boundaries, not pre-approved APIs. In particular, the absence of an alpha-hypothesis-generation method does not authorize a submission, registration, or creation API without a separate use case and contract discussion.

## 12. Status and Acceptance

This decision remains `triaged` until the owner reviews the complete DEC-021 copy-patch, including all four continuous researcher loops, the seed-expression research-input boundary, candidate-version validation, and promotion semantics. While triaged, DEC-021 remains the current resolved implementation-planning guide and OBS-019 remains open. After approval, DEC-024 may supersede DEC-021 and resolve OBS-019.

## Related Notes

- [OBS-019](../observations/OBS-019-continuous-research-replenishment.md) - open finding that defines the four researcher feedback loops and seed-expression artifact boundary added here.
- [OBS-018](../observations/OBS-018-operating-model-contract-leakage.md) - finding that researcher activities and component flows leaked into premature method contracts.
- [DEC-021](DEC-021-actor-artifact-capability-operating-model.md) - complete immediate predecessor copied and patched by this decision.
- [DEC-019](DEC-019-systematic-trading-lifecycle-operating-model.md) - original method-shaped operating-model draft.
- [DEC-020](DEC-020-systematic-trading-operating-model-correction.md) - runtime-ownership correction preserved through DEC-021.
- [framework lifecycle](../../enhanced/framework-lifecycle.md) - frozen component, build-phase, and runtime-loop distinctions.
- [alpha mining](../../enhanced/stages/stage-0-alpha-mining.md) - frozen human-seed and machine-search boundary.
- [risk overlay and monitoring](../../enhanced/stages/stage-7-risk-overlay-monitoring.md) - frozen automatic runtime-risk boundary.
