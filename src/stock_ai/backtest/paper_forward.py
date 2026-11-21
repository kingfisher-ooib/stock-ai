"""Local paper-forward state and tamper-evident journal."""

import hashlib
import json
import os
import tempfile
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from pathlib import Path

from stock_ai.ai.mlx_client import TradeDecision
from stock_ai.backtest.signals import REGISTERED_SIGNALS, is_signal_active
from stock_ai.config import Settings
from stock_ai.features.technical import compute_features
from stock_ai.risk.engine import RiskEngine


JST = timezone(timedelta(hours=9))


def _parse_observed_at(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("source_observed_at_utc must include timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _next_decisions(bars) -> dict:
    high = [float(bar["high"]) for bar in bars]
    low = [float(bar["low"]) for bar in bars]
    close = [float(bar["close"]) for bar in bars]
    volume = [float(bar["volume"]) for bar in bars]
    features = compute_features(high, low, close, volume, as_of_index=len(bars) - 1)
    stop_reference = close[-1] - features["atr14"]
    return {
        name: {
            "active": is_signal_active(name, features, prior_close=close[-1]),
            "stop_reference": stop_reference,
        }
        for name in REGISTERED_SIGNALS
    }


def _validated_bar(new_bar: dict, state: dict) -> dict:
    required = {
        "bar_date", "open", "high", "low", "close", "volume",
        "source_observed_at_utc", "provenance",
    }
    if not required.issubset(new_bar):
        raise ValueError("new bar is missing required fields")
    day = date.fromisoformat(str(new_bar["bar_date"])).isoformat()
    if day <= state["last_bar_date"]:
        raise ValueError("new bar date must be strictly later")
    prices = [float(new_bar[key]) for key in ("open", "high", "low", "close")]
    open_price, high, low, close = prices
    volume = float(new_bar["volume"])
    if (
        not all(isfinite(value) for value in (*prices, volume))
        or not 0 < low <= min(open_price, close) <= max(open_price, close) <= high
        or volume <= 0
        or not volume.is_integer()
    ):
        raise ValueError("invalid OHLCV")
    observed_at = _parse_observed_at(str(new_bar["source_observed_at_utc"]))
    daily_cutoff = datetime.combine(date.fromisoformat(day), time(16, 0), JST)
    if datetime.fromisoformat(observed_at) < daily_cutoff.astimezone(timezone.utc):
        raise ValueError("source observation is before fixed daily bar cutoff")
    if datetime.fromisoformat(observed_at) < datetime.fromisoformat(
        state["last_source_observed_at_utc"]
    ):
        raise ValueError("source observation time must not regress")
    provenance = str(new_bar["provenance"]).strip()
    if not provenance:
        raise ValueError("provenance is required")
    return {
        "bar_date": day,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": int(volume),
        "source_observed_at_utc": observed_at,
        "provenance": provenance,
    }


def hash_record(record: dict) -> str:
    payload = {key: value for key, value in record.items() if key != "record_hash"}
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def verify_journal(records: list[dict]) -> str:
    if not records:
        raise ValueError("journal is empty")
    previous = None
    for record in records:
        if record.get("previous_hash") != previous:
            raise ValueError("journal chain mismatch")
        if record.get("record_hash") != hash_record(record):
            raise ValueError("journal hash mismatch")
        previous = record["record_hash"]
    return previous


def initialize_forward_state(
    bars, *, base_snapshot_sha256: str, source_observed_at_utc: str,
) -> tuple[dict, dict]:
    if len(bars) < 60:
        raise ValueError("need at least 60 confirmed bars")
    dates = [bar["bar_date"] for bar in bars]
    if dates != sorted(set(dates)):
        raise ValueError("bar dates must be unique and increasing")
    observed_at = _parse_observed_at(source_observed_at_utc)
    decisions = _next_decisions(bars)
    record = {
        "event": "initialize",
        "previous_hash": None,
        "symbol": "1475",
        "base_snapshot_sha256": base_snapshot_sha256,
        "last_bar_date": dates[-1],
        "source_observed_at_utc": observed_at,
        "cost_assumption": {"bps_per_side": 5.0, "fee_yen_per_side": 0.0},
        "next_decisions": decisions,
    }
    record["record_hash"] = hash_record(record)
    state = {
        "schema_version": 1,
        "symbol": "1475",
        "base_snapshot_sha256": base_snapshot_sha256,
        "last_bar_date": dates[-1],
        "last_source_observed_at_utc": observed_at,
        "bps_per_side": 5.0,
        "fee_yen_per_side": 0.0,
        "forward_bars": [],
        "rules": {
            name: {"equity_yen": 100_000.0, "pending": deepcopy(decisions[name])}
            for name in REGISTERED_SIGNALS
        },
        "journal_tail_hash": record["record_hash"],
    }
    return state, record


def advance_forward_state(
    state: dict, history, new_bar: dict, journal_records: list[dict],
) -> tuple[dict, dict]:
    tail = verify_journal(journal_records)
    if state.get("journal_tail_hash") != tail:
        raise ValueError("state journal tail mismatch")
    if not history or history[-1]["bar_date"] != state.get("last_bar_date"):
        raise ValueError("history does not match state")
    bar = _validated_bar(new_bar, state)
    updated = deepcopy(state)
    impact = float(state["bps_per_side"]) / 10_000
    fee_per_side = float(state["fee_yen_per_side"])
    engine = RiskEngine(lot_size=10, settings=Settings(
        min_ai_confidence=0.70,
        max_position_ratio=0.05,
        max_daily_loss_ratio=0.02,
        max_trade_loss_ratio=0.001,
    ))
    buy = TradeDecision(action="BUY", confidence=1.0, reason=["frozen paper-forward rule"])
    settlements = {}
    for name in REGISTERED_SIGNALS:
        rule_state = updated["rules"][name]
        pending = rule_state["pending"]
        if not pending["active"]:
            settlements[name] = {"status": "no_signal", "net_pnl_yen": 0.0}
            continue
        stop = float(pending["stop_reference"])
        if bar["open"] <= stop:
            settlements[name] = {"status": "open_below_stop", "net_pnl_yen": 0.0}
            continue
        entry = bar["open"] * (1 + impact)
        protected_exit = stop * (1 - impact)
        assessment = engine.assess(
            buy, symbol="1475", equity=rule_state["equity_yen"], daily_pnl=0.0,
            price=entry, stop_price=protected_exit,
            estimated_round_trip_fee_yen=2 * fee_per_side,
        )
        if not assessment.approved:
            settlements[name] = {
                "status": "risk_rejected",
                "reason": assessment.reason,
                "net_pnl_yen": 0.0,
            }
            continue
        quantity = assessment.candidate.quantity
        hit_stop = bar["low"] <= stop
        exit_price = protected_exit if hit_stop else bar["close"] * (1 - impact)
        pnl = quantity * (exit_price - entry) - 2 * fee_per_side
        rule_state["equity_yen"] += pnl
        settlements[name] = {
            "status": "traded",
            "quantity": quantity,
            "entry_price": entry,
            "exit_price": exit_price,
            "stop_reference": stop,
            "exit_reason": "stop" if hit_stop else "close",
            "net_pnl_yen": pnl,
        }

    confirmed_history = [*history, bar]
    next_decisions = _next_decisions(confirmed_history)
    for name in REGISTERED_SIGNALS:
        updated["rules"][name]["pending"] = deepcopy(next_decisions[name])
    updated["last_bar_date"] = bar["bar_date"]
    updated["last_source_observed_at_utc"] = bar["source_observed_at_utc"]
    updated["forward_bars"].append(deepcopy(bar))
    record = {
        "event": "advance",
        "previous_hash": tail,
        "symbol": "1475",
        "input_bar": bar,
        "settlements": settlements,
        "equity_after_yen": {
            name: updated["rules"][name]["equity_yen"] for name in REGISTERED_SIGNALS
        },
        "next_decisions": next_decisions,
    }
    record["record_hash"] = hash_record(record)
    updated["journal_tail_hash"] = record["record_hash"]
    return updated, record


def advance_forward_batch(
    state: dict, history, bars, journal_records: list[dict],
) -> tuple[dict, list[dict]]:
    if not bars:
        raise ValueError("batch contains no bars")
    current_state = deepcopy(state)
    current_history = list(history)
    current_journal = list(journal_records)
    new_records = []
    for bar in bars:
        current_state, record = advance_forward_state(
            current_state, current_history, bar, current_journal,
        )
        current_history.append(record["input_bar"])
        current_journal.append(record)
        new_records.append(record)
    return current_state, new_records


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_initial_checkpoint(state_path, journal_path, state: dict, record: dict) -> None:
    state_path, journal_path = Path(state_path), Path(journal_path)
    if state_path.exists() or journal_path.exists():
        raise FileExistsError("checkpoint already exists")
    if verify_journal([record]) != state.get("journal_tail_hash"):
        raise ValueError("state journal tail mismatch")
    journal_text = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
    state_text = json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    _atomic_write_text(journal_path, journal_text)
    _atomic_write_text(state_path, state_text)


def load_checkpoint(state_path, journal_path) -> tuple[dict, list[dict]]:
    state_path, journal_path = Path(state_path), Path(journal_path)
    state = json.loads(state_path.read_text())
    records = [json.loads(line) for line in journal_path.read_text().splitlines() if line.strip()]
    tail = verify_journal(records)
    if state.get("journal_tail_hash") != tail:
        raise ValueError("state journal tail mismatch")
    return state, records


def append_checkpoint(state_path, journal_path, state: dict, record: dict) -> None:
    append_checkpoints(state_path, journal_path, state, [record])


def append_checkpoints(state_path, journal_path, state: dict, records: list[dict]) -> None:
    if not records:
        raise ValueError("no checkpoint records to append")
    state_path, journal_path = Path(state_path), Path(journal_path)
    previous_state, existing = load_checkpoint(state_path, journal_path)
    if records[0].get("previous_hash") != previous_state["journal_tail_hash"]:
        raise ValueError("new records do not extend journal")
    combined = [*existing, *records]
    if verify_journal(combined) != state.get("journal_tail_hash"):
        raise ValueError("state journal tail mismatch")
    journal_text = "".join(
        json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n" for item in combined
    )
    state_text = json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    _atomic_write_text(journal_path, journal_text)
    _atomic_write_text(state_path, state_text)
