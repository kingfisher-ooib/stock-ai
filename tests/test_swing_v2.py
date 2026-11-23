from copy import deepcopy

import pytest

from stock_ai.backtest.swing import SwingConfig, summarize_swing
from stock_ai.backtest.swing_v2 import buy_limit, run_swing_v2
from stock_ai.data.synthetic import synthetic_dataset


def run(data, strategy='A', config=None):
    return run_swing_v2(data, strategy=strategy, start=data['calendar'][60],
                        end=data['calendar'][-1], config=config)


def shock(data, index, factor):
    for bar in data['instruments']['1475']['bars'][index:]:
        for key in ('open', 'high', 'low', 'close'):
            bar[key] *= factor


@pytest.mark.parametrize('strategy', ['cash', 'hold', 'A', 'B', 'C'])
def test_real_data_cannot_be_enabled_with_verification_flags(strategy):
    data = synthetic_dataset(symbols=('1475',))
    data.update(synthetic=False, availability_mode='historical_assumption')
    with pytest.raises(ValueError, match='synthetic-only'):
        run(data, strategy)


def test_downward_gap_entry_is_not_cancelled_and_loss_is_counted():
    data = synthetic_dataset(symbols=('1475',))
    shock(data, 61, .5)
    shock(data, 62, .5)  # Loss occurs after entry, not merely from the pre-entry gap.
    result = run(data)
    first = result['fills'][0]
    order = result['orders'][0]
    assert first['date'] == data['calendar'][61]
    assert first['price'] < order['stop']
    assert result['trades'][0]['exit_date'] == data['calendar'][62]
    assert result['trades'][0]['net_pnl'] < -100
    assert summarize_swing(result)['risk_budget_exceedances'] >= 1


def test_daily_loss_uses_close_and_exits_at_next_open():
    data = synthetic_dataset(symbols=('1475',))
    shock(data, 62, .5)
    result = run(data, config=SwingConfig(max_position_ratio=.5, trade_risk_yen=10000))
    assert result['trades'][0]['reason'] == 'daily_loss_prior_close'
    assert result['trades'][0]['exit_date'] == data['calendar'][63]
    assert result['curve'][2]['positions'] == 1


@pytest.mark.parametrize('strategy', ['A', 'B', 'C'])
def test_orders_use_prior_data_and_three_slots_are_reserved(strategy, monkeypatch):
    # Force a signal only to exercise common execution for all three strategies.
    monkeypatch.setattr('stock_ai.backtest.swing_v2.signal',
                        lambda h, s: (True, h[-1]['close']-1, h[-1]['close']-2))
    data = synthetic_dataset()
    original = deepcopy(data)
    result = run(data, strategy)
    assert len([o for o in result['orders'] if o['created_date'] == data['calendar'][60]]) == 3
    assert all(f['order_date'] < f['date'] and f['price'] <= f['limit'] for f in result['fills'])
    assert all(p['cash'] >= 0 and p['positions'] <= 3 for p in result['curve'])
    assert data == original


def test_buy_hold_quantity_is_frozen_before_initial_open():
    data = synthetic_dataset(symbols=('1475',))
    baseline = run(data, 'hold')
    shock(data, 60, .5)
    changed = run(data, 'hold')
    assert changed['fills'][0]['quantity'] == baseline['fills'][0]['quantity']
    assert changed['fills'][0]['order_date'] == data['calendar'][59]
    assert len(changed['trades']) == 1 and changed['trades'][0]['reason'] == 'period_end'


def test_above_limit_after_cost_does_not_fill():
    data = synthetic_dataset(symbols=('1475',))
    limit = run(data)['orders'][0]['limit']
    bar = data['instruments']['1475']['bars'][61]
    bar.update(open=limit, high=limit+1, close=limit, low=limit-1)
    result = run(data)
    assert not any(f['date'] == data['calendar'][61] for f in result['fills'])
    assert any(r['date'] == data['calendar'][61] for r in result['rejections'])


@pytest.mark.parametrize('tick', [0, -1, float('nan')])
def test_invalid_tick_rejected(tick):
    with pytest.raises(ValueError, match='tick'):
        buy_limit(100, tick)


def test_limit_is_rounded_down_not_above_requested_cap():
    assert buy_limit(100.05, .1) == 101.0


@pytest.mark.parametrize('config', [SwingConfig(initial_cash=150), SwingConfig(fee_per_side=55)])
def test_unaffordable_or_cost_over_risk_orders_never_create_profit(config):
    result = run(synthetic_dataset(), config=config)
    assert result['fills'] == []
    assert summarize_swing(result)['net_pnl_yen'] == 0


def test_same_day_sale_cash_is_not_reserved_for_new_orders():
    data = synthetic_dataset(symbols=('1475','1306'))
    result = run(data, config=SwingConfig(initial_cash=5000, max_position_ratio=1, max_positions=1))
    for trade in result['trades']:
        assert not any(f['date'] == trade['exit_date'] for f in result['fills'])


