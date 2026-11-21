from stock_ai.backtest.intraday import BacktestResult, SimulatedTrade, run_intraday_sma_baseline, summarize
from stock_ai.config import Settings
import stock_ai.risk.engine as risk_module


def rising_bars():
    from datetime import date, timedelta

    start = date(2026, 1, 1)
    bars = []
    for i in range(60):
        close = 100 + i * 0.1
        bars.append({"bar_date": (start + timedelta(days=i)).isoformat(),
                     "open": close, "high": close + 1, "low": close - 1,
                     "close": close, "volume": 1000})
    bars.append({"bar_date": (start + timedelta(days=60)).isoformat(),
                 "open": 106.0, "high": 108.0, "low": 105.0,
                 "close": 107.0, "volume": 1000})
    return bars


def test_prior_day_signal_enters_next_open_and_exits_close():
    bars = rising_bars()
    result = run_intraday_sma_baseline(bars, start_date=bars[-1]["bar_date"],
                                       end_date=bars[-1]["bar_date"], bps_per_side=0)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.quantity == 40
    assert trade.entry_price == 106.0 and trade.exit_price == 107.0
    assert trade.net_pnl == 40.0
    assert result.daily_pnls == [40.0]


def test_cost_is_deducted_and_stop_takes_precedence_over_close():
    bars = rising_bars()
    date = bars[-1]["bar_date"]
    no_cost = run_intraday_sma_baseline(bars, start_date=date, end_date=date, bps_per_side=0)
    cost = run_intraday_sma_baseline(bars, start_date=date, end_date=date, bps_per_side=5)
    assert cost.trades[0].net_pnl < no_cost.trades[0].net_pnl
    bars[-1]["low"] = 103.0
    stopped = run_intraday_sma_baseline(bars, start_date=date, end_date=date, bps_per_side=0)
    assert stopped.trades[0].exit_reason == "stop"
    assert stopped.trades[0].net_pnl < 0


def test_fee_above_trade_risk_budget_rejects_all_new_entries():
    bars = rising_bars()
    date = bars[-1]["bar_date"]
    result = run_intraday_sma_baseline(bars, start_date=date, end_date=date,
                                       bps_per_side=0, fee_yen_per_side=55)
    assert result.trades == []
    assert result.skips.get("risk_rejected:minimum lot exceeds risk or position limit") == 1


def test_future_close_cannot_change_signal_or_size():
    bars = rising_bars()
    date = bars[-1]["bar_date"]
    first = run_intraday_sma_baseline(bars, start_date=date, end_date=date, bps_per_side=0)
    bars[-1]["close"] = 108.0
    second = run_intraday_sma_baseline(bars, start_date=date, end_date=date, bps_per_side=0)
    assert len(first.trades) == len(second.trades) == 1
    assert first.trades[0].quantity == second.trades[0].quantity
    assert first.trades[0].stop_price == second.trades[0].stop_price


def test_zero_trade_metrics_are_undefined():
    bars = rising_bars()
    result = run_intraday_sma_baseline(bars, start_date=bars[0]["bar_date"],
                                       end_date=bars[0]["bar_date"], bps_per_side=5)
    metrics = summarize(result)
    assert metrics["trade_count"] == 0
    assert metrics["expectancy_yen"] is None
    assert metrics["profit_factor"] is None
    assert metrics["daily_sharpe_unannualized"] is None


def test_block_bootstrap_expectancy_interval_for_sufficient_trades():
    result = BacktestResult("2026-01-01", "2026-02-09", 100000, 0, 0)
    result.dates = [f"day-{i}" for i in range(40)]
    result.daily_pnls = [1.0] * 40
    result.trades = [SimulatedTrade(day, 10, 100, 100.1, 99, "close", 1.0)
                     for day in result.dates]
    assert summarize(result)["expectancy_block_bootstrap_95pct_yen"] == [1.0, 1.0]


def test_registered_risk_limits_do_not_follow_runtime_defaults(monkeypatch):
    monkeypatch.setattr(risk_module, "Settings", lambda: Settings(
        max_position_ratio=0.9, max_trade_loss_ratio=0.01,
        max_daily_loss_ratio=0.02,
    ))
    bars = rising_bars()
    date = bars[-1]["bar_date"]
    result = run_intraday_sma_baseline(bars, start_date=date, end_date=date,
                                       bps_per_side=0)
    assert result.trades[0].quantity == 40


def test_registered_pullback_rule_can_skip_a_trend_entry():
    bars = rising_bars()
    date = bars[-1]["bar_date"]
    result = run_intraday_sma_baseline(
        bars, start_date=date, end_date=date, bps_per_side=0,
        signal_name="trend_pullback",
    )
    assert result.trades == []
    assert result.skips == {"signal_inactive": 1}


def test_target_day_close_and_volume_cannot_change_volume_momentum_entry():
    bars = rising_bars()
    date = bars[-1]["bar_date"]
    first = run_intraday_sma_baseline(
        bars, start_date=date, end_date=date, bps_per_side=0,
        signal_name="volume_momentum",
    )
    bars[-1]["close"] = 108.0
    bars[-1]["volume"] = 1_000_000
    second = run_intraday_sma_baseline(
        bars, start_date=date, end_date=date, bps_per_side=0,
        signal_name="volume_momentum",
    )
    assert len(first.trades) == len(second.trades) == 1
    assert first.trades[0].quantity == second.trades[0].quantity
    assert first.trades[0].stop_price == second.trades[0].stop_price
