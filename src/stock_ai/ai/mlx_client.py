"""Fail-closed client for the loopback MLX OpenAI-compatible endpoint."""

import json
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from stock_ai.config import Settings, require_local_url


class TradeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: list[str]


def safe_hold(reason: str) -> TradeDecision:
    return TradeDecision(action="HOLD", confidence=0.0, reason=[reason])


class MLXTradeClient:
    def __init__(self, base_url: str | None = None, model: str | None = None):
        settings = Settings()
        self.base_url = require_local_url(base_url or settings.mlx_base_url)
        self.model = model or settings.mlx_model
        self._client = OpenAI(base_url=self.base_url, api_key="local", timeout=90.0, max_retries=0)

    def make_trade_decision(self, market_data: dict, predictions: dict) -> TradeDecision:
        # Model output is advice only. Order sizing and approval remain in RiskEngine.
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": (
                        "You are a research-only stock signal summarizer. "
                        "Return ONLY one JSON object with action BUY, SELL, or HOLD, "
                        "confidence as a number 0..1, and reason as a list of strings. "
                        "You cannot place orders or decide position size. "
                        "If evidence is weak, choose HOLD."
                    )},
                    {"role": "user", "content": json.dumps({
                        "market_data": market_data, "predictions": predictions
                    }, ensure_ascii=False, allow_nan=False)},
                ],
                temperature=0.0,
                max_tokens=256,
            )
            content = response.choices[0].message.content
            if not content:
                return safe_hold("LLM returned empty content")
            return TradeDecision.model_validate_json(content)
        except Exception as exc:
            # Never promote malformed or unavailable LLM output into a tradable signal.
            return safe_hold(f"LLM response unavailable or invalid: {type(exc).__name__}")
