"""Freeze the first 1475 paper-forward decisions from the fixed snapshot."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from stock_ai.backtest.paper_forward import initialize_forward_state, write_initial_checkpoint
from stock_ai.data.snapshot import load_bars_as_of


ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data/processed/1475-point-in-time-assumed.parquet"
MANIFEST = ROOT / "data/results/1475-snapshot-manifest-2026-11-15.json"
STATE = ROOT / "data/paper/1475-state.json"
JOURNAL = ROOT / "data/paper/1475-journal.jsonl"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    digest = hashlib.sha256(PARQUET.read_bytes()).hexdigest()
    if digest != manifest["parquet_sha256"]:
        raise ValueError("Parquet hash differs from saved snapshot manifest")
    observed_at = manifest["source_observed_at_utc"]
    bars = load_bars_as_of(PARQUET, datetime.fromisoformat(observed_at), mode="observed")
    if len(bars) != 698 or bars[-1]["bar_date"] != "2026-11-13":
        raise ValueError("expected fixed 1475 snapshot was not loaded")
    state, record = initialize_forward_state(
        bars, base_snapshot_sha256=digest, source_observed_at_utc=observed_at,
    )
    write_initial_checkpoint(STATE, JOURNAL, state, record)
    print(json.dumps({
        "last_bar_date": state["last_bar_date"],
        "cost_bps_per_side": state["bps_per_side"],
        "next_decisions": record["next_decisions"],
        "journal_tail_hash": state["journal_tail_hash"],
    }, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
