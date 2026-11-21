"""Re-run the fixed baseline after two price corrections supported by JPX monthly tables.

Research sensitivity only: the 2026 interval has already been inspected.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from stock_ai.backtest.intraday import run_intraday_sma_baseline, summarize
from stock_ai.data.jpx_monthly import read_1475_segments
from stock_ai.data.snapshot import load_bars_as_of


ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data/processed/1475-point-in-time-assumed.parquet"
OUT = ROOT / "data/results/1475-data-repair-sensitivity-2026-11-15.json"
PERIODS = {
    "development": ("2024-01-04", "2025-12-30"),
    "later_evaluation_already_seen": ("2026-01-05", "2026-11-13"),
}


def main() -> None:
    snapshot = json.loads((ROOT / "data/results/1475-snapshot-manifest-2026-11-15.json").read_text())
    parquet_hash = hashlib.sha256(PARQUET.read_bytes()).hexdigest()
    if parquet_hash != snapshot["parquet_sha256"]:
        raise ValueError("baseline snapshot has changed")

    official = {}
    sources = []
    for ym, date, field, old in (
        ("202403", "2024-03-29", "close", 286.2),
        ("202404", "2024-04-01", "open", 285.5),
    ):
        path = ROOT / f"data/raw/jpx-monthly/ivt_{ym}.xlsx"
        segment = read_1475_segments(path)[0]
        if date not in {segment.first_date.isoformat(), segment.last_date.isoformat()}:
            raise ValueError(f"unexpected JPX monthly boundary: {date}")
        if field == "open" and date != segment.first_date.isoformat():
            raise ValueError("open correction is not a monthly first date")
        if field == "close" and date != segment.last_date.isoformat():
            raise ValueError("close correction is not a monthly last date")
        official[date] = (field, old, getattr(segment, field))
        sources.append({"year_month": ym, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    bars = load_bars_as_of(PARQUET, datetime(2026, 11, 15, tzinfo=timezone.utc),
                           mode="historical_assumption")
    repaired = [dict(bar) for bar in bars]
    corrections = []
    for bar in repaired:
        day = bar["bar_date"]
        if day in official:
            field, old, new = official[day]
            if abs(bar[field] - old) > 0.001 or abs(new - old) < 0.02:
                raise ValueError(f"unexpected correction state: {day}")
            bar[field] = new
            corrections.append({"date": day, "field": field, "before": old, "after": new})
    if len(corrections) != 2:
        raise ValueError("both JPX-supported corrections must be applied")

    results = {}
    for name, (start, end) in PERIODS.items():
        results[name] = {}
        for bps in (0.0, 5.0, 10.0):
            original = summarize(run_intraday_sma_baseline(
                bars, start_date=start, end_date=end, bps_per_side=bps))
            corrected = summarize(run_intraday_sma_baseline(
                repaired, start_date=start, end_date=end, bps_per_side=bps))
            results[name][f"{int(bps)}bp_per_side"] = {
                "original": original, "two_price_corrections": corrected,
                "net_pnl_delta_yen": corrected["net_pnl_yen"] - original["net_pnl_yen"],
                "trade_count_delta": corrected["trade_count"] - original["trade_count"],
            }
    report = {
        "status": "DATA_REPAIR_SENSITIVITY_ONLY_NOT_FRESH_VALIDATION",
        "source_parquet_sha256": parquet_hash,
        "official_monthly_sources": sources,
        "corrections": corrections,
        "unresolved": ["2024-01 monthly volume gap", "2024-03 monthly volume gap",
                       "2026-11 monthly JPX file unavailable at audit time"],
        "scope": "Existing SMA baseline and fixed cost cases only; no rule tuning or order placement.",
        "results": results,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"corrections": corrections,
                      "net_pnl_deltas": {name: {k: v["net_pnl_delta_yen"] for k, v in cases.items()}
                                         for name, cases in results.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
