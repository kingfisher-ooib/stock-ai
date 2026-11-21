"""Settle prior paper decisions and record one newly observed 1475 daily bar."""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from stock_ai.backtest.paper_forward import advance_forward_state, append_checkpoint, load_checkpoint
from stock_ai.data.snapshot import load_bars_as_of


ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data/processed/1475-point-in-time-assumed.parquet"
MANIFEST = ROOT / "data/results/1475-snapshot-manifest-2026-11-15.json"
STATE = ROOT / "data/paper/1475-state.json"
JOURNAL = ROOT / "data/paper/1475-journal.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="one newly observed daily bar JSON")
    args = parser.parse_args()
    state, records = load_checkpoint(STATE, JOURNAL)
    manifest = json.loads(MANIFEST.read_text())
    digest = hashlib.sha256(PARQUET.read_bytes()).hexdigest()
    if digest != manifest["parquet_sha256"] or digest != state["base_snapshot_sha256"]:
        raise ValueError("base snapshot hash mismatch")
    base = load_bars_as_of(
        PARQUET, datetime.fromisoformat(manifest["source_observed_at_utc"]), mode="observed",
    )
    history = [*base, *state["forward_bars"]]
    new_bar = json.loads(args.input.read_text())
    updated, record = advance_forward_state(state, history, new_bar, records)
    append_checkpoint(STATE, JOURNAL, updated, record)
    print(json.dumps({
        "bar_date": updated["last_bar_date"],
        "settlements": record["settlements"],
        "equity_after_yen": record["equity_after_yen"],
        "next_decisions": record["next_decisions"],
        "journal_tail_hash": updated["journal_tail_hash"],
    }, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
