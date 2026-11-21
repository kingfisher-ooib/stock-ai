# 1475 Paper Forward Batch Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import one or more new 1475 daily bars from local CSV or JSON into the existing paper-forward journal with all-or-nothing validation.

**Architecture:** A focused parser normalizes CSV/JSON and anchors provenance to the input hash. The paper-forward module advances all rows in memory, then persists the resulting journal records and state once. A thin CLI assembles fixed snapshot history and prints a compact summary.

**Tech Stack:** Python 3.12 standard library, existing stock_ai paper-forward module, pytest.

**Spec:** `docs/superpowers/specs/2026-11-15-paper-forward-batch-import-design.md`

## Global Constraints

- No network, broker or real order.
- Preserve the three fixed rules and 5bp-per-side cost assumption.
- Reject the complete batch without mutation if any row fails.
- Preserve source file SHA-256 in provenance.
- Do not accept dates at or before the current checkpoint.

## Review Focus

- CSV numeric strings and JSON numeric values normalize identically.
- Duplicate or malformed rows fail before checkpoint mutation.
- One common observation timestamp may apply to several sequential bars.
- A failure on the second row must leave original state and files unchanged.
- Multiple journal records must extend the existing hash chain in exact date order.

---

### Task 1: CSV/JSON batch parser

**Files:**
- Create: `src/stock_ai/data/forward_import.py`
- Create: `tests/test_forward_import.py`

**Interfaces:**
- Produces: `load_forward_bars(path: Path, *, observed_at_utc: str | None = None) -> list[dict]`.

- [ ] Add failing tests for CSV, JSON object/array, fallback observation/provenance, duplicate dates and missing fields.
- [ ] Implement minimal normalized parser and source hash provenance.
- [ ] Run focused tests.

### Task 2: Transactional in-memory batch advancement

**Files:**
- Modify: `src/stock_ai/backtest/paper_forward.py`
- Modify: `tests/test_paper_forward.py`

**Interfaces:**
- Produces: `advance_forward_batch(state, history, bars, journal_records) -> tuple[dict, list[dict]]` and `append_checkpoints(...)`.

- [ ] Add failing tests for two valid rows with one observation time and second-row failure without mutation.
- [ ] Permit equal observation timestamps while rejecting regressions.
- [ ] Implement batch advancement and one persistence step.
- [ ] Run focused and full tests.

### Task 3: Batch CLI and documentation

**Files:**
- Create: `scripts/import_1475_forward_bars.py`
- Modify: `README.md`

**Interfaces:**
- CLI accepts `--input PATH` and optional `--observed-at ISO8601`.

- [ ] Implement the thin CLI using fixed snapshot hash verification.
- [ ] Run CLI help and a temporary-file integration check without modifying the real checkpoint.
- [ ] Document CSV/JSON examples and output meaning.
- [ ] Run complete verification.
