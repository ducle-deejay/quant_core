---
doc_id: DEC-025
title: Systematic trading operating model - required operating and supporting artifacts
type: decision
owner: research
status: triaged
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [operating-model, lifecycle, artifacts, required-operating, supporting, capability-ownership]
source: "owner-approved correction plan 2026-09-03 following OBS-020 artifact criticality review of DEC-024"
design: [OV-LIFECYCLE, STG-0-ALPHA-MINING, STG-1-CANONICAL-SIM, STG-2-EVALUATION, STG-3-ORTHOGONALIZATION, STG-4-COMBINATION, STG-5-POSITION-CONSTRUCTION, STG-6-TRADE-SCHEDULING, STG-7-RISK-OVERLAY]
code: [src/alpha-core, src/market_data, src/quant_api, src/trading]
test: []
---

# DEC-025 - Systematic Trading Operating Model

## 1. Decision and Scope

This triaged decision is the proposed self-contained successor to DEC-024. It preserves the actor, artifact, capability, Rust, Nautilus, lifecycle, runtime-risk, and continuous research-replenishment boundaries from DEC-024 while adding the artifact classification and coverage semantics recorded by OBS-020. The substantive content of DEC-019 through DEC-024 remains unchanged as the historical record that led to this decision.

The operating model describes actors, business activities, required operating artifacts, supporting artifacts, system capabilities, ownership boundaries, lifecycle transitions, and feedback. It does not prescribe Python or Rust classes, public method names, method signatures, database schemas, serialization formats, report renderers, or an implementation work breakdown. Capability and artifact labels in this decision describe required behavior and evidence, not pre-approved APIs.

The framework is a replicable systematic-trading operating system. VN30F1M intraday trading and broker paper trading are the current proving ground, not the framework's end state. The present milestone uses one alpha set to exercise the complete operating model through a broker demo account before real capital is introduced.

## 2. Operating-Model Interpretation Rule

Read every lifecycle step through seven questions: who owns the decision, what activity occurs, which artifact enters, which capability performs any automated work, which artifact or state leaves, whether each artifact is required operating or supporting, and what happens when a required operating artifact is missing or invalid. Never infer a software method merely because an activity, capability, or artifact has a name.

```text
actor
    -> business activity
    -> input artifact and classification
    -> system capability where automation is required
    -> resulting artifact or lifecycle state
    -> required-for scope
    -> missing or invalid behavior
```

Model and policy ownership always has two distinct layers.

```text
owning researcher
    defines, reviews, validates, and versions a model or policy

runtime or research system
    applies the active version and records the result
```

Daily, weekly, monthly, and quarterly labels define operating cadence. They do not by themselves require a scheduled API call, automatic researcher judgment, or immediate deployment of a newly fitted artifact.

A missing or invalid Required Operating Artifact blocks its dependent activity under the declared scope. A missing Supporting Artifact may reduce reporting, diagnosis, or observability but never changes a system decision or blocks the operating flow.

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

Authoritative data source
    owner of source data consumed by the operating model

Authoritative mutable runtime state
    current operational truth owned by the runtime system

Required Operating Artifact
    artifact whose absence or invalidity blocks a named operating activity

Supporting Artifact
    implemented non-blocking output for reporting, diagnosis, interpretation,
    communication, or convenience
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

4.7 Artifact responsibility. Each researcher owns the Required Operating Artifacts that express an accepted model or policy within that role's boundary and the Supporting Artifacts produced for that role's interpretation. Researcher ownership does not imply that a supporting report can authorize a runtime or lifecycle decision.

## 5. Capability Ownership

The project wires existing quantitative primitives and Nautilus runtime capabilities into the business loop. It must not reproduce a capability already owned by either layer. Every project capability identifies the Required Operating Artifacts it consumes and produces, plus any Supporting Artifacts it emits. Missing supporting output never becomes a hidden failure of the operating capability.

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

## 6. Data, Artifact, and Runtime-State Ownership

