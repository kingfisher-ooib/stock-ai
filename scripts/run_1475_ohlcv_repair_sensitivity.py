"""Fixed-rule sensitivity to three identified 1475 daily OHLCV discrepancies."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from stock_ai.backtest.intraday import run_intraday_sma_baseline, summarize
from stock_ai.data.jpx_etf_quotes import compare_monthly_quote, read_1475_quote_month
from stock_ai.data.jpx_monthly import read_1475_segments
from stock_ai.data.snapshot import load_bars_as_of


ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data/processed/1475-point-in-time-assumed.parquet"
OUT = ROOT / "data/results/1475-ohlcv-repair-sensitivity-2026-11-15.json"
PERIODS = {
    "development": ("2024-01-04", "2025-12-30"),
    "later_evaluation_already_seen": ("2026-01-05", "2026-11-13"),
}


def main() -> None:
    snapshot = json.loads((ROOT / "data/results/1475-snapshot-manifest-2026-11-15.json").read_text())
    source_hash = hashlib.sha256(PARQUET.read_bytes()).hexdigest()
    if source_hash != snapshot["parquet_sha256"]:
        raise ValueError("baseline Parquet hash changed")
    jan_quote = ROOT / "data/raw/jpx-etf-quotes/202401.xlsx"
    mar_quote = ROOT / "data/raw/jpx-etf-quotes/202403.xlsx"
    mar_monthly = read_1475_segments(ROOT / "data/raw/jpx-monthly/ivt_202403.xlsx")[0]
    apr_monthly = read_1475_segments(ROOT / "data/raw/jpx-monthly/ivt_202404.xlsx")[0]
    if abs(mar_monthly.close - 286.7) > 0.001 or abs(apr_monthly.open - 287.4) > 0.001:
        raise ValueError("JPX monthly boundary prices changed")

    # Jan 15: direct JPX daily report. Mar 29: JPX monthly aggregate plus
    # a secondary daily listing. Apr 1: direct JPX daily report.
    changes = {
        "2024-01-15": {"high": (259.4, 261.5), "close": (259.1, 261.3),
                       "volume": (249780, 4109300)},
        "2024-03-29": {"high": (286.8, 287.1), "close": (286.2, mar_monthly.close),
                       "volume": (3891990, 4980290)},
        "2024-04-01": {"open": (285.5, apr_monthly.open)},
    }
    bars = load_bars_as_of(PARQUET, datetime(2026, 11, 15, tzinfo=timezone.utc),
                           mode="historical_assumption")
    corrected = [dict(bar) for bar in bars]
    corrections = []
    for bar in corrected:
        day = bar["bar_date"]
        for field, (before, after) in changes.get(day, {}).items():
            if abs(bar[field] - before) > 0.001:
                raise ValueError(f"unexpected original {day} {field}")
            bar[field] = after
            corrections.append({"date": day, "field": field, "before": before, "after": after})
    if len(corrections) != 7:
        raise ValueError("not all seven fields were corrected")

    monthly_checks = {}
    for ym, path in (("202401", jan_quote), ("202403", mar_quote)):
        quote = read_1475_quote_month(path)
        subset = [{"date": bar["bar_date"], "close": bar["close"], "volume": bar["volume"]}
                  for bar in corrected if bar["bar_date"].replace("-", "").startswith(ym)]
        check = compare_monthly_quote(subset, close_mean=quote["close_mean"],
                                      volume_mean=quote["volume_mean"])
        if (abs(check["close_sum_difference_original_units"]) > 0.02
                or abs(check["volume_difference_original_units"]) > 1):
            raise ValueError(f"candidate corrections do not reconcile JPX {ym}")
        monthly_checks[ym] = check

    results = {}
    for name, (start, end) in PERIODS.items():
        results[name] = {}
        for bps in (0.0, 5.0, 10.0):
            before = summarize(run_intraday_sma_baseline(
                bars, start_date=start, end_date=end, bps_per_side=bps))
            after = summarize(run_intraday_sma_baseline(
                corrected, start_date=start, end_date=end, bps_per_side=bps))
            results[name][f"{int(bps)}bp_per_side"] = {
                "original": before, "candidate_repair": after,
                "net_pnl_delta_yen": after["net_pnl_yen"] - before["net_pnl_yen"],
                "trade_count_delta": after["trade_count"] - before["trade_count"],
            }
    report = {
        "status": "DATA_REPAIR_SENSITIVITY_ONLY_NOT_FRESH_VALIDATION",
        "source_parquet_sha256": source_hash,
        "sources": {
            "2024-01-15": "https://www.jpx.co.jp/english/markets/statistics-equities/daily/o4sio70000005r5s-att/stq_20240115.pdf",
            "2024-03-29": "JPX 2024-03 monthly close and ETF mean/volume; 96ut daily listing for high and volume: https://96ut.com/stock/jikei.php?code=1475&year=2024",
            "2024-04-01": "https://www.jpx.co.jp/markets/statistics-equities/daily/mklp770000003i2z-att/stq_20240401.pdf",
            "monthly_quote_sha256": {ym: hashlib.sha256(path.read_bytes()).hexdigest()
                                     for ym, path in (("202401", jan_quote), ("202403", mar_quote))},
        },
        "corrections": corrections, "corrected_monthly_checks": monthly_checks,
        "scope": "Same fixed SMA rule, periods and 0/5/10bp cost assumptions; original files unchanged.",
        "results": results,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"corrections": len(corrections), "monthly_checks": monthly_checks,
                      "pnl_deltas": {name: {k: v["net_pnl_delta_yen"] for k, v in cases.items()}
                                     for name, cases in results.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
