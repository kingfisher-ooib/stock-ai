# 1475 Three-Signal Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible local screen for three pre-registered 1475 signals under identical execution and risk assumptions.

**Architecture:** Put pure prior-day signal logic in a focused module. Extend the existing intraday simulator with a rule selector while preserving the baseline wrapper, then add one report script that evaluates all fixed combinations and applies the screening gate.

**Tech Stack:** Python 3.12, pytest, existing Parquet snapshot and stock_ai modules.

**Spec:** `docs/superpowers/specs/2026-11-15-three-signal-screen-design.md`

## Global Constraints

- Use only bars confirmed before the simulated trading day.
- Keep execution, stop, Risk Engine, capital and lot assumptions identical across rules.
- Evaluate exactly three named rules and 0/5/10bp per side; do not tune thresholds after results.
- Preserve all failed results and never label the already-seen 2026 interval as untouched.
- No broker connection or order placement.

## Review Focus

- Unknown rule names must fail before simulation.
- A target-day close or volume change must not alter that day's entry decision or size.
- Exactly-equal volume ratio 1.0 must satisfy the registered momentum threshold.
- Too few trades must fail the candidate gate even if PnL is positive.
- Undefined PF or bootstrap bounds must fail the candidate gate.

---

### Task 1: Pure registered signal rules

**Files:**
- Create: `src/stock_ai/backtest/signals.py`
- Create: `tests/test_registered_signals.py`

**Interfaces:**
- Consumes: feature mapping from `compute_features` and prior confirmed close.
- Produces: `REGISTERED_SIGNALS` and `is_signal_active(name: str, features: Mapping[str, float], prior_close: float) -> bool`.

- [ ] Write tests for all three exact rules, the inclusive volume threshold, and unknown names.
- [ ] Run `pytest tests/test_registered_signals.py -q`; expect failure because the module is absent.
- [ ] Implement the minimal pure rule dispatcher.
- [ ] Run `pytest tests/test_registered_signals.py -q`; expect pass.

### Task 2: Simulator rule selection and leakage guard

**Files:**
- Modify: `src/stock_ai/backtest/intraday.py`
- Modify: `tests/test_intraday_backtest.py`

**Interfaces:**
- Consumes: `is_signal_active` from Task 1.
- Produces: optional `signal_name: str = "trend"` on `run_intraday_sma_baseline` with unchanged default behavior.

- [ ] Add failing tests showing a restrictive rule can skip and target-day close/volume cannot alter entry decision.
- [ ] Run the new tests; expect failure because `signal_name` is unsupported.
- [ ] Route the prior-day features and prior close through the registered signal function.
- [ ] Run `pytest tests/test_intraday_backtest.py -q`; expect pass.

### Task 3: Fixed comparison report and candidate gate

**Files:**
- Create: `src/stock_ai/backtest/screening.py`
- Create: `tests/test_screening.py`
- Create: `scripts/run_1475_three_signal_screen.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: simulator summaries for registered rules.
- Produces: `passes_candidate_gate(metrics: dict) -> bool` and `data/results/1475-three-signal-screen-2026-11-15.json`.

- [ ] Add failing tests for every gate condition, including missing metrics and fewer than 30 trades.
- [ ] Run `pytest tests/test_screening.py -q`; expect failure because the module is absent.
- [ ] Implement the minimal gate and fixed report script with snapshot hash verification.
- [ ] Run the complete suite; expect all tests pass.
- [ ] Run the report once and inspect all 18 result cells and candidate decisions.
- [ ] Record the command, assumptions and result link in README.
