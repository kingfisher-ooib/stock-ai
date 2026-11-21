"""Single pre-registered, research-only 1475 intraday baseline."""

from dataclasses import dataclass, field
from math import isfinite
from random import Random
from statistics import mean, stdev
from typing import Sequence

from stock_ai.ai.mlx_client import TradeDecision
from stock_ai.backtest.signals import REGISTERED_SIGNALS, is_signal_active
from stock_ai.config import Settings
from stock_ai.features.technical import compute_features
from stock_ai.risk.engine import RiskEngine


@dataclass(frozen=True)
class SimulatedTrade:
    date: str
    quantity: int
    entry_price: float
    exit_price: float
    stop_price: float
    exit_reason: str
    net_pnl: float


@dataclass
class BacktestResult:
    start_date: str
    end_date: str
    initial_equity: float
    bps_per_side: float
    fee_yen_per_side: float
    dates: list[str] = field(default_factory=list)
    daily_pnls: list[float] = field(default_factory=list)
    trades: list[SimulatedTrade] = field(default_factory=list)
    skips: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skips[reason] = self.skips.get(reason, 0) + 1


def run_intraday_sma_baseline(
    bars: Sequence[dict], *, start_date: str, end_date: str,
    bps_per_side: float = 5.0, fee_yen_per_side: float = 0.0,
    initial_equity: float = 100_000.0, signal_name: str = "trend",
) -> BacktestResult:
    """Use prior close features, hypothetical open/stop/close fills and fee-aware sizing."""
    if (start_date > end_date or not isfinite(bps_per_side) or bps_per_side < 0
            or not isfinite(fee_yen_per_side) or fee_yen_per_side < 0
            or not isfinite(initial_equity) or initial_equity <= 0):
        raise ValueError("invalid simulation configuration")
    if signal_name not in REGISTERED_SIGNALS:
        raise ValueError(f"unknown signal: {signal_name}")
    result = BacktestResult(start_date, end_date, initial_equity, bps_per_side, fee_yen_per_side)
    dates = [bar["bar_date"] for bar in bars]
    if dates != sorted(set(dates)):
        raise ValueError("bar dates must be unique and increasing")
    high = [float(bar["high"]) for bar in bars]
    low = [float(bar["low"]) for bar in bars]
    close = [float(bar["close"]) for bar in bars]
    volume = [float(bar["volume"]) for bar in bars]
    engine = RiskEngine(lot_size=10, settings=Settings(
        min_ai_confidence=0.70, max_position_ratio=0.05,
        max_daily_loss_ratio=0.02, max_trade_loss_ratio=0.001,
    ))
    equity = initial_equity
    impact = bps_per_side / 10_000
    buy_signal = TradeDecision(action="BUY", confidence=1.0, reason=["fixed deterministic baseline"])
    sell_signal = TradeDecision(action="SELL", confidence=1.0, reason=["same-day deterministic exit"])
    for i, bar in enumerate(bars):
        day = dates[i]
        if day < start_date or day > end_date:
            continue
        result.dates.append(day)
        result.daily_pnls.append(0.0)
        if i < 60:
            result.skip("insufficient_history")
            continue
        features = compute_features(high, low, close, volume, as_of_index=i - 1)
        if not is_signal_active(signal_name, features, prior_close=close[i - 1]):
            result.skip("signal_inactive")
            continue
        open_price = float(bar["open"])
        if not all(isfinite(x) for x in (open_price, high[i], low[i], close[i])):
            raise ValueError(f"nonfinite target bar: {day}")
        if not 0 < low[i] <= min(open_price, close[i]) <= max(open_price, close[i]) <= high[i]:
            raise ValueError(f"invalid target OHLC: {day}")
        stop_reference = close[i - 1] - features["atr14"]
        if stop_reference <= 0 or open_price <= stop_reference:
            result.skip("open_below_stop")
            continue
        entry = open_price * (1 + impact)
        protected_exit = stop_reference * (1 - impact)
        assessment = engine.assess(buy_signal, symbol="1475", equity=equity,
                                   daily_pnl=0, price=entry, stop_price=protected_exit,
                                   estimated_round_trip_fee_yen=2 * fee_yen_per_side)
        if not assessment.approved:
            result.skip("risk_rejected:" + assessment.reason)
            continue
        quantity = assessment.candidate.quantity
        hit_stop = low[i] <= stop_reference
        exit_price = protected_exit if hit_stop else close[i] * (1 - impact)
        exit_assessment = engine.assess(sell_signal, symbol="1475", equity=equity,
                                        daily_pnl=0, price=exit_price,
                                        stop_price=None, current_quantity=quantity)
        if not exit_assessment.approved:
            raise RuntimeError("risk engine rejected deterministic exit")
        pnl = quantity * (exit_price - entry) - 2 * fee_yen_per_side
        trade = SimulatedTrade(day, quantity, entry, exit_price, stop_reference,
                               "stop" if hit_stop else "close", pnl)
        result.trades.append(trade)
        result.daily_pnls[-1] = pnl
        equity += pnl
    return result


def summarize(result: BacktestResult) -> dict:
    """Report net statistics, with undefined values left as None."""
    pnls = [trade.net_pnl for trade in result.trades]
    gains = sum(x for x in pnls if x > 0)
    losses = -sum(x for x in pnls if x < 0)
    equity = result.initial_equity
    peak = equity
    max_drawdown = 0.0
    daily_returns = []
    for pnl in result.daily_pnls:
        daily_returns.append(pnl / equity if equity > 0 else 0.0)
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    spread = stdev(daily_returns) if len(daily_returns) >= 2 else 0.0
    sharpe = mean(daily_returns) / spread if spread > 0 else None
    interval = None
    if len(pnls) >= 30 and len(result.dates) >= 5:
        rng = Random(20261115)
        trade_days = {trade.date for trade in result.trades}
        observations = [(pnl, int(day in trade_days))
                        for day, pnl in zip(result.dates, result.daily_pnls)]
        n = len(observations)
        estimates = []
        for _ in range(1000):
            sample = []
            while len(sample) < n:
                start = rng.randrange(n - 4)
                sample.extend(observations[start:start + 5])
            sample = sample[:n]
            count = sum(item[1] for item in sample)
            if count:
                estimates.append(sum(item[0] for item in sample) / count)
        if estimates:
            estimates.sort()
            interval = [estimates[int(0.025 * (len(estimates) - 1))],
                        estimates[int(0.975 * (len(estimates) - 1))]]
    return {
        "period": [result.start_date, result.end_date],
        "days": len(result.dates), "trade_count": len(pnls),
        "net_pnl_yen": sum(pnls),
        "expectancy_yen": mean(pnls) if pnls else None,
        "expectancy_block_bootstrap_95pct_yen": interval,
        "bootstrap_definition": "1000 fixed-seed resamples of 5-trading-day blocks; None if <30 trades",
        "profit_factor": gains / losses if losses > 0 else None,
        "daily_sharpe_unannualized": sharpe,
        "sharpe_definition": "mean/std of daily equity returns, sample std, risk-free=0, no annualization",
        "max_drawdown_ratio": max_drawdown,
        "win_count": sum(x > 0 for x in pnls),
        "loss_count": sum(x < 0 for x in pnls),
        "skips": result.skips,
    }
