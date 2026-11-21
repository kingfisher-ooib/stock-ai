"""Audit 1475 daily close/volume sums using JPX ETF monthly mean workbooks."""

import csv
import hashlib
import json
import re
from pathlib import Path
from statistics import median
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

from stock_ai.data.jpx_etf_quotes import compare_monthly_quote, read_1475_quote_month


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.jpx.co.jp/equities/products/etfs/quoting-data/"
CSV = ROOT / "data/processed/1475-daily-split-normalized-2024-2026.csv"
RAW = ROOT / "data/raw/jpx-etf-quotes"
OUT = ROOT / "data/results/jpx-etf-quote-audit-2026-11-15.json"


def monthly_links() -> dict[str, str]:
    with urlopen(BASE, timeout=20) as response:
        html = response.read().decode("utf-8", "ignore")
    links = {}
    for year, month, path in re.findall(
        r'<th[^>]*>\s*(20\d{2})年(\d{1,2})月\s*</th>.*?<a href="([^"]+\.xlsx)"',
        html, re.S,
    ):
        ym = f"{year}{int(month):02d}"
        if "202401" <= ym <= "202609":
            url = urljoin(BASE, path)
            if urlparse(url).hostname != "www.jpx.co.jp":
                raise ValueError("non-JPX ETF quote source")
            links[ym] = url
    if len(links) != 33:
        raise ValueError(f"expected 33 ETF monthly files, found {len(links)}")
    return dict(sorted(links.items()))


def main() -> None:
    links = monthly_links()
    RAW.mkdir(parents=True, exist_ok=True)
    with CSV.open(newline="") as handle:
        bars = list(csv.DictReader(handle))
    months = []
    issues = []
    for ym, url in links.items():
        path = RAW / f"{ym}.xlsx"
        if not path.exists():
            with urlopen(url, timeout=30) as response:
                content = response.read()
            if len(content) < 1000 or content[:2] != b"PK":
                raise ValueError(f"bad ETF workbook: {ym}")
            path.write_bytes(content)
        quote = read_1475_quote_month(path)
        subset = [bar for bar in bars if bar["date"].replace("-", "").startswith(ym)]
        if not subset:
            raise ValueError(f"no daily bars for {ym}")
        comparison = compare_monthly_quote(
            subset, close_mean=quote["close_mean"], volume_mean=quote["volume_mean"])
        record = {"year_month": ym, "url": url,
                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "bytes": path.stat().st_size, **quote, **comparison}
        months.append(record)
        if (abs(comparison["close_sum_difference_original_units"]) > 0.02
                or abs(comparison["volume_difference_original_units"]) > 1):
            issues.append({"year_month": ym, **comparison})
    spreads = [record["quoted_spread_mean_bps"] for record in months]
    report = {
        "role": "retrospective_monthly_mean_audit_not_individual_day_or_execution_validation",
        "symbol": "1475", "period": ["2024-01", "2026-09"],
        "source_index": BASE, "daily_csv_sha256": hashlib.sha256(CSV.read_bytes()).hexdigest(),
        "unit": "Contemporaneous original units; undo the Yahoo 10:1 split adjustment before 2024-08-08.",
        "monthly_files": months, "issues": issues,
        "quoted_spread_mean_bps_median_of_months": median(spreads),
        "quoted_spread_mean_bps_range_of_months": [min(spreads), max(spreads)],
        "limitations": [
            "The mean quoted spread is not a measured spread at entry or exit and cannot establish actual execution cost.",
            "Monthly mean agreement does not validate each daily row; JPX monthly publication is retrospective.",
            "The published ETF averages may share upstream exchange data with JPX monthly quotation tables.",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"files": len(months), "issues": issues,
                      "spread_median_bps": report["quoted_spread_mean_bps_median_of_months"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
