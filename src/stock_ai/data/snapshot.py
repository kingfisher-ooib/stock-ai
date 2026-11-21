"""Immutable, provenance-labelled daily OHLCV snapshots."""

import csv
import hashlib
import json
import math
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import duckdb


JST = timezone(timedelta(hours=9))


def build_snapshot(csv_path: Path, manifest_path: Path, metadata_path: Path,
                   parquet_path: Path, *, symbol: str) -> dict:
    """Verify the saved CSV hash before converting it to a local Parquet snapshot."""
    csv_path, parquet_path = Path(csv_path), Path(parquet_path)
    raw = csv_path.read_bytes()
    manifest = json.loads(Path(manifest_path).read_text())
    digest = hashlib.sha256(raw).hexdigest()
    if digest != manifest["output_sha256"]:
        raise ValueError("source CSV hash does not match cleaning manifest")
    observed = datetime.fromisoformat(json.loads(Path(metadata_path).read_text())["retrieved_at_utc"])
    if observed.tzinfo is None:
        raise ValueError("retrieved_at_utc must include a timezone")
    observed = observed.astimezone(timezone.utc)
    official_dates = {entry["date"] for entry in manifest["official_replacements"]}
    rows = []
    seen_official = set()
    previous = None
    for row in csv.DictReader(raw.decode("utf-8-sig").splitlines()):
        day = date.fromisoformat(row["date"])
        if previous is not None and day <= previous:
            raise ValueError("bar dates must be unique and increasing")
        previous = day
        prices = tuple(float(row[key]) for key in ("open", "high", "low", "close"))
        volume = int(row["volume"])
        open_, high, low, close = prices
        if (not all(math.isfinite(x) for x in prices)
                or not 0 < low <= min(open_, close) <= max(open_, close) <= high
                or volume <= 0):
            raise ValueError(f"invalid OHLCV on {day}")
        assumed = datetime.combine(day + timedelta(days=1), time.min, JST).astimezone(timezone.utc)
        provenance = "jpx_replacement" if day.isoformat() in official_dates else "yahoo_unverified"
        if provenance == "jpx_replacement":
            seen_official.add(day.isoformat())
        rows.append((symbol, day, *prices, volume, observed, assumed, provenance))
    if not rows:
        raise ValueError("empty source CSV")
    if seen_official != official_dates:
        raise ValueError("official replacement date missing from source CSV")

    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = parquet_path.with_suffix(".tmp.parquet")
    con = duckdb.connect()
    try:
        con.execute("""CREATE TABLE bars (
            symbol VARCHAR, bar_date DATE, open DOUBLE, high DOUBLE, low DOUBLE,
            close DOUBLE, volume BIGINT, source_observed_at_utc TIMESTAMPTZ,
            assumed_available_at_utc TIMESTAMPTZ, provenance VARCHAR
        )""")
        con.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        con.execute("COPY bars TO ? (FORMAT PARQUET)", [str(temp_path)])
        os.replace(temp_path, parquet_path)
    finally:
        con.close()
        temp_path.unlink(missing_ok=True)
    return {"symbol": symbol, "rows": len(rows), "period": [rows[0][1].isoformat(), rows[-1][1].isoformat()],
            "source_sha256": digest, "parquet_sha256": hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
            "source_observed_at_utc": observed.isoformat(), "jpx_replacement_rows": len(seen_official)}


def load_bars_as_of(parquet_path: Path, decision_time_utc: datetime,
                    *, mode: str = "observed") -> list[dict]:
    """Default to actual source observation; historical availability requires explicit assumption."""
    if decision_time_utc.tzinfo is None:
        raise ValueError("decision_time_utc must have timezone")
    if mode not in {"observed", "historical_assumption"}:
        raise ValueError("unknown availability mode")
    column = "source_observed_at_utc" if mode == "observed" else "assumed_available_at_utc"
    con = duckdb.connect()
    try:
        result = con.execute(
            f"""SELECT symbol, bar_date::VARCHAR AS bar_date, open, high, low, close, volume,
                strftime(source_observed_at_utc, '%Y-%m-%dT%H:%M:%S.%fZ') AS source_observed_at_utc,
                strftime(assumed_available_at_utc, '%Y-%m-%dT%H:%M:%S.%fZ') AS assumed_available_at_utc,
                provenance
                FROM read_parquet(?) WHERE {column} <= ? ORDER BY bar_date""",
            [str(parquet_path), decision_time_utc.astimezone(timezone.utc)],
        )
        names = [item[0] for item in result.description]
        records = [dict(zip(names, row)) for row in result.fetchall()]
    finally:
        con.close()
    return records
