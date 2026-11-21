"""Prepare an auditable, split-normalized daily 1475 series from a saved snapshot."""

import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/1475-yahoo-chart-2024-2026.json"
OUT = ROOT / "data/processed/1475-daily-split-normalized-2024-2026.csv"
MANIFEST = ROOT / "data/results/cleaning-manifest-2026-11-15.json"
JST = dt.timezone(dt.timedelta(hours=9))

# Original Tokyo Stock Exchange daily reports. Prices are per post-split unit.
OFFICIAL = {
    "2024-08-08": (250.8, 257.4, 249.0, 252.3, 1030890),
    "2024-08-09": (257.0, 257.4, 250.1, 255.1, 3383820),
    "2025-10-24": (337.8, 338.7, 336.3, 337.7, 646030),
}
SOURCES = {
    "2024-08-08": "https://www.jpx.co.jp/markets/statistics-equities/daily/mklp77000000dt4a-att/stq_20240808.pdf",
    "2024-08-09": "https://www.jpx.co.jp/markets/statistics-equities/daily/mklp77000000dwls-att/stq_20240809.pdf",
    "2025-10-24": "https://www.jpx.co.jp/markets/statistics-equities/daily/um3qrc0000028a0i-att/stq_20251024.pdf",
}


def main():
    raw = RAW.read_bytes()
    data = json.loads(raw)["chart"]["result"][0]
    quote = data["indicators"]["quote"][0]
    rows = []
    for i, timestamp in enumerate(data["timestamp"]):
        date = dt.datetime.fromtimestamp(timestamp, JST).date().isoformat()
        values = tuple(quote[key][i] for key in ("open", "high", "low", "close", "volume"))
        if date in OFFICIAL:
            values = OFFICIAL[date]
        if any(value is None or not math.isfinite(value) for value in values):
            raise ValueError("Unresolved missing or invalid value: " + date)
        open_, high, low, close, volume = values
        if not (0 < low <= min(open_, close) <= max(open_, close) <= high):
            raise ValueError("Invalid OHLC: " + date)
        if volume <= 0:
            raise ValueError("Invalid volume: " + date)
        rows.append((date, *(f"{value:.2f}" for value in (open_, high, low, close)), int(volume)))

    dates = [row[0] for row in rows]
    if dates != sorted(set(dates)):
        raise ValueError("Dates are duplicated or unordered")
    if len(rows) != 698 or dates[0] != "2024-01-04" or dates[-1] != "2026-11-13":
        raise ValueError("Snapshot period changed")
    by_date = {row[0]: row for row in rows}
    if by_date["2024-08-07"][4] != "254.00" or by_date["2026-11-11"][4] != "407.80":
        raise ValueError("Cross-check anchor changed")
    if any(abs(float(b[4]) / float(a[4]) - 1) > 0.3 for a, b in zip(rows, rows[1:])):
        raise ValueError("Unresolved >30% close-to-close jump")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("date", "open", "high", "low", "close", "volume"))
        writer.writerows(rows)
    manifest = {
        "instrument": "1475",
        "role": "data_preparation_only_no_trading_pnl",
        "raw_path": str(RAW),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "output_path": str(OUT),
        "output_sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "rows": len(rows),
        "period": [dates[0], dates[-1]],
        "official_replacements": [
            {"date": date, "ohlcv": OFFICIAL[date], "source": SOURCES[date]}
            for date in OFFICIAL
        ],
        "price_basis": "Post-2024-08-08 split-adjusted units; Yahoo pre-split quotes were already divided by 10.",
        "limitations": [
            "Only three identified errors were replaced; all other bars remain unverified Yahoo data.",
            "No historical bid/ask or executable fills are supplied.",
            "Dividend adjustments are not applied to OHLC; distributions require separate handling for overnight positions.",
        ],
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"rows": len(rows), "output_sha256": manifest["output_sha256"]}))


if __name__ == "__main__":
    main()
