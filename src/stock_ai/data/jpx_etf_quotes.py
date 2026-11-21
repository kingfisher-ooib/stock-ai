"""Compare JPX ETF monthly averages with a split-normalized daily snapshot."""

from datetime import date
from pathlib import Path
from typing import Sequence

from openpyxl import load_workbook


SPLIT_TRADING_DATE = date(2024, 8, 8)


def compare_monthly_quote(bars: Sequence[dict], *, close_mean: float,
                          volume_mean: float) -> dict:
    """Return sum differences in contemporaneous (pre/post split) units."""
    if not bars:
        raise ValueError("monthly bars are empty")
    observed_close = 0.0
    observed_volume = 0.0
    for bar in bars:
        ratio = 10 if date.fromisoformat(bar["date"]) < SPLIT_TRADING_DATE else 1
        observed_close += float(bar["close"]) * ratio
        observed_volume += int(bar["volume"]) / ratio
    days = len(bars)
    return {
        "days": days,
        "close_sum_difference_original_units": round(observed_close - close_mean * days, 6),
        "volume_difference_original_units": round(observed_volume - volume_mean * days, 6),
    }


def read_1475_quote_month(path: Path) -> dict:
    """Read published means and spread; this is not an open/close execution quote."""
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        for row in book.active.iter_rows(values_only=True):
            if str(row[1]).strip() == "1475":
                return {
                    "close_mean": float(row[7]),
                    "volume_mean": float(row[5]),
                    "quoted_spread_mean_bps": float(row[11]),
                    "quoted_spread_mean_yen_original_unit": float(row[14]),
                }
        raise ValueError("1475 absent from ETF quote workbook")
    finally:
        book.close()
