from copy import deepcopy
from datetime import date, timedelta

import pytest

from stock_ai.backtest.paper_forward import (
    advance_forward_batch,
    advance_forward_state,
    append_checkpoint,
    append_checkpoints,
    hash_record,
    initialize_forward_state,
    load_checkpoint,
    verify_journal,
    write_initial_checkpoint,
)


def rising_history(count=61):
    start = date(2026, 1, 1)
    bars = []
    for i in range(count):
        close = 100.0 + i * 0.1
        bars.append({
            "bar_date": (start + timedelta(days=i)).isoformat(),
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000,
        })
    return bars


def test_initialization_freezes_registered_next_bar_decisions():
    state, record = initialize_forward_state(
        rising_history(),
        base_snapshot_sha256="a" * 64,
        source_observed_at_utc="2026-03-03T08:00:00+00:00",
    )
    assert state["last_bar_date"] == "2026-03-02"
    assert state["rules"]["trend"]["pending"]["active"] is True
    assert state["rules"]["trend_pullback"]["pending"]["active"] is False
    assert state["rules"]["volume_momentum"]["pending"]["active"] is True
    assert state["rules"]["trend"]["equity_yen"] == 100_000.0
    assert state["journal_tail_hash"] == record["record_hash"]
    assert verify_journal([record]) == record["record_hash"]


def test_record_hash_is_canonical_and_ignores_existing_hash_field():
    left = {"event": "initialize", "previous_hash": None, "value": 1}
    right = {"value": 1, "record_hash": "stale", "previous_hash": None, "event": "initialize"}
    assert hash_record(left) == hash_record(right)


def test_journal_verification_rejects_tampering():
    _, record = initialize_forward_state(
        rising_history(),
        base_snapshot_sha256="a" * 64,
        source_observed_at_utc="2026-03-03T08:00:00+00:00",
    )
    changed = deepcopy(record)
    changed["last_bar_date"] = "2026-03-01"
    with pytest.raises(ValueError, match="journal hash mismatch"):
        verify_journal([changed])


def next_bar(**overrides):
    bar = {
        "bar_date": "2026-03-03",
        "open": 106.0,
        "high": 108.0,
        "low": 105.0,
        "close": 107.0,
        "volume": 1000,
        "source_observed_at_utc": "2026-03-03T09:00:00+00:00",
        "provenance": "manual_test",
    }
    bar.update(overrides)
    return bar


def initialized():
    history = rising_history()
    state, record = initialize_forward_state(
        history,
        base_snapshot_sha256="a" * 64,
        source_observed_at_utc="2026-03-02T08:00:00+00:00",
    )
    return history, state, [record]


def test_advancement_settles_trade_and_records_inactive_rule_without_win():
    history, state, journal = initialized()
    updated, record = advance_forward_state(state, history, next_bar(), journal)
    trend = record["settlements"]["trend"]
    assert trend["status"] == "traded"
    assert trend["quantity"] == 40
    assert trend["net_pnl_yen"] > 0
    assert updated["rules"]["trend"]["equity_yen"] == 100_000.0 + trend["net_pnl_yen"]
    assert record["settlements"]["trend_pullback"] == {
        "status": "no_signal", "net_pnl_yen": 0.0,
    }
    assert updated["last_bar_date"] == "2026-03-03"
    assert verify_journal(journal + [record]) == updated["journal_tail_hash"]


def test_gap_below_frozen_stop_skips_entry():
    history, state, journal = initialized()
    stop = state["rules"]["trend"]["pending"]["stop_reference"]
    bar = next_bar(open=stop - 0.1, high=stop + 0.5, low=stop - 1.0, close=stop)
    updated, record = advance_forward_state(state, history, bar, journal)
    assert record["settlements"]["trend"] == {
        "status": "open_below_stop", "net_pnl_yen": 0.0,
    }
    assert updated["rules"]["trend"]["equity_yen"] == 100_000.0


@pytest.mark.parametrize(
    ("bar", "message"),
    [
        (next_bar(bar_date="2026-03-02"), "strictly later"),
        (next_bar(high=105.0), "invalid OHLCV"),
        (next_bar(source_observed_at_utc="2026-03-03T09:00:00"), "timezone"),
    ],
)
def test_invalid_bar_does_not_advance_state(bar, message):
    history, state, journal = initialized()
    original = deepcopy(state)
    with pytest.raises(ValueError, match=message):
        advance_forward_state(state, history, bar, journal)
    assert state == original


def test_bar_observed_before_fixed_daily_cutoff_is_rejected():
    history = rising_history()
    state, record = initialize_forward_state(
        history,
        base_snapshot_sha256="a" * 64,
        source_observed_at_utc="2026-03-02T08:00:00+00:00",
    )
    early = next_bar(source_observed_at_utc="2026-03-03T06:59:59+00:00")
    with pytest.raises(ValueError, match="daily bar cutoff"):
        advance_forward_state(state, history, early, [record])