This section is the canonical inventory for data, artifacts, and mutable runtime state named elsewhere in the operating model. Every artifact noun in the lifecycle, operating algorithm, or capability map resolves to one entry here.

6.1 Classification. DEC-025 uses two artifact classes only.

```text
Required Operating Artifact
    required by a named research, deployment, runtime, risk,
    execution, monitoring, or feedback activity
    missing or invalid -> block that dependent activity

Supporting Artifact
    implemented for reporting, diagnosis, interpretation,
    communication, or convenience
    missing -> operating decisions and lifecycle flow remain unchanged
```

Required Operating Artifacts declare a canonical name, owner, producer, consumer, required-for scope, authoritative source, version or provenance expectation, retention or regenerability expectation, and missing or invalid behavior. Supporting Artifacts declare their authoritative inputs, consumers, regenerability, and non-blocking failure behavior.

6.2 Authoritative data sources. Source data remains distinct from artifacts derived from it.

```text
Historical market data
    classification  authoritative data source
    owner           ParquetDataCatalog
    consumers       alpha mining, standardized backtest,
                    evaluation, portfolio research
    provenance      catalog and dataset version
    behavior        dependent research activity stops when required data
                    is missing or invalid

Live market data
    classification  authoritative data source
    owner           Nautilus DataEngine and Cache
    consumers       live alpha, portfolio, risk, and execution capabilities
    provenance      instrument, source, event time, receive time
    behavior        active data policy determines whether new exposure stops
```

6.3 Authoritative mutable runtime state. These entries are operational truth rather than project artifacts.

```text
Current market state
    owner  Nautilus Cache

Orders and fills
    owner  Nautilus ExecutionEngine and Cache

Positions, exposure, profit and loss, balances, margin, and equity
    owner  Nautilus Portfolio and Cache

Trading state
    owner  Nautilus RiskEngine

Reconciliation state
    owner  Nautilus runtime
```

Project capabilities may consume this state and derive immutable evidence from it. They must not create a second authoritative order, fill, position, account, profit-and-loss, trading-state, or reconciliation store.

6.4 Required Operating Artifacts. The following artifacts are required only for the named dependent activities.

