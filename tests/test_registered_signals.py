import pytest

from stock_ai.backtest.signals import is_signal_active


def features(**overrides):
    values = {
        "sma20": 105.0,
        "sma60": 100.0,
        "ema20": 104.0,
        "macd_histogram": 0.5,
        "volume_ratio": 1.2,
    }
    values.update(overrides)
    return values


def test_trend_requires_fast_average_above_slow_average():
    assert is_signal_active("trend", features(), prior_close=106.0)
    assert not is_signal_active("trend", features(sma20=100.0), prior_close=106.0)


def test_pullback_requires_prior_close_below_ema_inside_trend():
    assert is_signal_active("trend_pullback", features(), prior_close=103.0)
    assert not is_signal_active("trend_pullback", features(), prior_close=104.0)


def test_volume_momentum_includes_exactly_average_volume():
    assert is_signal_active(
        "volume_momentum",
        features(volume_ratio=1.0, macd_histogram=0.01),
        prior_close=106.0,
    )
    assert not is_signal_active(
        "volume_momentum",
        features(volume_ratio=0.99, macd_histogram=0.01),
        prior_close=106.0,
    )
    assert not is_signal_active(
        "volume_momentum",
        features(volume_ratio=1.2, macd_histogram=0.0),
        prior_close=106.0,
    )


def test_unknown_signal_is_rejected():
    with pytest.raises(ValueError, match="unknown signal"):
        is_signal_active("invented", features(), prior_close=106.0)
