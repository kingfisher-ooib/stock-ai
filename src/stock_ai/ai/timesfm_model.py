"""TimesFM 2.5 adapter; uses PyTorch MPS when available."""

from typing import Sequence

import numpy as np
import torch

from stock_ai.ai.forecast import Forecast, validate_values
from stock_ai.config import Settings


class TimesFMModel:
    def __init__(self, model_id: str | None = None):
        import timesfm

        self.model_id = model_id or Settings().timesfm_model
        if self.model_id != "google/timesfm-2.5-200m-pytorch":
            raise ValueError("Only the reviewed Apache-2.0 TimesFM 2.5 checkpoint is supported")
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
            self.model_id, torch_compile=False
        )
        if self.device == "mps":
            self.model.model.to(torch.device("mps"))
            self.model.model.device = torch.device("mps")
        self.model.compile(timesfm.ForecastConfig(
            max_context=512, max_horizon=256, per_core_batch_size=1,
            normalize_inputs=True, use_continuous_quantile_head=False,
        ))

    def predict(self, values: Sequence[float], horizon: int = 5) -> Forecast:
        cleaned = validate_values(values, horizon)
        points, _ = self.model.forecast(horizon=horizon, inputs=[np.asarray(cleaned, dtype=np.float32)])
        return Forecast("timesfm", horizon, tuple(float(x) for x in points[0, :horizon]), self.device)
