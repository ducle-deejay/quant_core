---
doc_id: DEC-019
title: Systematic trading lifecycle operating model
type: decision
owner: research
status: triaged
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [operating-model, lifecycle, module-ownership, live-trading]
source: "owner discussion: systematic-trading operating model"
design:
  - OV-LIFECYCLE
  - STG-0-ALPHA-MINING
  - STG-1-CANONICAL-SIM
  - STG-2-EVALUATION
  - STG-3-ORTHOGONALIZATION
  - STG-4-COMBINATION
  - STG-5-POSITION-CONSTRUCTION
  - STG-6-TRADE-SCHEDULING
  - STG-7-RISK-OVERLAY
code:
  - src/market_data
  - src/quant_api
  - src/trading
test: []
---

# DEC-019 — Systematic trading lifecycle operating model

## Applied vocabulary classification

| Current or ambiguous term | Applied wording | Meaning |
|---|---|---|
| `STATE` used to aggregate all data | `DATA / STORAGE` | Classify data by ownership and persistence |
| `positions` | `desired_target`, `allowed_target`, `internal_position`, `broker_position` | Separate intent, permission, and realized state |
| `alpha_pool` | `eligible_alpha_pool`, `active_alpha_pool` | Research qualification is not live deployment |
| `Portfolio.include_alpha()` | `Portfolio.register_eligible_alpha()` | Register an eligible alpha without activating it |
| `target_position` | `desired_target` | Exposure Portfolio wants |
| `allowed_target` | Keep | Exposure Risk permits |
| `experiment_log` used for live history | `experiment_log`, `alpha_monitoring_history` | Separate research provenance from live time series |
| Disable rules inside an alpha baseline | `live_monitoring_baseline`, `risk_intervention_policy` | Alpha defines expectations; Risk defines actions |
| `Portfolio.retire_failed_alphas()` | Decompose by ownership | Alpha diagnosis, Portfolio contribution/removal, and Risk emergency intervention |
| `DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY` | Keep | Baseline operating cadence |
| `harness` | Keep | `backtest harness`, `research harness` |
| `canonical harness` | Make specific | `standard backtest harness` |
| `canonical simulation` | Replace | `standardized backtest` |
| `orthogonalization` | Keep unchanged | `orthogonalize_against_pool()` |
| `residualization` | Keep when referring to regression residuals | `residualize_returns()` |
| `residual` | Keep | `residual_returns`, `residual_statistics` |
| `incremental-value gate` | Make specific | `evaluate_incrementality()` |
| `dossier` | Replace | `backtest_result`, `evaluation_result`, `residual_statistics` |
| `spec_sheet` | Split | `tear_sheet` for human review; `live_monitoring_baseline` for runtime |
| `trial_registry` | Replace | `experiment_log` |
| `alpha_registry` | Replace | `alpha_library` |
| `habitat` | Replace | `regime_profile` |
| `admission` | Replace | `portfolio_eligibility` |
| `promotion` | Keep for deployment transitions | `activate_alpha()` or a lifecycle transition |
| `divergence` | Make specific | `live_vs_backtest_drift` |
| `kill switch` | Keep | Portfolio-level or system-level emergency action |
| `kill criteria` | Replace | `risk_intervention_policy`, `retirement_rules` |
| `post-mortem` | Keep | Alpha failure and operational incident |
| `factory` | Keep only at the operating-model level | Do not use it in method names |
| `immune system` | Remove from technical vocabulary | `independent risk process` |
| `artifact` | Name the concrete object | `weights`, `cost_model`, `tear_sheet`, `baseline`, `report` |

## Module structure

