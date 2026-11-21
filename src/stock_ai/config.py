"""Configuration with local-only defaults."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    mlx_base_url: str = os.getenv("MLX_BASE_URL", "http://127.0.0.1:8080/v1")
    mlx_model: str = os.getenv("MLX_MODEL", "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit")
    timesfm_model: str = os.getenv("TIMESFM_MODEL", "google/timesfm-2.5-200m-pytorch")
    chronos_model: str = os.getenv("CHRONOS_MODEL", "amazon/chronos-2")
    min_ai_confidence: float = float(os.getenv("MIN_AI_CONFIDENCE", "0.70"))
    max_position_ratio: float = float(os.getenv("MAX_POSITION_RATIO", "0.05"))
    max_daily_loss_ratio: float = float(os.getenv("MAX_DAILY_LOSS_RATIO", "0.02"))
    max_trade_loss_ratio: float = float(os.getenv("MAX_TRADE_LOSS_RATIO", "0.001"))

    def __post_init__(self) -> None:
        values = (self.min_ai_confidence, self.max_position_ratio,
                  self.max_daily_loss_ratio, self.max_trade_loss_ratio)
        if not all(0 < value <= 1 for value in values):
            raise ValueError("risk ratios and confidence must be in (0, 1]")
        if self.max_trade_loss_ratio > self.max_daily_loss_ratio:
            raise ValueError("per-trade loss limit cannot exceed daily loss limit")


def require_local_url(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port != 8080:
        raise ValueError("MLX API must be http://127.0.0.1:8080/v1")
    if parsed.path.rstrip("/") != "/v1":
        raise ValueError("MLX API path must be /v1")
    return url