@pytest.mark.parametrize('action', ['split', 'lot'])
def test_pending_order_expires_on_corporate_or_lot_change(action):
    data = synthetic_dataset(symbols=('1475',))
    i = data['instruments']['1475']
    if action == 'split':
        i['actions'].append(dict(kind='split', date=data['calendar'][61], ratio=2,
                                 source='synthetic', known_at=data['calendar'][59]+'T00:00:00+00:00'))
        shock(data, 61, .5)
    else:
        i['lots'].append(dict(date=data['calendar'][61], size=5))
    assert not any(f['date'] == data['calendar'][61] for f in run(data)['fills'])


@pytest.mark.parametrize('ratio', [2, .5])
def test_split_preserves_assets_and_end_pnl(ratio):
    data = synthetic_dataset(symbols=('1475',))
    config = SwingConfig(spread_bps=0, slippage_bps=0)
    base = run(data, 'hold', config)
    i = data['instruments']['1475']
    i['actions'] = [dict(kind='split', date=data['calendar'][63], ratio=ratio,
                         source='synthetic', known_at=data['calendar'][59]+'T00:00:00+00:00')]
    shock(data, 63, 1/ratio)
    i['lots'].append(dict(date=data['calendar'][63], size=1))
    changed = run(data, 'hold', config)
    assert changed['curve'][-1]['equity'] == pytest.approx(base['curve'][-1]['equity'])
    assert changed['trades'][0]['net_pnl'] == pytest.approx(base['trades'][0]['net_pnl'])


def test_distribution_receivable_and_payment_are_not_double_counted():
    data = synthetic_dataset(symbols=('1475',))
    i = data['instruments']['1475']
    i['actions'] = [dict(kind='distribution', date=data['calendar'][63], amount=2,
                         pay_date=data['calendar'][70], source='synthetic',
                         known_at=data['calendar'][59]+'T00:00:00+00:00')]
    result = run(data, 'hold')
    assert result['curve'][3]['cash'] == result['curve'][2]['cash']
    assert result['curve'][10]['cash'] > result['curve'][9]['cash']
    assert result['curve'][-1]['equity']-100000 == pytest.approx(sum(t['net_pnl'] for t in result['trades']))


def test_reproducible_no_mutation_and_holding_period_limit():
    data = synthetic_dataset()
    original = deepcopy(data)
    first = run(data)
    assert first == run(data) and data == original
    assert all(t['holding_days'] <= 5 for t in first['trades'])


def test_missing_bar_and_missing_prior_session_rejected():
    data = synthetic_dataset()
    data['instruments']['1475']['bars'].pop()
    with pytest.raises(ValueError, match='missing'):
        run(data)
    data = synthetic_dataset()
    with pytest.raises(ValueError, match='prior session'):
        run_swing_v2(data, strategy='hold', start=data['calendar'][0], end=data['calendar'][-1])


def test_fractional_split_and_unsellable_lot_raise_instead_of_booking_profit():
    data = synthetic_dataset(symbols=('1475',))
    data['instruments']['1475']['lots'].append(dict(date=data['calendar'][63], size=1000))
    with pytest.raises(ValueError, match='cannot be sold'):
        run(data, 'hold')
    data = synthetic_dataset(symbols=('1475',))
    data['instruments']['1475']['actions'] = [dict(
        kind='split', date=data['calendar'][63], ratio=.123,
        source='synthetic', known_at=data['calendar'][59]+'T00:00:00+00:00')]
    with pytest.raises(ValueError, match='fractional'):
        run(data, 'hold')


def test_v2_runner_is_bounded_and_preserves_existing_output(tmp_path):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    output = tmp_path/'v2.json'
    command = [sys.executable, str(root/'scripts/run_multi_etf_swing_v2.py'),
               '--synthetic', '--output', str(output)]
    env = {**os.environ, 'PYTHONPATH': str(root/'src')}
    subprocess.run(command, env=env, capture_output=True, check=True)
    original = output.read_bytes()
    report = json.loads(original)
    assert report['run_count'] == 30 and report['adopted_strategies'] == []
    assert report['qualified_for_real_data'] is False
    assert all(r['simulation']['synthetic'] for r in report['results'])
    assert report['artifact_sha256']['config/swing_v2.yaml']
    failed = subprocess.run(command, env=env, capture_output=True)
    assert failed.returncode != 0 and output.read_bytes() == original
    second = tmp_path/'second.json'
    subprocess.run(command[:-1]+[str(second)], env=env, capture_output=True, check=True)
    assert second.read_bytes() == original


def test_v2_runner_has_no_real_input_option(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    output = tmp_path/'forbidden.json'
    result = subprocess.run([sys.executable, str(root/'scripts/run_multi_etf_swing_v2.py'),
                             '--input', 'not-a-market-source', '--output', str(output)],
                            env={**os.environ, 'PYTHONPATH': str(root/'src')}, capture_output=True)
    assert result.returncode != 0 and not output.exists()
