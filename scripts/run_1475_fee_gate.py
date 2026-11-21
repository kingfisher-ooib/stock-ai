"""Research-only fee-gate sensitivity for Rakuten's small-order Cho-wari rate."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from stock_ai.backtest.intraday import run_intraday_sma_baseline, summarize
from stock_ai.data.snapshot import load_bars_as_of


ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data/processed/1475-point-in-time-assumed.parquet"
OUT = ROOT / "data/results/1475-cho-wari-fee-gate-2026-11-15.json"
PERIODS = {
    "development": ("2024-01-04", "2025-12-30"),
    "later_evaluation_already_seen": ("2026-01-05", "2026-11-13"),
}


def main() -> None:
    manifest = json.loads((ROOT / "data/results/1475-snapshot-manifest-2026-11-15.json").read_text())
    digest = hashlib.sha256(PARQUET.read_bytes()).hexdigest()
    if digest != manifest["parquet_sha256"]:
        raise ValueError("baseline snapshot changed")
    bars = load_bars_as_of(PARQUET, datetime(2026, 11, 15, tzinfo=timezone.utc),
                           mode="historical_assumption")
    results = {}
    for name, (start, end) in PERIODS.items():
        results[name] = {}
        for bps in (0.0, 5.0, 10.0):
            run = run_intraday_sma_baseline(
                bars, start_date=start, end_date=end, bps_per_side=bps,
                fee_yen_per_side=55.0)
            results[name][f"{int(bps)}bp_per_side"] = summarize(run)
    report = {
        "status": "CONDITIONAL_FEE_SENSITIVITY_ONLY_NO_TRADING_ADVANTAGE_CLAIM",
        "symbol": "1475", "source_parquet_sha256": digest,
        "fee_source": "https://www.rakuten-sec.co.jp/web/domestic/stock/commission.html",
        "fee_condition": "Cho-wari course, one execution <= 50,000 JPY; user course unconfirmed.",
        "fee_yen_per_side": 55.0, "round_trip_fee_yen": 110.0,
        "initial_equity_yen": 100000.0, "max_trade_loss_ratio": 0.001,
        "initial_trade_loss_budget_yen": 100.0,
        "risk_rule": "Estimated round-trip fee is deducted from trade-loss budget before sizing; no broker connection.",
        "zero_trade_metrics": "Net PnL 0 reflects no trade. Expectancy, PF and Sharpe are undefined.",
        "results": results,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({name: {case: {"trades": value["trade_count"],
                                    "net_pnl_yen": value["net_pnl_yen"]}
                             for case, value in cases.items()}
                      for name, cases in results.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
