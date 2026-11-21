"""Research-only orchestration. No broker calls or persistence side effects."""

from dataclasses import dataclass
from typing import Protocol, Sequence

from stock_ai.ai.ensemble import EnsembleResult, combine
from stock_ai.ai.forecast import Forecast
from stock_ai.ai.mlx_client import MLXTradeClient, TradeDecision
from stock_ai.features.technical import compute_features
from stock_ai.risk.engine import RiskAssessment, RiskEngine


class Forecaster(Protocol):
    def predict(self, values: Sequence[float], horizon: int = 5) -> Forecast: ...


@dataclass(frozen=True)
class ResearchResult:
    features: dict[str, float]
    timesfm: Forecast
    chronos: Forecast
    ensemble: EnsembleResult
    decision: TradeDecision
    risk: RiskAssessment


class ResearchPipeline:
    def __init__(self, timesfm: Forecaster, chronos: Forecaster,
                 llm: MLXTradeClient, risk: RiskEngine | None = None):
        self.timesfm = timesfm
        self.chronos = chronos
        self.llm = llm
        self.risk = risk or RiskEngine()

    def run(self, *, symbol: str, high: Sequence[float], low: Sequence[float],
            close: Sequence[float], volume: Sequence[float], as_of_index: int,
            horizon: int, equity: float, daily_pnl: float,
            stop_price: float | None = None, current_quantity: int = 0) -> ResearchResult:
        # A fixed as-of boundary is used for every feature and model input.
        features = compute_features(high, low, close, volume, as_of_index)
        history = list(close[:as_of_index + 1])[-512:]
        timesfm = self.timesfm.predict(history, horizon)
        chronos = self.chronos.predict(history, horizon)
        ensemble = combine(timesfm, chronos, float(history[-1]))
        decision = self.llm.make_trade_decision(
            {"symbol": symbol, "close": float(history[-1]), **features},
            {"timesfm": timesfm.as_dict(), "chronos": chronos.as_dict(),
             "ensemble": ensemble.as_dict()},
        )
        risk = self.risk.assess(decision, symbol=symbol, equity=equity,
                                daily_pnl=daily_pnl, price=float(history[-1]),
                                stop_price=stop_price, current_quantity=current_quantity)
        return ResearchResult(features, timesfm, chronos, ensemble, decision, risk)
