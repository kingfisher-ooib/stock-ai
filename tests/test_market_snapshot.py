import csv
import hashlib
import json
from datetime import datetime, timezone

import pytest

from stock_ai.data.snapshot import build_snapshot, load_bars_as_of


def fixture_paths(tmp_path):
    csv_path = tmp_path / "bars.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        writer.writerow(["2026-01-05", 100, 102, 99, 101, 1000])
        writer.writerow(["2026-01-06", 101, 103, 100, 102, 1200])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "output_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "official_replacements": [{"date": "2026-01-05", "source": "https://jpx.example/report"}],
    }))
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"retrieved_at_utc": "2026-11-15T00:18:24+00:00"}))
    return csv_path, manifest, metadata, tmp_path / "bars.parquet"


def test_snapshot_keeps_observed_and_assumed_availability_separate(tmp_path):
    csv_path, manifest, metadata, parquet = fixture_paths(tmp_path)
    summary = build_snapshot(csv_path, manifest, metadata, parquet, symbol="1475")
    assert summary["rows"] == 2
    cutoff = datetime(2026, 1, 6, 0, 0, tzinfo=timezone.utc)
    assert load_bars_as_of(parquet, cutoff) == []
    assumed = load_bars_as_of(parquet, cutoff, mode="historical_assumption")
    assert len(assumed) == 1
    assert assumed[0]["bar_date"] == "2026-01-05"
    assert assumed[0]["provenance"] == "jpx_replacement"
    assert assumed[0]["source_observed_at_utc"].startswith("2026-11-15")
    assert len(load_bars_as_of(parquet, datetime(2026, 11, 16, tzinfo=timezone.utc))) == 2


def test_snapshot_rejects_changed_source(tmp_path):
    csv_path, manifest, metadata, parquet = fixture_paths(tmp_path)
    csv_path.write_text(csv_path.read_text().replace("101,1000", "999,1000"))
    with pytest.raises(ValueError, match="hash"):
        build_snapshot(csv_path, manifest, metadata, parquet, symbol="1475")
    assert not parquet.exists()


def test_snapshot_rejects_missing_official_replacement_date(tmp_path):
    csv_path, manifest, metadata, parquet = fixture_paths(tmp_path)
    record = json.loads(manifest.read_text())
    record["official_replacements"][0]["date"] = "2026-01-04"
    manifest.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="replacement"):
        build_snapshot(csv_path, manifest, metadata, parquet, symbol="1475")
