"""Normalize local CSV or JSON bars for paper-forward ingestion."""

import csv
import hashlib
import json
from datetime import date
from pathlib import Path


REQUIRED_FIELDS = {"bar_date", "open", "high", "low", "close", "volume"}


def load_forward_bars(
    path: Path, *, observed_at_utc: str | None = None,
) -> list[dict]:
    path = Path(path)
    raw = path.read_bytes()
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    elif path.suffix.lower() == ".json":
        payload = json.loads(raw)
        rows = payload if isinstance(payload, list) else [payload]
    else:
        raise ValueError("input must be CSV or JSON")
    if not rows:
        raise ValueError("input contains no bars")
    fallback_provenance = f"{path.name} sha256:{hashlib.sha256(raw).hexdigest()}"
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or not REQUIRED_FIELDS.issubset(row):
            raise ValueError("missing required fields")
        observed = row.get("source_observed_at_utc") or observed_at_utc
        if not observed:
            raise ValueError("observation time is required")
        volume = float(row["volume"])
        if not volume.is_integer():
            raise ValueError("volume must be an integer")
        normalized.append({
            "bar_date": date.fromisoformat(str(row["bar_date"])).isoformat(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(volume),
            "source_observed_at_utc": str(observed),
            "provenance": str(row.get("provenance") or fallback_provenance),
        })
    normalized.sort(key=lambda bar: bar["bar_date"])
    dates = [bar["bar_date"] for bar in normalized]
    if len(dates) != len(set(dates)):
        raise ValueError("duplicate bar date")
    return normalized