```text
SystematicTradingSystem
├── Data
│   ├── connect_live_feed()
│   ├── update_market_state()
│   └── check_live_data()
│
├── Alpha
│   ├── generate_hypotheses()
│   ├── generate_candidates()
│   ├── run_standard_backtest()
│   ├── evaluate_candidate()
│   ├── log_experiment()
│   ├── record_lifecycle_transition()
│   ├── build_tear_sheet()
│   ├── define_live_monitoring_baseline()
│   ├── compute_live_scores()
│   ├── compare_live_to_baseline()
│   ├── record_live_observation()
│   ├── get_latest_health_assessments()
│   ├── get_latest_health_assessment()
│   ├── record_disable()
│   ├── record_retirement()
│   ├── rerun_parameter_stability()
│   ├── review_backtest_harness()
│   ├── version_backtest_harness()
│   ├── update_candidate_generation_rules()
│   └── update_evaluation_rules()
│
├── Portfolio
│   ├── orthogonalize_against_pool()
│   ├── evaluate_incrementality()
│   ├── register_eligible_alpha()
│   ├── select_active_composition()
│   ├── standardize_scores()
│   ├── estimate_alpha_pnl_volatility()
│   ├── fit_weights()
│   ├── compare_weights_out_of_sample()
│   ├── publish_active_composition()
│   ├── compute_decision_contributions()
│   ├── combine_scores()
│   ├── build_target_position()
│   ├── record_decision()
│   ├── attribute_pnl()
│   ├── review_pool()
│   ├── assess_portfolio_contribution()
│   ├── evaluate_pool_membership()
│   ├── remove_alpha()
│   └── rerun_pool_orthogonalization()
│
├── Execution
│   ├── connect_gateway()
│   ├── restore_execution_ledger()
│   ├── get_broker_position()
│   ├── get_open_orders()
│   ├── get_account_state()
│   ├── compare_internal_with_broker()
│   ├── create_order_schedule()
│   ├── advance_order_schedules()
│   ├── submit_actions()
│   ├── record_order_event()
│   ├── update_order_state()
│   ├── update_position_from_fill()
│   ├── update_execution_metrics()
│   ├── compare_position_with_broker()
│   ├── manage_open_positions()
│   ├── cancel_open_orders()
│   ├── flatten_positions()
│   ├── disconnect()
│   └── fit_cost_model()
│
└── Risk
    ├── validate_startup_state()
    ├── block_trading()
    ├── enable_trading()
    ├── handle_data_failure()
    ├── apply_portfolio_constraints()
    ├── evaluate_alpha_assessment()
    ├── block_new_orders()
    ├── block_new_exposure()
    ├── monitor()
    ├── allow_trading()
    ├── reduce_risk_multiplier()
    ├── send_warning()
    ├── send_critical_alert()
    ├── lock_restart()
    └── review_risk_budgets()
```

## DATA / STORAGE

```text
Data storage
    market_data
    market_state
    data_health

Research database
    experiment_log
        candidate
        parameters
        dataset_version
        harness_version
        cost_model_version
        test_results
        verdict
    tear_sheets

Alpha store
    alpha_library
    alpha_lifecycle_state
    live_monitoring_baselines

Live monitoring store
    alpha_monitoring_history
        date
        live_ic
        live_pnl
        drawdown
        turnover
        realized_cost
        regime
        baseline_comparison
        health_status
    alpha_health_assessments

Portfolio configuration / ledger
    eligible_alpha_pool
    active_alpha_pool
    residual_statistics
    portfolio_weights
    deployment_policy
    decision_contributions
        decision_id
        timestamp
        alpha_scores
        standardized_scores
        portfolio_weights
        alpha_contributions
        composite_score
        desired_target
        allowed_target
    pnl_attribution

Risk configuration and state store
    allocated_risk_budget
    hard_exposure_limits
    leverage_cap
    risk_intervention_policy
    retirement_rules
    system_trading_state
    risk_actions

Execution ledger
    parent_orders
    working_orders
    order_events
    fills
    internal_position
    broker_position
    account_state
    execution_metrics

Operating policy store
    session_policy
```

## Alpha lifecycle