```text
Alpha-mining research inputs
    owner           Quantitative Researcher
    producer        Quantitative Researcher
    consumers       alpha-mining capability
    holds           research hypotheses, seed expressions,
                    search-space or grammar version,
                    candidate constraints, fitness-configuration version
    required for    starting the corresponding alpha-mining activity
    provenance      researcher, source evidence, version
    retention       preserve inputs for candidate reproducibility
    behavior        mining activity does not start when missing or invalid

Dataset reference
    owner           project research catalog
    producer        research dataset selection
    consumers       alpha mining, standardized backtest, evaluation
    required for    reproducible candidate research
    source          ParquetDataCatalog
    provenance      dataset and catalog version
    retention       preserve reference and source availability
    behavior        dependent candidate research stops when unresolved

Candidate research evidence
    owner           project research store
    producers       candidate search, standardized backtest,
                    evaluation, orthogonalization, incrementality
    consumers       evaluation, pool admission, monitoring-baseline research
    holds           candidate specification, parameters, backtest result,
                    evaluation result, residual returns,
                    residual statistics, incrementality result
    required for    candidate evaluation and lifecycle progression
    provenance      dataset, harness, cost-model, code, and policy versions
    retention       preserve across the alpha lifecycle
    behavior        candidate cannot advance when required evidence is absent

Experiment log
    owner           project research store
    producers       standardized-backtest and evaluation capabilities
    consumers       evaluation and multiple-testing control,
                    Quantitative Researcher
    required for    evaluation provenance and effective trial history
    source          candidate research evidence
    provenance      immutable event and artifact-version references
    retention       append-only research history
    behavior        evaluation requiring trial history stops when unavailable

Alpha library and lifecycle record
    owner           project alpha store
    producers       research, deployment, monitoring, and risk capabilities
    consumers       alpha, portfolio, risk, feedback, and deployment activities
    required for    identifying an alpha and its current lifecycle state
    provenance      alpha definition, evidence, transition reason, version
    retention       preserve the complete lifecycle history
    behavior        no lifecycle-dependent activity proceeds without identity
                    and an unambiguous current state

Portfolio eligibility evidence
    owner           project portfolio store
    producers       orthogonalization and incrementality capabilities
    consumers       eligible-pool and portfolio-refit activities
    holds           residual statistics and incrementality result
    required for    entering and remaining in eligible_alpha_pool
    provenance      candidate, active-pool, policy, and data versions
    retention       preserve while lifecycle or review depends on it
    behavior        alpha cannot enter the eligible pool when missing or invalid

Active portfolio configuration
    owner           Portfolio Researcher
    producers       accepted portfolio research and deployment policy
    consumers       live score combination and position construction
    holds           eligible_alpha_pool, active_alpha_pool,
                    active composition, portfolio weights,
                    combination and deployment policy versions
    required for    producing a live composite score and desired target
    provenance      inputs, benchmark comparison, policy version
    retention       preserve every activated version
    behavior        new live portfolio decisions stop when absent or invalid

Live monitoring baseline
    owner           Quantitative Researcher
    producers       monitoring-statistics research and accepted baseline work
    consumers       alpha-health and project-risk capabilities
    required for    live-versus-backtest comparison
    provenance      candidate research evidence and baseline version
    retention       preserve with every monitored alpha version
    behavior        baseline-dependent health assessment stops when unavailable

Alpha monitoring and health evidence
    owner           project monitoring store
    producers       live comparison and alpha-health capabilities
    consumers       Quantitative, Portfolio, and Risk Researchers;
                    active project risk policy
    holds           monitoring history, baseline comparison,
                    alpha-health assessment
    required for    alpha-health feedback and configured risk intervention
    provenance      alpha, baseline, market, decision, and fill versions
    retention       preserve across review and intervention horizons
    behavior        dependent assessment or intervention stops or follows
                    the active conservative risk policy when unavailable

Position-construction configuration
    owner           Portfolio Researcher
    producer        accepted portfolio research
    consumers       live portfolio capability
    holds           position model, volatility estimator,
                    allocated portfolio inputs
    required for    converting composite score into desired_target
    provenance      model and input versions
    retention       preserve every activated version
    behavior        no new desired target is produced when invalid

Risk configuration
    owner           Risk Researcher
    producer        accepted risk research
    consumers       project risk and live position-sizing capabilities
    holds           allocated risk budget, sizing method, risk multiplier policy,
                    hard exposure limits, leverage cap,
                    risk intervention policy, restart policy
    required for    allowed_target and automatic project-risk action
    provenance      model, threshold, evidence, and version
    retention       preserve every activated version and effective period
    behavior        block new exposure when required active policy is missing
                    or invalid

Execution configuration
    owner           Execution Researcher
    producer        accepted execution research
    consumers       standardized backtest, primary-order-intent capability,
                    execution feedback
    holds           cost model, execution policy,
                    execution-algorithm selection and configuration
    required for    cost-aware research and live primary-order intent
    provenance      fill evidence, model, algorithm, and version
    retention       preserve every activated version
    behavior        dependent backtest or live order-intent activity stops
                    when its required configuration is invalid

Deployment configuration
    owner           project operating-policy store
    producers       accepted researcher artifacts and deployment selection
    consumers       runtime initialization and live capabilities
    holds           active artifact versions, instrument, session,
                    account environment, capital, data and execution clients
    required for    starting the intended paper or live operating profile
    provenance      selected artifact versions and effective time
    retention       preserve every activated deployment
    behavior        runtime does not start when a required entry is missing

Decision attribution
    owner           project portfolio records
    producer        live decision capability
    consumers       execution attribution, portfolio attribution,
                    monitoring, feedback
    holds           decision id, timestamp, alpha scores,
                    standardized scores, portfolio weights,
                    alpha contributions, composite score,
                    desired_target, allowed_target
    required for    tracing a decision through execution and feedback
    provenance      active alpha, portfolio, risk, and market versions
    retention       preserve for the operating evidence horizon
    behavior        do not submit new exposure that cannot be attributed

Risk action record
    owner           project risk store
    producer        project risk capability
    consumers       runtime control, monitoring, feedback, post-mortem
    required for    tracing risk changes and interventions
    provenance      active risk policy, triggering evidence, effective time
    retention       append-only intervention history
    behavior        intervention still acts fail-closed; missing record output
                    is a critical operating fault requiring escalation

Execution attribution and metrics
    owner           project execution analytics
    producer        execution-event analytics
    consumers       Execution Researcher, cost-model feedback,
                    portfolio and risk research
    holds           decision-to-order attribution, implementation shortfall,
                    fill, reject, latency, and tracking evidence
    required for    closing the execution feedback edge
    source          broker-confirmed Nautilus events and decision attribution
    retention       preserve through feedback and model-validation horizons
    behavior        live execution remains Nautilus-owned, but the affected
                    feedback activity stops when evidence is incomplete

Portfolio and alpha feedback evidence
    owner           project portfolio and monitoring stores
    producers       attribution and live-comparison capabilities
    consumers       all four researcher loops
    holds           profit-and-loss attribution, portfolio contribution,
                    pool health, alpha health, live-versus-backtest drift
    required for    continuous diagnosis and candidate-version research
    source          decisions, Nautilus fills and positions,
                    active monitoring baselines
    retention       preserve across declared review horizons
    behavior        affected feedback or recalibration activity stops when
                    required evidence is incomplete

Candidate model and policy versions
    owner           corresponding Quantitative, Portfolio,
                    Execution, or Risk Researcher
    producers       researcher-owned replenishment and recalibration
    consumers       offline evaluation, shadow or paper validation,
                    accepted-version promotion
    required for    changing an active model or policy
    provenance      source evidence, researcher, evaluation, version
    retention       preserve candidate and accepted version history
    behavior        runtime continues on the current active version;
                    candidate cannot replace it without complete validation
```

