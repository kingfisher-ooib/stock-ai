"""End-to-end local inference smoke test; no orders or market data."""

import platform
import sys
import time
import urllib.request


def check(number: int, name: str, fn, remedy: str):
    try:
        value = fn()
        print(f"[{number}] {name:<23} OK {value if value is not None else ''}")
        return value
    except Exception as exc:
        print(f"[{number}] {name:<23} FAILED")
        print(f"    原因: {type(exc).__name__}: {exc}")
        print(f"    推奨対処: {remedy}")
        return None


def main() -> int:
    if sys.version_info[:2] != (3, 12):
        print("[1] Python environment      FAILED: Python 3.12 required")
        return 1
    print(f"[1] Python environment      OK {platform.python_version()}")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        print("[2] Apple Silicon           FAILED: macOS arm64 required")
        return 1
    print("[2] Apple Silicon           OK arm64")

    def mlx_check():
        import mlx.core as mx
        return float(mx.sum(mx.array([1.0, 2.0])).item())
    mlx = check(3, "MLX", mlx_check, "Install dependencies with uv sync and run outside a GPU-restricted sandbox")

    def server_check():
        from stock_ai.config import Settings, require_local_url
        url = require_local_url(Settings().mlx_base_url)
        with urllib.request.urlopen(url + "/models", timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("server returned non-200")
        return "127.0.0.1:8080"
    server = check(4, "MLX Server", server_check, "Run bash scripts/start_mlx_server.sh in another terminal")

    def qwen_check():
        from stock_ai.ai.mlx_client import MLXTradeClient
        market = {"symbol": "TEST", "close": 1000, "sma20": 980,
                  "sma60": 950, "rsi14": 55, "atr14": 20, "volume_ratio": 1.4}
        start = time.perf_counter()
        decision = MLXTradeClient().make_trade_decision(
            market, {"timesfm_signal": "bullish", "chronos_signal": "bullish"})
        if decision.reason and decision.reason[0].startswith(("LLM response unavailable or invalid", "LLM returned empty content")):
            raise RuntimeError(decision.reason[0])
        return f"{decision.action} {time.perf_counter()-start:.2f}s"
    qwen = check(5, "Qwen response", qwen_check, "Check model download/server logs and JSON output") if server else None
    if qwen is None and not server:
        print("[5] Qwen response           FAILED: MLX Server unavailable")

    values = [100 + i * 0.25 + (i % 5) * 0.1 for i in range(64)]
    def timesfm_check():
        from stock_ai.ai.timesfm_model import TimesFMModel
        result = TimesFMModel().predict(values, horizon=5)
        return result
    timesfm = check(6, "TimesFM", timesfm_check, "Check checkpoint download and MPS compatibility")

    def chronos_check():
        from stock_ai.ai.chronos_model import ChronosModel
        result = ChronosModel().predict(values, horizon=5)
        return result
    chronos = check(7, "Chronos", chronos_check, "Check checkpoint download; retry CPU if MPS operation fails")

    def ensemble_check():
        from stock_ai.ai.ensemble import combine
        if not timesfm or not chronos:
            raise RuntimeError("forecasts unavailable")
        return combine(timesfm, chronos, values[-1]).signal
    ensemble = check(8, "Ensemble", ensemble_check, "Resolve forecasting failures first")

    def risk_check():
        from stock_ai.ai.mlx_client import TradeDecision
        from stock_ai.risk.engine import RiskEngine
        engine = RiskEngine()
        signal = TradeDecision(action="BUY", confidence=0.99, reason=["dummy"])
        rejected = engine.assess(signal, symbol="TEST", equity=100000,
                                 daily_pnl=0, price=400, stop_price=None)
        allowed = engine.assess(signal, symbol="TEST", equity=100000,
                                daily_pnl=0, price=400, stop_price=395)
        if rejected.approved or not allowed.approved or allowed.candidate.quantity != 10:
            raise AssertionError("risk gate did not enforce protective stop or size")
        return "unprotected BUY rejected; 10-unit candidate accepted"
    risk = check(9, "Risk Engine", risk_check, "Inspect deterministic risk limits")
    return 0 if all(x is not None for x in (mlx, server, qwen, timesfm, chronos, ensemble, risk)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
