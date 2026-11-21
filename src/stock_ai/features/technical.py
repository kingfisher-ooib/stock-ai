"""Features computed from confirmed history through an explicit as-of index."""

from math import isfinite
from typing import Sequence


def _ema(values: list[float], span: int) -> list[float]:
    alpha = 2.0 / (span + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1 - alpha) * out[-1])
    return out


def compute_features(high: Sequence[float], low: Sequence[float],
                     close: Sequence[float], volume: Sequence[float],
                     as_of_index: int | None = None) -> dict[str, float]:
    length = len(close)
    if not (len(high) == len(low) == len(volume) == length):
        raise ValueError("OHLCV lengths differ")
    end = length - 1 if as_of_index is None else as_of_index
    if end < 59 or end >= length:
        raise ValueError("need at least 60 confirmed bars and a valid as-of index")
    h, l, c, v = ([float(x) for x in seq[:end + 1]] for seq in (high, low, close, volume))
    if not all(isfinite(x) for seq in (h, l, c, v) for x in seq):
        raise ValueError("nonfinite bar")
    if any(lo > cl or hi < cl or lo > hi or vol < 0 for hi, lo, cl, vol in zip(h, l, c, v)):
        raise ValueError("invalid bar")

    changes = [c[i] - c[i - 1] for i in range(1, len(c))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains[:14]) / 14
    avg_loss = sum(losses[:14]) / 14
    for gain, loss in zip(gains[14:], losses[14:]):
        avg_gain = (avg_gain * 13 + gain) / 14
        avg_loss = (avg_loss * 13 + loss) / 14
    rsi = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)

    ema12, ema26 = _ema(c, 12), _ema(c, 26)
    macd_line = [a - b for a, b in zip(ema12, ema26)]
    macd_signal = _ema(macd_line, 9)[-1]
    tr = [h[0] - l[0]]
    tr.extend(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
              for i in range(1, len(c)))
    atr = sum(tr[1:15]) / 14
    for value in tr[15:]:
        atr = (atr * 13 + value) / 14
    vol20 = sum(v[-20:]) / 20
    return {
        "sma20": sum(c[-20:]) / 20, "sma60": sum(c[-60:]) / 60,
        "ema20": _ema(c, 20)[-1], "rsi14": rsi,
        "macd": macd_line[-1], "macd_signal": macd_signal,
        "macd_histogram": macd_line[-1] - macd_signal,
        "atr14": atr, "volume_sma20": vol20,
        "volume_ratio": v[-1] / vol20 if vol20 > 0 else 0.0,
    }
