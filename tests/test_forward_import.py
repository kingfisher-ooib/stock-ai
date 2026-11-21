import json

import pytest

from stock_ai.data.forward_import import load_forward_bars


def test_csv_rows_are_sorted_and_receive_common_observation_and_hashed_provenance(tmp_path):
    path = tmp_path / "1475.csv"
    path.write_text(
        "bar_date,open,high,low,close,volume\n"
        "2026-11-17,402,405,401,404,120000\n"
        "2026-11-16,400,403,399,402,100000\n"
    )
    bars = load_forward_bars(path, observed_at_utc="2026-11-17T08:00:00+00:00")
    assert [bar["bar_date"] for bar in bars] == ["2026-11-16", "2026-11-17"]
    assert bars[0]["open"] == 400.0
    assert bars[0]["volume"] == 100000
    assert bars[0]["source_observed_at_utc"] == "2026-11-17T08:00:00+00:00"
    assert bars[0]["provenance"].startswith("1475.csv sha256:")
    assert bars[0]["provenance"] == bars[1]["provenance"]


@pytest.mark.parametrize("as_array", [False, True])
def test_json_accepts_one_object_or_array_and_preserves_row_metadata(tmp_path, as_array):
    row = {
        "bar_date": "2026-11-16", "open": 400, "high": 403,
        "low": 399, "close": 402, "volume": 100000,
        "source_observed_at_utc": "2026-11-16T08:00:00+00:00",
        "provenance": "saved-jpx-file",
    }
    path = tmp_path / "1475.json"
    path.write_text(json.dumps([row] if as_array else row))
    assert load_forward_bars(path) == [{
        **row, "open": 400.0, "high": 403.0, "low": 399.0, "close": 402.0,
    }]


def test_duplicate_dates_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    row = {
        "bar_date": "2026-11-16", "open": 400, "high": 403,
        "low": 399, "close": 402, "volume": 100000,
    }
    path.write_text(json.dumps([row, row]))
    with pytest.raises(ValueError, match="duplicate bar date"):
        load_forward_bars(path, observed_at_utc="2026-11-16T08:00:00+00:00")


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"bar_date": "2026-11-16"}, "missing required fields"),
        ({
            "bar_date": "2026-11-16", "open": 400, "high": 403,
            "low": 399, "close": 402, "volume": 100000,
        }, "observation time is required"),
    ],
)
def test_missing_fields_or_observation_are_rejected(tmp_path, row, message):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError, match=message):
        load_forward_bars(path)
