"""Unsupported concurrent actions must stop before any strategy or PnL work."""
from copy import deepcopy

import pytest

from stock_ai.backtest.swing_v2 import run_swing_v2
from stock_ai.data.synthetic import synthetic_dataset


@pytest.mark.parametrize('symbol', ['1475', '2558'])
@pytest.mark.parametrize('distribution_first', [False, True])
@pytest.mark.parametrize('strategy', ['hold', 'A'])
def test_split_and_distribution_collision_never_books_income(
        symbol, distribution_first, strategy, monkeypatch):
    # All dates, amounts and prices in this fixture are synthetic. This models
    # the structural collision, not either ETF's historical return.
    data = synthetic_dataset(symbols=(symbol,))
    day = data['calendar'][63]
    known_at = data['calendar'][59] + 'T00:00:00+00:00'
    actions = [
        dict(kind='split', date=day, ratio=10,
             source='synthetic', known_at=known_at),
        dict(kind='distribution', date=day, amount=7,
             pay_date=data['calendar'][70],
             source='synthetic', known_at=known_at),
    ]
    data['instruments'][symbol]['actions'] = (
        list(reversed(actions)) if distribution_first else actions)
    original = deepcopy(data)

    def no_strategy_work(*args, **kwargs):
        pytest.fail('strategy work started before rejecting unsupported actions')

    monkeypatch.setattr('stock_ai.backtest.swing_v2.signal', no_strategy_work)
    monkeypatch.setattr('stock_ai.backtest.swing_v2.buy_limit', no_strategy_work)
    with pytest.raises(ValueError, match='multiple same-day actions'):
        run_swing_v2(data, strategy=strategy,
                     start=data['calendar'][60], end=data['calendar'][-1])
    assert data == original
