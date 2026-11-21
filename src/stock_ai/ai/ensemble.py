"""Deterministic agreement of independent point forecasts."""

from dataclasses import dataclass
from math import isfinite

from stock_ai.ai.forecast import Forecast


@dataclass(frozen=True)
class EnsembleResult:
    signal: str
    timesfm_direction: str
    chronos_direction: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _direction(forecast: Forecast, last_close: float) -> str:
    end = forecast.prediction[-1]
    if end > last_close:
        return "bullish"
    if end < last_close:
        return "bearish"
    return "neutral"


def combine(timesfm: Forecast, chronos: Forecast, last_close: float) -> EnsembleResult:
    if not isfinite(last_close) or last_close <= 0:
        raise ValueError("last_close must be positive and finite")
    if timesfm.model != "timesfm" or chronos.model != "chronos":
        raise ValueError("wrong forecast models")
    if timesfm.horizon != chronos.horizon:
        raise ValueError("forecast horizons differ")
    a, b = _direction(timesfm, last_close), _direction(chronos, last_close)
    return EnsembleResult(a if a == b else "neutral", a, b)