6.5 Supporting Artifacts. These artifacts are in implementation scope for reporting, diagnosis, interpretation, communication, and convenience, but they never authorize a system decision or block the operating lifecycle.

```text
Tear sheet
    owner           project research store
    producer        research reporting capability
    consumers       Quantitative and Portfolio Researchers
    source          candidate research and portfolio-eligibility evidence
    regenerability  regenerable from versioned required inputs
    behavior        candidate gates use authoritative evidence directly;
                    missing tear sheet does not change the verdict

Daily attribution report
    owner           project reporting capability
    producer        portfolio and alpha feedback evidence
    consumers       Quantitative and Portfolio Researchers
    source          required attribution and monitoring evidence
    regenerability  regenerable
    behavior        feedback evidence remains available when report fails

Weekly execution and weight-review reports
    owner           project reporting capability
    producer        execution analytics and portfolio-refit evidence
    consumers       Execution and Portfolio Researchers
    source          required execution and portfolio evidence
    regenerability  regenerable
    behavior        report failure does not change active models or runtime

Monthly pool and alpha-health reports
    owner           project reporting capability
    producer        portfolio and alpha feedback evidence
    consumers       Quantitative, Portfolio, and Risk Researchers
    source          required monitoring and attribution evidence
    regenerability  regenerable
    behavior        report failure does not cause lifecycle transition

Quarterly research review reports
    owner           project reporting capability
    producer        risk, portfolio, harness, and realized-cost evidence
    consumers       all four researcher roles
    source          required operating evidence
    regenerability  regenerable
    behavior        report failure does not replace or invalidate active versions

Charts, dashboards, notebook outputs, and convenience exports
    owner           producing research or reporting capability
    consumers       researchers
    source          named Required Operating Artifacts
    regenerability  declare whether regenerable and from which versions
    behavior        missing output may reduce observability or convenience
                    but never changes operating behavior
```

