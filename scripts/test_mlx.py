"""One local LLM schema check. Start the MLX server first."""

import json
from stock_ai.ai.mlx_client import MLXTradeClient


def main() -> None:
    market = {"symbol": "TEST", "close": 1000, "sma20": 980, "sma60": 950,
              "rsi14": 55, "atr14": 20, "volume_ratio": 1.4}
    predictions = {"timesfm_signal": "bullish", "chronos_signal": "bullish"}
    result = MLXTradeClient().make_trade_decision(market, predictions)
    if result.reason and result.reason[0].startswith(("LLM response unavailable or invalid", "LLM returned empty content")):
        raise RuntimeError(result.reason[0])
    print(json.dumps(result.model_dump(), ensure_ascii=False))


if __name__ == "__main__":
    main()