```text
CANDIDATE
    ├── REJECTED
    └── QUALIFIED
            └── ELIGIBLE
                    ├── SHADOW      optional by deployment policy
                    ├── PAPER       optional by deployment policy
                    └── ACTIVE
                            ├── DEGRADED
                            │       ├── ACTIVE
                            │       ├── DISABLED
                            │       └── RETIRED
                            ├── DISABLED
                            │       ├── ACTIVE
                            │       └── RETIRED
                            └── RETIRED
```

Semantic:

```text
QUALIFIED
    passed standalone research evaluation

ELIGIBLE
    passed standalone evaluation and pool incrementality evaluation

SHADOW
    runs on live data and produces scores, targets, and monitoring metrics
    without affecting the active portfolio or creating orders and fills

PAPER
    runs through execution simulation and produces simulated orders and fills
    without using real capital

ACTIVE
    selected by portfolio deployment policy and assigned active weight

DEGRADED
    remains active, but Alpha diagnosed material deterioration against baseline
    may recover to ACTIVE, be constrained by Risk, or transition to DISABLED

DISABLED
    live trading permission removed; potentially reversible

RETIRED
    removed from the investable alpha lifecycle
```

## Core operating invariants

```text
Alpha
    produces forecast

Portfolio
    produces desired exposure

Risk
    produces permitted exposure

Execution
    produces realized exposure

Portfolio
    attributes realized economics

Alpha
    diagnoses live alpha behavior

Risk
    decides whether trading may continue
```

## ALGORITHM SYSTEMATIC_TRADING_LIFECYCLE

