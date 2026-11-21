"""Compare 1475 daily CSV to JPX monthly quotation XLSX files (2024-01..2026-10)."""

import csv
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

from stock_ai.data.jpx_monthly import audit_monthly, read_1475_segments


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.jpx.co.jp/markets/statistics-equities/price/"
PAGES = ("00-archives-02.html", "00-archives-01.html", "index.html")
CSV = ROOT / "data/processed/1475-daily-split-normalized-2024-2026.csv"
RAW = ROOT / "data/raw/jpx-monthly"
OUT = ROOT / "data/results/jpx-monthly-audit-2026-11-15.json"


def official_files() -> dict[str, str]:
    urls = {}
    for page in PAGES:
        source = urljoin(BASE, page)
        with urlopen(source, timeout=20) as response:
            html = response.read().decode("utf-8", "ignore")
        for path, ym in re.findall(r'href="([^"]*ivt_(20\d{4})\.xlsx)"', html):
            if "202401" <= ym <= "202610":
                url = urljoin(source, path)
                if urlparse(url).hostname != "www.jpx.co.jp":
                    raise ValueError("non-JPX monthly source")
                urls[ym] = url
    if len(urls) != 34:
        raise ValueError(f"expected 34 monthly JPX files, found {len(urls)}")
    return dict(sorted(urls.items()))


def main() -> None:
    urls = official_files()
    RAW.mkdir(parents=True, exist_ok=True)
    sources = []
    segments = []
    for ym, url in urls.items():
        path = RAW / f"ivt_{ym}.xlsx"
        if not path.exists():
            with urlopen(url, timeout=30) as response:
                payload = response.read()
            if len(payload) < 1000 or payload[:2] != b"PK":
                raise ValueError(f"invalid workbook downloaded for {ym}")
            path.write_bytes(payload)
            time.sleep(0.15)
        payload = path.read_bytes()
        sources.append({"year_month": ym, "url": url,
                        "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)})
        segments.extend(read_1475_segments(path))
    with CSV.open(newline="") as handle:
        bars = list(csv.DictReader(handle))
    result = audit_monthly(bars, segments)
    report = {
        "role": "independent_monthly_aggregate_audit_not_order_validation",
        "symbol": "1475", "period": ["2024-01", "2026-10"],
        "daily_csv_sha256": hashlib.sha256(CSV.read_bytes()).hexdigest(),
        "source_pages": [urljoin(BASE, page) for page in PAGES],
        "source_files": sources,
        "method": "Compare split-normalized monthly OHLC, JPX total volume minus ToSTNeT, and days traded; price tolerance 0.02 JPY.",
        "limitations": [
            "Monthly agreement cannot prove each daily OHLCV row is correct.",
            "JPX monthly files are published after each month, so this is retrospective validation.",
            "JPX monthly volume reflects retrospective corrections and total minus ToSTNeT may include off-floor distributions; a volume mismatch does not by itself identify a faulty daily bar.",
            "No opening/closing bid-ask or actual execution costs are supplied.",
        ],
        **result,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"files": len(sources), "segments": result["segments"],
                      "audited_rows": result["audited_rows"],
                      "issue_count": len(result["issues"]), "issues": result["issues"][:20]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