A Supporting Artifact must not become a shadow source of truth. It always identifies the authoritative data, runtime state, or Required Operating Artifacts from which it was derived.

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

Lifecycle transitions require the following Required Operating Artifacts. These requirements define operating evidence, not a software method or storage schema.

```text
CANDIDATE -> QUALIFIED
    candidate research evidence
    dataset, harness, cost-model, and evaluation-policy versions
    experiment log and effective trial history

QUALIFIED -> ELIGIBLE
    portfolio eligibility evidence
    residual statistics
    incrementality result

ELIGIBLE -> SHADOW | PAPER | ACTIVE
    active portfolio configuration where the alpha affects composition
    live monitoring baseline
    position-construction configuration
    risk configuration
    execution configuration
    deployment configuration for the selected environment

ACTIVE | DEGRADED | DISABLED -> another permitted live state
    alpha monitoring and health evidence
    active risk policy and risk action where intervention applies

ACTIVE | DEGRADED | DISABLED -> RETIRED
    portfolio and alpha feedback evidence
    result of the active retirement rules
```

A missing required transition artifact prevents only that transition. It does not rewrite the current lifecycle state or stop unrelated operating loops.

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

Artifact invariants are:

```text
Every Required Operating Artifact has one authoritative owner,
at least one producer, and at least one named consumer.

Every required consumer input resolves to the canonical artifact inventory.

Every artifact produced by the operating algorithm resolves to the inventory.

A required artifact with no consumer indicates likely excess scope.

A required consumer input with no producer indicates an incomplete model.

A Supporting Artifact never authorizes or changes a system decision.

Authoritative mutable runtime state is never duplicated as a project artifact.

Missing or invalid Required Operating Artifacts block only their declared
dependent activities unless safety requires blocking new exposure or startup.
```

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

    IF a Required Operating Artifact for runtime startup is missing or invalid:
        runtime does not start

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

        IF Required Operating Artifacts for candidate evaluation are missing:
            stop evaluation for that candidate
            do not advance its lifecycle state
            keep existing live runtime unaffected
            CONTINUE

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

            IF Required Operating Artifacts for activation are missing:
                do not publish or activate the result
                keep the current active composition
                CONTINUE

            publish active composition and weights as one versioned artifact
            record newly active alphas with alpha.lifecycle_state = ACTIVE


LIVE MARKET EVENT

    ON each market event:

        market state comes from Nautilus Cache

        IF active Required Operating Artifacts for risk or execution
        are missing or invalid:
            block new exposure under the active fail-closed policy
            preserve Nautilus authoritative runtime state
            CONTINUE

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

        IF a Supporting Artifact cannot be produced:
            preserve its authoritative Required Operating Artifacts
            continue unrelated operating and feedback activities
            record degraded reporting or observability

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

10.1 Data capability. The project applies freshness, expected-gap, session, and validity policy to Nautilus data and Cache state. Nautilus remains the source of runtime market state. Project data capability produces Required Operating data-health evidence and may emit Supporting data-quality reports.

10.2 Alpha research capability. The Quantitative Researcher owns research hypotheses, seed expressions, research policy, and interpretation. The system consumes Required Operating alpha-mining inputs and produces Required Operating candidate evidence, experiment history, lifecycle records, monitoring baselines and health evidence. It produces tear sheets as Supporting Artifacts.

10.3 Portfolio research capability. The Portfolio Researcher owns pool-admission, composition, combination, weighting, benchmark, deployment, contribution, and retirement policy. The system produces Required Operating eligibility evidence, active portfolio configuration, desired targets, decision attribution and portfolio feedback evidence. It may emit Supporting portfolio review reports.

10.4 Execution research capability. The Execution Researcher owns cost and execution-policy research. The project consumes Required Operating execution configuration and produces Required Operating primary-order attribution, execution metrics and cost-model evidence. It may emit Supporting execution review reports. Nautilus owns orders, execution algorithms, fills, positions, accounts, and reconciliation.

