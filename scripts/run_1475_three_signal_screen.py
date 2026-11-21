"""Run the fixed, low-cost screen of three pre-registered 1475 signals."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from stock_ai.backtest.intraday import run_intraday_sma_baseline, summarize
from stock_ai.backtest.screening import passes_candidate_gate
from stock_ai.backtest.signals import REGISTERED_SIGNALS
from stock_ai.data.snapshot import load_bars_as_of


ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data/processed/1475-point-in-time-assumed.parquet"
OUT = ROOT / "data/results/1475-three-signal-screen-2026-11-15.json"
PERIODS = {
    "development": ("2024-01-04", "2025-12-30"),
    "later_evaluation_already_seen": ("2026-01-05", "2026-11-13"),
}
RULES = {
    "trend": "SMA20 > SMA60",
    "trend_pullback": "SMA20 > SMA60 and prior close < EMA20",
    "volume_momentum": "SMA20 > SMA60 and MACD histogram > 0 and volume ratio >= 1.0",
}


def main() -> None:
    snapshot = json.loads(
        (ROOT / "data/results/1475-snapshot-manifest-2026-11-15.json").read_text()
    )
    digest = hashlib.sha256(PARQUET.read_bytes()).hexdigest()
    if digest != snapshot["parquet_sha256"]:
        raise ValueError("Parquet hash differs from saved snapshot manifest")
    bars = load_bars_as_of(
        PARQUET, datetime(2026, 11, 15, tzinfo=timezone.utc),
        mode="historical_assumption",
    )
    if (
        len(bars) != 698
        or bars[0]["bar_date"] != "2024-01-04"
        or bars[-1]["bar_date"] != "2026-11-13"
    ):
        raise ValueError("expected fixed 1475 snapshot was not loaded")

    report = {
        "status": "SCREEN_COMPLETE_NO_VALIDATED_RULE",
        "symbol": "1475",
        "source_parquet_sha256": digest,
        "plan": "docs/superpowers/specs/2026-11-15-three-signal-screen-design.md",
        "rules": RULES,
        "primary_cost_condition": "5bp adverse price impact per side; fixed commission 0 JPY assumed",
        "fee_warning": "Actual Rakuten account course and execution cost remain unconfirmed.",
        "screening_gate": {
            "interval": "development only",
            "cost": "5bp_per_side",
            "minimum_trade_count": 30,
            "net_pnl_yen": "> 0",
            "profit_factor": "> 1",
            "expectancy_bootstrap_95pct_lower_yen": "> 0",
        },
        "later_interval_warning": "2026 results were already seen and are not untouched validation.",
        "results": {},
        "candidate_decisions": {},
    }
    for signal_name in REGISTERED_SIGNALS:
        report["results"][signal_name] = {}
        for period_name, (start, end) in PERIODS.items():
            report["results"][signal_name][period_name] = {}
            for bps in (0.0, 5.0, 10.0):
                result = run_intraday_sma_baseline(
                    bars, start_date=start, end_date=end,
                    bps_per_side=bps, signal_name=signal_name,
                )
                report["results"][signal_name][period_name][f"{int(bps)}bp_per_side"] = summarize(result)
        passed = passes_candidate_gate(
            report["results"][signal_name]["development"]["5bp_per_side"]
        )
        report["candidate_decisions"][signal_name] = {
            "development_gate_passed": passed,
            "validated_for_trading": False,
            "reason": (
                "Requires a new untouched interval before adoption."
                if passed else "Failed the fixed development gate."
            ),
        }

    if any(item["development_gate_passed"] for item in report["candidate_decisions"].values()):
        report["status"] = "SCREEN_COMPLETE_CANDIDATE_REQUIRES_NEW_UNTOUCHED_PERIOD"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    compact = {
        name: {
            "development_5bp": report["results"][name]["development"]["5bp_per_side"],
            "later_seen_5bp": report["results"][name]["later_evaluation_already_seen"]["5bp_per_side"],
            "decision": report["candidate_decisions"][name],
        }
        for name in REGISTERED_SIGNALS
    }
    print(json.dumps(compact, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