```text
ALGORITHM SYSTEMATIC_TRADING_LIFECYCLE


INITIALIZATION

    load active configuration

    connect market data
    connect execution gateway

    broker_position ← Execution.get_broker_position()
    broker_orders ← Execution.get_open_orders()
    account_state ← Execution.get_account_state()

    internal_state ← Execution.restore_execution_ledger()

    state_check ← Execution.compare_internal_with_broker(...)

    data_check ← Data.check_live_data(...)

    risk_check ← Risk.validate_startup_state(...)

    IF all checks PASS:
        enable_trading
    ELSE:
        remain_blocked


RESEARCH_LOOP

    WHILE system_active:

        hypotheses ← Alpha.generate_hypotheses(
            researcher_inputs,
            post_mortems,
            live_failures,
            family_statistics
        )

        candidates ← Alpha.generate_candidates(
            hypotheses,
            market_data
        )

        FOR candidate IN candidates:

            Alpha.record_lifecycle_transition(
                candidate,
                CANDIDATE
            )

            backtest_result ← Alpha.run_standard_backtest(
                candidate,
                market_data,
                backtest_harness,
                cost_model
            )

            evaluation_result ← Alpha.evaluate_candidate(
                backtest_result,
                experiment_log
            )

            Alpha.log_experiment(
                candidate,
                backtest_result,
                evaluation_result
            )

            IF evaluation_result.verdict != PASS:

                Alpha.record_lifecycle_transition(
                    candidate,
                    REJECTED
                )

                CONTINUE

            Alpha.record_lifecycle_transition(
                candidate,
                QUALIFIED
            )

            orthogonalization_result ←
                Portfolio.orthogonalize_against_pool(
                    candidate.daily_net_pnl,
                    active_alpha_pool.daily_net_pnl
                )

            incrementality_result ←
                Portfolio.evaluate_incrementality(
                    orthogonalization_result.residual_returns,
                    orthogonalization_result.residual_statistics
                )

            Alpha.log_experiment(
                candidate,
                backtest_result,
                incrementality_result
            )

            IF incrementality_result.verdict != PASS:

                Alpha.record_lifecycle_transition(
                    candidate,
                    REJECTED
                )

                CONTINUE

            tear_sheet ← Alpha.build_tear_sheet(
                candidate,
                backtest_result,
                orthogonalization_result,
                incrementality_result
            )

            live_monitoring_baseline ←
                Alpha.define_live_monitoring_baseline(
                    backtest_result,
                    orthogonalization_result
                )

            Portfolio.register_eligible_alpha(
                candidate,
                orthogonalization_result.residual_statistics
            )

            Alpha.record_lifecycle_transition(
                candidate,
                ELIGIBLE
            )


PORTFOLIO_REFIT_LOOP

    WEEKLY:

        composition_candidate ←
            Portfolio.select_active_composition(
                eligible_alpha_pool,
                active_alpha_pool,
                residual_statistics,
                deployment_policy
            )

        standardized_scores ← Portfolio.standardize_scores(
            composition_candidate.score_history
        )

        alpha_pnl_volatility ←
            Portfolio.estimate_alpha_pnl_volatility(
                composition_candidate,
                residual_statistics
            )

        candidate_weights ← Portfolio.fit_weights(
            standardized_scores,
            alpha_pnl_volatility,
            residual_statistics
        )

        comparison ← Portfolio.compare_weights_out_of_sample(
            candidate_weights,
            benchmark_weights
        )

        IF comparison.candidate_beats_benchmark:

            portfolio_weights ← candidate_weights

        ELSE:

            portfolio_weights ← benchmark_weights

        Portfolio.publish_active_composition(
            composition_candidate,
            portfolio_weights
        )

        FOR alpha IN composition_candidate.newly_active:

            Alpha.record_lifecycle_transition(
                alpha,
                ACTIVE
            )


LIVE_EVENT_LOOP

    ON each_market_event:

        market_state ← Data.update_market_state(
            market_data
        )

        data_check ← Data.check_live_data(
            market_state
        )

        IF data_check.failed:

            Risk.handle_data_failure(data_check)

            CONTINUE

        alpha_scores ← Alpha.compute_live_scores(
            active_alpha_pool,
            market_state
        )

        standardized_scores ← Portfolio.standardize_scores(
            alpha_scores
        )

        alpha_contributions ←
            Portfolio.compute_decision_contributions(
                standardized_scores,
                portfolio_weights
            )

        composite_score ← Portfolio.combine_scores(
            standardized_scores,
            portfolio_weights
        )

        desired_target ← Portfolio.build_target_position(
            composite_score,
            volatility_estimate,
            allocated_risk_budget
        )

        allowed_target ← Risk.apply_portfolio_constraints(
            desired_target,
            leverage_cap,
            drawdown_state,
            account_state,
            market_state
        )

        decision_record ← Portfolio.record_decision(
            timestamp = timestamp,
            alpha_scores = alpha_scores,
            standardized_scores = standardized_scores,
            portfolio_weights = portfolio_weights,
            alpha_contributions = alpha_contributions,
            composite_score = composite_score,
            desired_target = desired_target,
            allowed_target = allowed_target
        )

        execution_actions ← Execution.create_order_schedule(
            decision_id = decision_record.decision_id,
            target_version = decision_record.target_version,
            allowed_target = allowed_target,
            internal_position = internal_position,
            parent_orders = parent_orders,
            working_orders = working_orders,
            order_book = market_state.order_book,
            alpha_decay = alpha_decay,
            cost_model = cost_model
        )

        Execution.submit_actions(
            execution_actions
        )


    ON execution_timer_event:

        actions ← Execution.advance_order_schedules(
            working_orders,
            current_time,
            market_state
        )

        Execution.submit_actions(actions)


    ON broker_order_event:

        Execution.record_order_event(
            broker_order_event
        )

        order_state ← Execution.update_order_state(
            parent_orders,
            working_orders,
            broker_order_event
        )

        parent_orders ← order_state.parent_orders
        working_orders ← order_state.working_orders

        broker_position ← Execution.get_broker_position()

        IF broker_order_event.is_fill:

            internal_position ←
                Execution.update_position_from_fill(
                    internal_position,
                    broker_order_event
                )

            fills.append(
                broker_order_event
            )

            execution_metrics ←
                Execution.update_execution_metrics(
                    execution_metrics,
                    broker_order_event
                )

        position_check ←
            Execution.compare_position_with_broker(
                internal_position,
                broker_position
            )

        IF position_check.failed:

            Risk.block_new_orders()
            Risk.send_critical_alert(position_check)
            Risk.block_trading(position_check)

            system_trading_state ← BLOCKED

            ENTER INITIALIZATION


RISK_LOOP

    CONTINUOUSLY:

        alpha_health_assessments ←
            Alpha.get_latest_health_assessments()

        FOR assessment IN alpha_health_assessments:

            alpha_risk_action ←
                Risk.evaluate_alpha_assessment(
                    assessment,
                    portfolio_state
                )

            IF alpha_risk_action.force_disable:

                Risk.block_new_exposure(
                    assessment.alpha
                )

                Execution.manage_open_positions(
                    assessment.alpha
                )

                Alpha.record_disable(
                    assessment.alpha,
                    alpha_risk_action
                )

                Alpha.record_lifecycle_transition(
                    assessment.alpha,
                    DISABLED
                )

        risk_status ← Risk.monitor(
            exposure,
            PnL,
            drawdown,
            implementation_shortfall,
            position_tracking_error,
            fill_rate,
            reject_rate,
            latency,
            feed_health,
            process_heartbeat,
            alpha_health_assessments
        )

        CASE risk_status:

            NORMAL:
                Risk.allow_trading()

            DEGRADED:
                Risk.reduce_risk_multiplier()
                Risk.send_warning(risk_status)

            SOFT_HALT:
                Risk.block_new_exposure()
                Execution.manage_open_positions()

            FLATTEN:
                Execution.cancel_open_orders()
                Execution.flatten_positions()
                Risk.send_critical_alert(risk_status)

            SHUTDOWN:
                Execution.cancel_open_orders()
                Execution.disconnect()
                Risk.lock_restart()


FEEDBACK_LOOP

    DAILY:

        pnl_attribution ← Portfolio.attribute_pnl(
            decision_contributions,
            fills
        )

        alpha_health_assessments ←
            Alpha.compare_live_to_baseline(
                pnl_attribution,
                live_monitoring_baselines
            )

        Alpha.record_live_observation(
            pnl_attribution,
            alpha_health_assessments
        )


    WEEKLY:

        cost_model ← Execution.fit_cost_model(
            fills,
            implementation_shortfall
        )

    MONTHLY:

        pool_review ← Portfolio.review_pool(
            active_alpha_pool
        )

        FOR alpha IN active_alpha_pool:

            alpha_health ←
                Alpha.get_latest_health_assessment(
                    alpha
                )

            portfolio_contribution ←
                Portfolio.assess_portfolio_contribution(
                    alpha,
                    pool_review,
                    decision_contributions,
                    pnl_attribution
                )

            retirement_review ←
                Portfolio.evaluate_pool_membership(
                    alpha_health,
                    portfolio_contribution,
                    retirement_rules
                )

            IF retirement_review.retire:

                Portfolio.remove_alpha(
                    alpha
                )

                Alpha.record_retirement(
                    alpha,
                    retirement_review
                )

                Alpha.record_lifecycle_transition(
                    alpha,
                    RETIRED
                )

        Alpha.rerun_parameter_stability()


    QUARTERLY:

        residual_statistics ←
            Portfolio.rerun_pool_orthogonalization(
                active_alpha_pool
            )

        allocated_risk_budget ←
            Risk.review_risk_budgets(
                portfolio_performance,
                portfolio_drawdown,
                family_correlations
            )

        harness_review ← Alpha.review_backtest_harness(
            data_quality,
            realized_execution_costs,
            live_vs_backtest_drift
        )

        IF harness_review.requires_new_version:

            Alpha.version_backtest_harness(
                harness_review
            )

    post_mortems
        → Alpha.generate_hypotheses()
        → Alpha.update_candidate_generation_rules()
        → Alpha.update_evaluation_rules()


END ALGORITHM
```

