"""Common forecast result and input validation."""

from dataclasses import dataclass
from math import isfinite
from typing import Sequence


@dataclass(frozen=True)
class Forecast:
    model: str
    horizon: int
    prediction: tuple[float, ...]
    device: str

    def __post_init__(self) -> None:
        if self.horizon < 1 or len(self.prediction) != self.horizon:
            raise ValueError("Forecast length must equal positive horizon")
        if not all(isfinite(value) for value in self.prediction):
            raise ValueError("Forecast contains nonfinite value")

    def as_dict(self) -> dict:
        return {"model": self.model, "horizon": self.horizon,
                "prediction": list(self.prediction), "device": self.device}


def validate_values(values: Sequence[float], horizon: int) -> list[float]:
    if horizon < 1 or horizon > 256:
        raise ValueError("horizon must be 1..256")
    if len(values) < 32:
        raise ValueError("at least 32 past observations required")
    result = [float(value) for value in values]
    if not all(isfinite(value) and value > 0 for value in result):
        raise ValueError("prices must be positive finite numbers")
    return result
