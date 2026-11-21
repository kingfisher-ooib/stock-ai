"""Pre-registered signal rules evaluated on confirmed prior-day data."""

from collections.abc import Mapping


REGISTERED_SIGNALS = ("trend", "trend_pullback", "volume_momentum")


def is_signal_active(
    name: str, features: Mapping[str, float], prior_close: float,
) -> bool:
    if name not in REGISTERED_SIGNALS:
        raise ValueError(f"unknown signal: {name}")
    in_uptrend = features["sma20"] > features["sma60"]
    if name == "trend":
        return in_uptrend
    if name == "trend_pullback":
        return in_uptrend and prior_close < features["ema20"]
    return (
        in_uptrend
        and features["macd_histogram"] > 0
        and features["volume_ratio"] >= 1.0
    )
