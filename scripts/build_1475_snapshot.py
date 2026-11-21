"""Build the local, provenance-labelled 1475 Parquet snapshot."""

import json
from pathlib import Path

from stock_ai.data.snapshot import build_snapshot


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    summary = build_snapshot(
        ROOT / "data/processed/1475-daily-split-normalized-2024-2026.csv",
        ROOT / "data/results/cleaning-manifest-2026-11-15.json",
        ROOT / "data/raw/1475-yahoo-chart-2024-2026.meta.json",
        ROOT / "data/processed/1475-point-in-time-assumed.parquet",
        symbol="1475",
    )
    path = ROOT / "data/results/1475-snapshot-manifest-2026-11-15.json"
    path.write_text(json.dumps({
        **summary,
        "availability_note": "Next-calendar-day 00:00 JST is an assumption, not observed provider delivery time.",
        "verified_rows": 3,
        "unverified_rows": summary["rows"] - 3,
        "use": "research_only_no_ordering",
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
