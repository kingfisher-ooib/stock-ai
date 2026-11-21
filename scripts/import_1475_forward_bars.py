"""Import a local CSV or JSON batch into the 1475 paper-forward journal."""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from stock_ai.backtest.paper_forward import (
    advance_forward_batch,
    append_checkpoints,
    load_checkpoint,
)
from stock_ai.data.forward_import import load_forward_bars
from stock_ai.data.snapshot import load_bars_as_of


ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data/processed/1475-point-in-time-assumed.parquet"
MANIFEST = ROOT / "data/results/1475-snapshot-manifest-2026-11-15.json"
STATE = ROOT / "data/paper/1475-state.json"
JOURNAL = ROOT / "data/paper/1475-journal.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="CSV or JSON containing new daily bars")
    parser.add_argument(
        "--observed-at", help="timezone-labelled observation time applied where a row omits it",
    )
    args = parser.parse_args()
    state, journal = load_checkpoint(STATE, JOURNAL)
    manifest = json.loads(MANIFEST.read_text())
    digest = hashlib.sha256(PARQUET.read_bytes()).hexdigest()
    if digest != manifest["parquet_sha256"] or digest != state["base_snapshot_sha256"]:
        raise ValueError("base snapshot hash mismatch")
    base = load_bars_as_of(
        PARQUET, datetime.fromisoformat(manifest["source_observed_at_utc"]), mode="observed",
    )
    history = [*base, *state["forward_bars"]]
    bars = load_forward_bars(args.input, observed_at_utc=args.observed_at)
    updated, records = advance_forward_batch(state, history, bars, journal)
    append_checkpoints(STATE, JOURNAL, updated, records)

    rule_summary = {}
    for name in updated["rules"]:
        settlements = [record["settlements"][name] for record in records]
        trades = [item for item in settlements if item["status"] == "traded"]
        rule_summary[name] = {
            "trade_count": len(trades),
            "net_pnl_yen": sum(item["net_pnl_yen"] for item in trades),
            "equity_after_yen": updated["rules"][name]["equity_yen"],
        }
    print(json.dumps({
        "imported_count": len(records),
        "period": [records[0]["input_bar"]["bar_date"], records[-1]["input_bar"]["bar_date"]],
        "rules": rule_summary,
        "journal_tail_hash": updated["journal_tail_hash"],
    }, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
