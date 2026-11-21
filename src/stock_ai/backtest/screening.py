"""Candidate screening for pre-registered exploratory rules."""

from math import isfinite


def passes_candidate_gate(metrics: dict) -> bool:
    try:
        trade_count = metrics["trade_count"]
        net_pnl = metrics["net_pnl_yen"]
        profit_factor = metrics["profit_factor"]
        interval = metrics["expectancy_block_bootstrap_95pct_yen"]
    except KeyError:
        return False
    if profit_factor is None or interval is None or len(interval) != 2:
        return False
    values = (float(net_pnl), float(profit_factor), float(interval[0]), float(interval[1]))
    return (
        all(isfinite(value) for value in values)
        and int(trade_count) >= 30
        and net_pnl > 0
        and profit_factor > 1
        and interval[0] > 0
    )