## Method table

### Data

| Method | Module | Role |
|---|---|---|
| `Data.connect_live_feed()` | Data | Connect to the live market-data source |
| `Data.update_market_state()` | Data | Update market state from a market event |
| `Data.check_live_data()` | Data | Check live-data freshness, gaps, and validity |

### Alpha

| Method | Module | Role |
|---|---|---|
| `Alpha.generate_hypotheses()` | Alpha | Generate research hypotheses from researcher input and feedback |
| `Alpha.generate_candidates()` | Alpha | Generate candidate expressions from hypotheses |
| `Alpha.run_standard_backtest()` | Alpha | Run a candidate through the standard backtest harness |
| `Alpha.evaluate_candidate()` | Alpha | Apply forecast, cost, stability, and multiple-testing checks |
| `Alpha.log_experiment()` | Alpha | Record immutable-ish research provenance and the evaluation result |
| `Alpha.record_lifecycle_transition()` | Alpha | Record a change in alpha lifecycle state |
| `Alpha.build_tear_sheet()` | Alpha | Build a human-readable alpha research report |
| `Alpha.define_live_monitoring_baseline()` | Alpha | Define expected live behavior and statistical confidence bands |
| `Alpha.compute_live_scores()` | Alpha | Compute live forecasts for the active alpha pool |
| `Alpha.compare_live_to_baseline()` | Alpha | Diagnose live alpha health against its baseline |
| `Alpha.record_live_observation()` | Alpha | Record live metrics and health assessments in monitoring history |
| `Alpha.get_latest_health_assessments()` | Alpha | Return the latest health assessments for active alphas |
| `Alpha.get_latest_health_assessment()` | Alpha | Return the latest health assessment for one alpha |
| `Alpha.record_disable()` | Alpha | Record that Risk disabled an alpha and why |
| `Alpha.record_retirement()` | Alpha | Record permanent retirement and its supporting evidence |
| `Alpha.rerun_parameter_stability()` | Alpha | Rerun parameter-plateau and stability checks |
| `Alpha.review_backtest_harness()` | Alpha | Review the harness using data, cost, and live evidence |
| `Alpha.version_backtest_harness()` | Alpha | Publish a new version of the standard backtest harness |
| `Alpha.update_candidate_generation_rules()` | Alpha | Update the search space and candidate constraints |
| `Alpha.update_evaluation_rules()` | Alpha | Update candidate evaluation rules |

