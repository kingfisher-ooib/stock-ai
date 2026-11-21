"""Deterministic risk gate. It has no broker or network adapter."""

from dataclasses import dataclass
from math import floor, isfinite

from stock_ai.ai.mlx_client import TradeDecision
from stock_ai.config import Settings


@dataclass(frozen=True)
class OrderCandidate:
    symbol: str
    action: str
    quantity: int
    reference_price: float
    stop_price: float | None


@dataclass(frozen=True)
class RiskAssessment:
    approved: bool
    reason: str
    candidate: OrderCandidate | None = None


class RiskEngine:
    def __init__(self, lot_size: int = 10, settings: Settings | None = None):
        self.settings = settings or Settings()
        if lot_size < 1:
            raise ValueError("lot_size must be positive")
        self.lot_size = lot_size

    def assess(self, decision: TradeDecision, *, symbol: str, equity: float,
               daily_pnl: float, price: float, stop_price: float | None,
               current_quantity: int = 0,
               estimated_round_trip_fee_yen: float = 0.0) -> RiskAssessment:
        if not symbol or not all(isfinite(v) for v in (
                equity, daily_pnl, price, estimated_round_trip_fee_yen)):
            return RiskAssessment(False, "invalid account or price data")
        if equity <= 0 or price <= 0 or current_quantity < 0 or estimated_round_trip_fee_yen < 0:
            return RiskAssessment(False, "invalid account or price data")
        if decision.action == "HOLD":
            return RiskAssessment(False, "HOLD signal")
        if decision.confidence < self.settings.min_ai_confidence:
            return RiskAssessment(False, "AI confidence below minimum")
        if decision.action == "SELL":
            if current_quantity < self.lot_size:
                return RiskAssessment(False, "no full lot to exit")
            quantity = (current_quantity // self.lot_size) * self.lot_size
            return RiskAssessment(True, "exit candidate", OrderCandidate(symbol, "SELL", quantity, price, None))
        if daily_pnl <= -equity * self.settings.max_daily_loss_ratio:
            return RiskAssessment(False, "daily loss limit reached")
        if current_quantity:
            return RiskAssessment(False, "existing position; new buys disabled")
        if stop_price is None or not isfinite(stop_price) or stop_price <= 0 or stop_price >= price:
            return RiskAssessment(False, "valid protective stop required")
        per_unit_risk = price - stop_price
        risk_after_fees = equity * self.settings.max_trade_loss_ratio - estimated_round_trip_fee_yen
        max_by_risk = floor(risk_after_fees / per_unit_risk)
        max_by_position = floor(equity * self.settings.max_position_ratio / price)
        max_by_cash = floor(equity / price)
        quantity = min(max_by_risk, max_by_position, max_by_cash)
        quantity = (quantity // self.lot_size) * self.lot_size
        if quantity < self.lot_size:
            return RiskAssessment(False, "minimum lot exceeds risk or position limit")
        return RiskAssessment(True, "buy candidate only; no broker connected",
                              OrderCandidate(symbol, "BUY", quantity, price, stop_price))
