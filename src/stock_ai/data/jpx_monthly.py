"""Compare saved 1475 daily bars with official JPX monthly quotation aggregates."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from openpyxl import load_workbook


SPLIT_TRADING_DATE = date(2024, 8, 8)


@dataclass(frozen=True)
class MonthlySegment:
    year_month: str
    first_date: date
    last_date: date
    open: float
    high: float
    low: float
    close: float
    non_tostnet_volume: int
    days_traded: int
    normalization_ratio: int


def read_1475_segments(path: Path) -> list[MonthlySegment]:
    """Read issue 1475; JPX uses two rows in the August 2024 split month."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        segments = []
        for row in workbook.active.iter_rows(values_only=True):
            if str(row[1]).strip() != "1475":
                continue
            year, month = (int(x) for x in str(row[0]).split("/"))
            first = date(year, month, int(row[11]))
            last = date(year, month, int(row[17]))
            if first > last or first < SPLIT_TRADING_DATE <= last:
                raise ValueError("JPX monthly row crosses the 2024-08-08 split boundary")
            ratio = 10 if last < SPLIT_TRADING_DATE else 1
            total = int(row[19])
            tostnet = int(row[20] or 0)
            if tostnet > total:
                raise ValueError("ToSTNeT volume exceeds total volume")
            prices = tuple(float(row[i]) / ratio for i in (10, 12, 14, 16))
            segments.append(MonthlySegment(
                f"{year:04d}-{month:02d}", first, last, *prices,
                (total - tostnet) * ratio, int(row[23]), ratio,
            ))
        if not segments:
            raise ValueError("1475 missing from JPX monthly workbook")
        return segments
    finally:
        workbook.close()


def audit_monthly(bars: Sequence[dict], segments: Sequence[MonthlySegment],
                  *, price_tolerance: float = 0.02) -> dict:
    """Report mismatches without changing either source or calling them verified."""
    issues = []
    covered = set()
    for segment in segments:
        subset = [bar for bar in bars if segment.first_date <= date.fromisoformat(bar["date"]) <= segment.last_date]
        label = f"{segment.first_date}/{segment.last_date}"
        if not subset:
            issues.append({"segment": label, "field": "missing_bars", "official": segment.days_traded,
                           "observed": 0})
            continue
        dates = {bar["date"] for bar in subset}
        if covered & dates:
            raise ValueError("overlapping JPX monthly segments")
        covered.update(dates)
        observed = {
            "open": float(subset[0]["open"]),
            "high": max(float(bar["high"]) for bar in subset),
            "low": min(float(bar["low"]) for bar in subset),
            "close": float(subset[-1]["close"]),
            "volume": sum(int(bar["volume"]) for bar in subset),
            "days_traded": len(subset),
        }
        expected = {
            "open": segment.open, "high": segment.high,
            "low": segment.low, "close": segment.close,
            "volume": segment.non_tostnet_volume, "days_traded": segment.days_traded,
        }
        for field, official in expected.items():
            tolerance = price_tolerance if field in {"open", "high", "low", "close"} else 0
            if abs(observed[field] - official) > tolerance:
                issues.append({"segment": label, "field": field, "official": official,
                               "observed": observed[field], "difference": observed[field] - official})
    return {"segments": len(segments), "audited_rows": len(covered), "issues": issues}