def test_advancement_rejects_state_and_journal_tail_mismatch():
    history, state, journal = initialized()
    state["journal_tail_hash"] = "0" * 64
    with pytest.raises(ValueError, match="state journal tail mismatch"):
        advance_forward_state(state, history, next_bar(), journal)


def test_checkpoint_files_round_trip_and_refuse_initial_overwrite(tmp_path):
    history, state, journal = initialized()
    state_path = tmp_path / "state.json"
    journal_path = tmp_path / "journal.jsonl"
    write_initial_checkpoint(state_path, journal_path, state, journal[0])
    loaded_state, loaded_journal = load_checkpoint(state_path, journal_path)
    assert loaded_state == state
    assert loaded_journal == journal
    with pytest.raises(FileExistsError, match="checkpoint already exists"):
        write_initial_checkpoint(state_path, journal_path, state, journal[0])

    updated, record = advance_forward_state(state, history, next_bar(), journal)
    append_checkpoint(state_path, journal_path, updated, record)
    loaded_state, loaded_journal = load_checkpoint(state_path, journal_path)
    assert loaded_state == updated
    assert loaded_journal == journal + [record]


def test_batch_advances_two_dates_with_one_common_observation_time():
    history, state, journal = initialized()
    bars = [
        next_bar(source_observed_at_utc="2026-03-04T08:00:00+00:00"),
        next_bar(
            bar_date="2026-03-04", open=107.0, high=109.0, low=106.0,
            close=108.0, source_observed_at_utc="2026-03-04T08:00:00+00:00",
        ),
    ]
    original = deepcopy(state)
    updated, records = advance_forward_batch(state, history, bars, journal)
    assert state == original
    assert updated["last_bar_date"] == "2026-03-04"
    assert len(records) == 2
    assert records[0]["previous_hash"] == journal[-1]["record_hash"]
    assert records[1]["previous_hash"] == records[0]["record_hash"]
    assert verify_journal(journal + records) == updated["journal_tail_hash"]


def test_late_bar_is_recorded_as_retrospective_without_trade_or_equity_change():
    history, state, journal = initialized()
    bar = next_bar(source_observed_at_utc="2026-03-04T08:00:00+00:00")
    updated, record = advance_forward_state(state, history, bar, journal)
    assert record["evidence_class"] == "retrospective"
    assert record["settlements"]["trend"] == {
        "status": "retrospective_not_scored", "net_pnl_yen": 0.0,
    }
    assert updated["rules"]["trend"]["equity_yen"] == 100_000.0


def test_same_day_bar_with_prior_decision_is_forward_scored():
    history, state, journal = initialized()
    updated, record = advance_forward_state(state, history, next_bar(), journal)
    assert record["evidence_class"] == "forward"
    assert record["settlements"]["trend"]["status"] == "traded"
    assert updated["rules"]["trend"]["equity_yen"] != 100_000.0


def test_decision_created_after_open_cannot_score_same_day_bar():
    history = rising_history()
    state, initial = initialize_forward_state(
        history, base_snapshot_sha256="a" * 64,
        source_observed_at_utc="2026-03-03T08:00:00+00:00",
    )
    updated, record = advance_forward_state(state, history, next_bar(), [initial])
    assert record["evidence_class"] == "retrospective"
    assert updated["rules"]["trend"]["equity_yen"] == 100_000.0


def test_batch_failure_on_second_row_leaves_original_state_unchanged():
    history, state, journal = initialized()
    bars = [
        next_bar(source_observed_at_utc="2026-03-04T08:00:00+00:00"),
        next_bar(
            bar_date="2026-03-04", high=100.0,
            source_observed_at_utc="2026-03-04T08:00:00+00:00",
        ),
    ]
    original = deepcopy(state)
    with pytest.raises(ValueError, match="invalid OHLCV"):
        advance_forward_batch(state, history, bars, journal)
    assert state == original


def test_multiple_records_are_persisted_in_one_checkpoint_update(tmp_path):
    history, state, journal = initialized()
    state_path = tmp_path / "state.json"
    journal_path = tmp_path / "journal.jsonl"
    write_initial_checkpoint(state_path, journal_path, state, journal[0])
    bars = [
        next_bar(source_observed_at_utc="2026-03-04T08:00:00+00:00"),
        next_bar(
            bar_date="2026-03-04", open=107.0, high=109.0, low=106.0,
            close=108.0, source_observed_at_utc="2026-03-04T08:00:00+00:00",
        ),
    ]
    updated, records = advance_forward_batch(state, history, bars, journal)
    append_checkpoints(state_path, journal_path, updated, records)
    loaded_state, loaded_journal = load_checkpoint(state_path, journal_path)
    assert loaded_state == updated
    assert loaded_journal == journal + records
