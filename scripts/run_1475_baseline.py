"""Run the single pre-registered exploratory 1475 baseline once."""

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from stock_ai.backtest.intraday import run_intraday_sma_baseline, summarize
from stock_ai.data.snapshot import load_bars_as_of


ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data/processed/1475-point-in-time-assumed.parquet"
OUT = ROOT / "data/results/1475-baseline-exploratory-2026-11-15.json"
TRADES = ROOT / "data/trades/1475-baseline-exploratory-2026-11-15.json"
PERIODS = {
    "development": ("2024-01-04", "2025-12-30"),
    "later_evaluation": ("2026-01-05", "2026-11-13"),
}


def main() -> None:
    snapshot = json.loads((ROOT / "data/results/1475-snapshot-manifest-2026-11-15.json").read_text())
    digest = hashlib.sha256(PARQUET.read_bytes()).hexdigest()
    if digest != snapshot["parquet_sha256"]:
        raise ValueError("Parquet hash differs from saved snapshot manifest")
    bars = load_bars_as_of(PARQUET, datetime(2026, 11, 15, tzinfo=timezone.utc),
                           mode="historical_assumption")
    if len(bars) != 698 or bars[0]["bar_date"] != "2024-01-04" or bars[-1]["bar_date"] != "2026-11-13":
        raise ValueError("expected fixed 1475 snapshot was not loaded")
    report = {
        "status": "EXPLORATORY_ONLY_NOT_VALIDATED_FOR_TRADING",
        "plan": "docs/research-plan-2026-11-15.md",
        "symbol": "1475", "source_parquet_sha256": digest,
        "source_observed_at_utc": snapshot["source_observed_at_utc"],
        "source_quality": {"jpx_replacement_rows": 3, "unverified_yahoo_rows": 695},
        "availability_mode": "historical_assumption_next_calendar_day_00JST",
        "fill_model": "next open buy; same-day stop or close sell; adverse bps each side; fee 0 yen assumed",
        "cash_reference_net_pnl_yen": 0.0,
        "results": {},
    }
    trade_details = {}
    for name, (start, end) in PERIODS.items():
        report["results"][name] = {}
        trade_details[name] = {}
        for bps in (0.0, 5.0, 10.0):
            run = run_intraday_sma_baseline(bars, start_date=start, end_date=end,
                                            bps_per_side=bps)
            label = f"{int(bps)}bp_per_side"
            report["results"][name][label] = summarize(run)
            trade_details[name][label] = [asdict(trade) for trade in run.trades]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    TRADES.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    TRADES.write_text(json.dumps(trade_details, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({name: values["5bp_per_side"] for name, values in report["results"].items()},
                     ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