### Portfolio

| Method | Module | Role |
|---|---|---|
| `Portfolio.orthogonalize_against_pool()` | Portfolio | Remove the portion of candidate PnL explained by the active pool |
| `Portfolio.evaluate_incrementality()` | Portfolio | Determine whether the residual retains sufficient incremental edge |
| `Portfolio.register_eligible_alpha()` | Portfolio | Register an eligible alpha without activating it |
| `Portfolio.select_active_composition()` | Portfolio | Select the active composition from eligible and currently active alphas |
| `Portfolio.standardize_scores()` | Portfolio | Standardize alpha scores before combination |
| `Portfolio.estimate_alpha_pnl_volatility()` | Portfolio | Estimate PnL volatility for each alpha |
| `Portfolio.fit_weights()` | Portfolio | Fit alpha combination weights |
| `Portfolio.compare_weights_out_of_sample()` | Portfolio | Compare candidate weights with the out-of-sample benchmark |
| `Portfolio.publish_active_composition()` | Portfolio | Publish the active alpha set and portfolio weights |
| `Portfolio.compute_decision_contributions()` | Portfolio | Compute each alpha's contribution at decision time |
| `Portfolio.combine_scores()` | Portfolio | Combine standardized scores into a composite score |
| `Portfolio.build_target_position()` | Portfolio | Convert the composite score into a desired target using the allocated risk budget |
| `Portfolio.record_decision()` | Portfolio | Persist the required decision-time fields and assign `decision_id` |
| `Portfolio.attribute_pnl()` | Portfolio | Attribute realized PnL using decision-time contribution history |
| `Portfolio.review_pool()` | Portfolio | Review performance, concentration, and redundancy |
| `Portfolio.assess_portfolio_contribution()` | Portfolio | Assess one alpha's marginal portfolio contribution |
| `Portfolio.evaluate_pool_membership()` | Portfolio | Evaluate scheduled membership using health and portfolio evidence |
| `Portfolio.remove_alpha()` | Portfolio | Remove an alpha from the active pool |
| `Portfolio.rerun_pool_orthogonalization()` | Portfolio | Rerun orthogonalization for the active pool |

