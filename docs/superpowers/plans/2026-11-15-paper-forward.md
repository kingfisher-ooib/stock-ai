# 1475 Paper Forward Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, tamper-evident paper-forward journal for the three frozen 1475 rules.

**Architecture:** A pure paper-forward module validates one new daily bar, settles frozen prior decisions, creates the next decisions from confirmed history, and hash-chains each journal record. Thin CLI scripts initialize from the fixed snapshot and ingest one user-supplied JSON bar.

**Tech Stack:** Python 3.12, existing DuckDB/Parquet loader, RiskEngine, pytest, JSON/JSONL and SHA-256.

**Spec:** `docs/superpowers/specs/2026-11-15-paper-forward-design.md`

## Global Constraints

- No web fetch, broker connection, API credential or real order.
- Fixed symbol 1475, three registered rules, 100,000 JPY per rule, 10-unit lot, 5bp per side and zero fixed commission assumption.
- Only a strictly later, validated, timezone-labelled bar may advance state.
- Verify the base snapshot hash and complete journal chain before mutation.
- Never count no-trade observations as wins.

## Review Focus

- Duplicate or out-of-order dates must not mutate state or journal.
- Invalid OHLCV or timezone-naive observation times must be rejected.
- A modified journal line or mismatched state tail hash must stop processing.
- An inactive signal must record no trade and zero PnL without a win.
- A gap below the stored stop must skip entry rather than fabricate a stop fill.

---

### Task 1: Forward state and hash-chain initialization

**Files:**
- Create: `src/stock_ai/backtest/paper_forward.py`
- Create: `tests/test_paper_forward.py`

**Interfaces:**
- Produces: `initialize_forward_state(bars, *, base_snapshot_sha256, source_observed_at_utc) -> tuple[dict, dict]`, `hash_record(record: dict) -> str`, and `verify_journal(records: list[dict]) -> str`.

- [ ] Write failing tests for fixed initial decisions, deterministic hashing and tamper rejection.
- [ ] Run the focused tests and confirm failure for missing behavior.
- [ ] Implement minimal initialization and chain verification.
- [ ] Run focused tests and confirm pass.

### Task 2: One-bar settlement and advancement

**Files:**
- Modify: `src/stock_ai/backtest/paper_forward.py`
- Modify: `tests/test_paper_forward.py`

**Interfaces:**
- Consumes: initialized state, full confirmed history, one new bar and journal records.
- Produces: `advance_forward_state(state, history, new_bar, journal_records) -> tuple[dict, dict]`.

- [ ] Write failing tests for a normal trade, inactive signal, gap below stop, duplicate date, invalid OHLCV/time and chain mismatch.
- [ ] Implement fee-aware RiskEngine sizing and fixed 5bp settlement using stored prior decisions.
- [ ] Run focused tests and then the full suite.

### Task 3: Local CLI and first frozen checkpoint

**Files:**
- Create: `scripts/init_1475_paper_forward.py`
- Create: `scripts/record_1475_forward_bar.py`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Initializer verifies the fixed Parquet hash and writes state plus first journal line.
- Recorder accepts `--input PATH`, verifies state/journal, appends exactly one record and atomically replaces state.

- [ ] Add script-level validation through real temporary files in tests.
- [ ] Implement thin scripts and atomic writes.
- [ ] Run all tests.
- [ ] Initialize the real local journal once from the 2026-11-13 snapshot.
- [ ] Inspect the frozen next-bar decisions and document the daily command.
