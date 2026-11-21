import pytest

from stock_ai.backtest.screening import passes_candidate_gate


def qualifying_metrics():
    return {
        "trade_count": 30,
        "net_pnl_yen": 1.0,
        "profit_factor": 1.01,
        "expectancy_block_bootstrap_95pct_yen": [0.01, 2.0],
    }


def test_candidate_gate_requires_every_registered_condition():
    assert passes_candidate_gate(qualifying_metrics())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trade_count", 29),
        ("net_pnl_yen", 0.0),
        ("profit_factor", 1.0),
        ("expectancy_block_bootstrap_95pct_yen", [0.0, 2.0]),
        ("profit_factor", None),
        ("expectancy_block_bootstrap_95pct_yen", None),
    ],
)
def test_candidate_gate_rejects_failed_or_undefined_condition(field, value):
    metrics = qualifying_metrics()
    metrics[field] = value
    assert not passes_candidate_gate(metrics)


def test_candidate_gate_rejects_missing_metrics():
    assert not passes_candidate_gate({})