10.5 Risk research capability. The Risk Researcher owns sizing, budgets, limits, intervention, escalation, and restart policy. The project consumes Required Operating risk configuration and evidence, then produces allowed targets and Required Operating risk-action records automatically. Supporting risk reports never replace the active policy. Nautilus enforces last-mile order checks and trading state.

10.6 Core shared capability. The project maintains versioned catalogs, artifacts, lifecycle records, pool membership, experiment provenance, monitoring history, and deployment configuration without duplicating Nautilus runtime state.

10.7 Continuous research feedback capability. Production and research evidence feeds role-owned candidate work. The system consumes Required Operating feedback evidence and produces candidate model or policy versions for offline evaluation, shadow or paper validation where required, and accepted-version promotion. Supporting reports assist interpretation but never authorize promotion. Evidence arrival never mutates an active model or policy.

10.8 Artifact coverage rules. Every capability input and output resolves to the canonical Section 6 inventory. Every Required Operating Artifact has one authoritative owner, a producer, and a named consumer. A required artifact with no consumer is excess scope; a required consumer input with no producer is an incomplete operating model. Supporting Artifacts resolve to authoritative inputs and remain non-blocking.

## 11. Implementation Boundary

This decision does not remove or approve any particular existing `quant_api` method. Existing code remains evidence of current behavior. Required Operating Artifacts define mandatory capability inputs, outputs, evidence, ownership, and failure semantics for requirements derivation. Supporting Artifacts are also in the current implementation scope, but their failure remains non-blocking. Neither class decides an API, database, serialization, file format, or report renderer.

After this operating model is approved, implementation planning must audit the code and classify each existing method as one of four outcomes: retain as a valid capability boundary, wire to an existing Rust primitive, delegate to Nautilus, or remove because it represents researcher work or duplicate runtime ownership.

Do not invent replacement methods for researcher-owned activities. Research hypotheses, seed expressions, search configuration, fitness configuration, and candidate model or policy versions are artifact boundaries, not pre-approved APIs. In particular, the absence of an alpha-hypothesis-generation method does not authorize a submission, registration, or creation API without a separate use case and contract discussion.

## 12. Status and Acceptance

This decision remains `triaged` until the owner reviews the complete DEC-024 copy-patch, the artifact-by-artifact classification, lifecycle and algorithm dependencies, missing or invalid behavior, coverage rules, and current implementation scope. While triaged, DEC-024 remains the current implementation-planning draft and OBS-020 remains open. After approval, DEC-025 may supersede DEC-024 and resolve OBS-020.

## Related Notes

- [OBS-020](../observations/OBS-020-artifact-criticality-taxonomy.md) - open finding defining the Required Operating and Supporting Artifact correction applied here.
- [DEC-024](DEC-024-continuous-research-replenishment-operating-model.md) - complete immediate predecessor copied and patched by this decision.
- [OBS-019](../observations/OBS-019-continuous-research-replenishment.md) - open finding that defines the four researcher feedback loops and seed-expression artifact boundary preserved here.
- [OBS-018](../observations/OBS-018-operating-model-contract-leakage.md) - finding that researcher activities and component flows leaked into premature method contracts.
- [DEC-021](DEC-021-actor-artifact-capability-operating-model.md) - complete immediate predecessor copied and patched by this decision.
- [DEC-019](DEC-019-systematic-trading-lifecycle-operating-model.md) - original method-shaped operating-model draft.
- [DEC-020](DEC-020-systematic-trading-operating-model-correction.md) - runtime-ownership correction preserved through DEC-021.
- [framework lifecycle](../../enhanced/framework-lifecycle.md) - frozen component, build-phase, and runtime-loop distinctions.
- [alpha mining](../../enhanced/stages/stage-0-alpha-mining.md) - frozen human-seed and machine-search boundary.
- [risk overlay and monitoring](../../enhanced/stages/stage-7-risk-overlay-monitoring.md) - frozen automatic runtime-risk boundary.
