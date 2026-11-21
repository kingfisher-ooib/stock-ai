"""Chronos-2 adapter; prefers MPS and exposes the 0.5 quantile."""

from typing import Sequence

import numpy as np
import torch
from chronos import BaseChronosPipeline

from stock_ai.ai.forecast import Forecast, validate_values
from stock_ai.config import Settings


class ChronosModel:
    def __init__(self, model_id: str | None = None):
        self.model_id = model_id or Settings().chronos_model
        if self.model_id != "amazon/chronos-2":
            raise ValueError("Only the reviewed Apache-2.0 Chronos-2 checkpoint is supported")
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.pipeline = BaseChronosPipeline.from_pretrained(self.model_id, device_map=self.device)

    def predict(self, values: Sequence[float], horizon: int = 5) -> Forecast:
        cleaned = validate_values(values, horizon)
        quantiles, _ = self.pipeline.predict_quantiles(
            [np.asarray(cleaned, dtype=np.float32)], prediction_length=horizon,
            quantile_levels=[0.5], batch_size=1,
        )
        arr = quantiles[0].detach().cpu().numpy().reshape(-1)
        return Forecast("chronos", horizon, tuple(float(x) for x in arr[:horizon]), self.device)