### Execution

| Method | Module | Role |
|---|---|---|
| `Execution.connect_gateway()` | Execution | Connect to the broker or execution venue |
| `Execution.restore_execution_ledger()` | Execution | Restore positions, parent orders, and working orders |
| `Execution.get_broker_position()` | Execution | Read the broker-confirmed position |
| `Execution.get_open_orders()` | Execution | Read broker-confirmed open orders |
| `Execution.get_account_state()` | Execution | Read account, margin, and buying-power state |
| `Execution.compare_internal_with_broker()` | Execution | Compare restored internal state with broker positions and orders |
| `Execution.create_order_schedule()` | Execution | Apply the target version, invalidate stale intent, and create the order schedule |
| `Execution.advance_order_schedules()` | Execution | Process timer slices, timeouts, cancel/replace actions, and session transitions |
| `Execution.submit_actions()` | Execution | Submit new-order, cancel, or replace actions |
| `Execution.record_order_event()` | Execution | Record acknowledgements, rejects, cancels, replacements, and fills |
| `Execution.update_order_state()` | Execution | Update parent-order and working-order state from a broker event |
| `Execution.update_position_from_fill()` | Execution | Update the internal position from a confirmed fill |
| `Execution.update_execution_metrics()` | Execution | Update fill, shortfall, reject, and latency metrics |
| `Execution.compare_position_with_broker()` | Execution | Compare the internal position with the broker position |
| `Execution.manage_open_positions()` | Execution | Manage existing exposure when additional risk is blocked |
| `Execution.cancel_open_orders()` | Execution | Cancel non-terminal orders |
| `Execution.flatten_positions()` | Execution | Move positions to zero in response to a Risk action |
| `Execution.disconnect()` | Execution | Disconnect the execution gateway |
| `Execution.fit_cost_model()` | Execution | Calibrate the cost model from realized fills |

### Risk

| Method | Module | Role |
|---|---|---|
| `Risk.validate_startup_state()` | Risk | Confirm that data, broker, account, and internal execution state are safe |
| `Risk.block_trading()` | Risk | Keep the entire system in a blocked state |
| `Risk.enable_trading()` | Risk | Enable trading after startup checks pass |
| `Risk.handle_data_failure()` | Risk | Choose whether to block, halt, or flatten after a live-data failure |
| `Risk.apply_portfolio_constraints()` | Risk | Convert the desired target into the allowed target |
| `Risk.evaluate_alpha_assessment()` | Risk | Convert an Alpha diagnosis into a live risk action |
| `Risk.block_new_orders()` | Risk | Block new orders when execution state is not trustworthy |
| `Risk.block_new_exposure()` | Risk | Block additional exposure at system or alpha scope |
| `Risk.monitor()` | Risk | Monitor portfolio, alpha, execution, data, and process health |
| `Risk.allow_trading()` | Risk | Maintain the normal trading state |
| `Risk.reduce_risk_multiplier()` | Risk | Reduce permitted exposure |
| `Risk.send_warning()` | Risk | Send a warning alert |
| `Risk.send_critical_alert()` | Risk | Send a critical alert |
| `Risk.lock_restart()` | Risk | Lock restart after shutdown |
| `Risk.review_risk_budgets()` | Risk | Review allocated risk budgets across strategy families |
