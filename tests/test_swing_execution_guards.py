"""All prices are generated fixtures; verification labels model audit preconditions."""
import pytest

from stock_ai.backtest.swing import SwingConfig, run_swing
from stock_ai.data.synthetic import synthetic_dataset


def observed_fixture():
    data = synthetic_dataset(symbols=('1475',))
    data.update(synthetic=False, availability_mode='observed')
    keys = ('ohlcv_verified', 'calendar_verified', 'lot_history_verified',
            'actions_complete', 'distributions_complete', 'execution_cost_verified')
    instrument = data['instruments']['1475']
    instrument['verification'] = {k: True for k in keys}
    instrument['verification_evidence'] = {k: 'synthetic test-only evidence' for k in keys}
    return data


def simulate(data, strategy='A'):
    return run_swing(data, strategy=strategy, start=data['calendar'][60], end=data['calendar'][-1])


@pytest.mark.parametrize('strategy', ['cash', 'hold', 'A', 'B', 'C'])
@pytest.mark.parametrize('index', [60, 84])
def test_all_strategies_reject_late_observations_including_final_session(strategy, index):
    data = observed_fixture()
    data['instruments']['1475']['bars'][index]['observed_at'] = '2026-11-21T08:00:00+00:00'
    with pytest.raises(ValueError, match='not yet observed'):
        simulate(data, strategy)


@pytest.mark.parametrize('strategy', ['A', 'B', 'C'])
def test_feature_warmup_cannot_contain_retrospectively_observed_bars(strategy):
    data = observed_fixture()
    data['instruments']['1475']['bars'][0]['observed_at'] = '2026-11-21T08:00:00+00:00'
    with pytest.raises(ValueError, match='not yet observed'):
        simulate(data, strategy)


@pytest.mark.parametrize('new_lot', [1, 5])
def test_frozen_order_expires_on_lot_change_even_when_quantity_is_divisible(new_lot):
    data = synthetic_dataset(symbols=('1475',))
    baseline = simulate(data)
    first = baseline['fills'][0]
    assert first['date'] == data['calendar'][61]
    assert first['quantity'] % new_lot == 0
    data['instruments']['1475']['lots'].append(dict(date=data['calendar'][61], size=new_lot))
    result = simulate(data)
    assert not any(f['date'] == data['calendar'][61] for f in result['fills'])
    assert any(r['date'] == data['calendar'][61] for r in result['rejections'])


@pytest.mark.parametrize('strategy', ['cash', 'hold'])
def test_timely_observed_fixture_still_runs(strategy):
    assert simulate(observed_fixture(), strategy)['strategy'] == strategy


def test_explicit_historical_assumption_is_not_observed_mode():
    data = observed_fixture()
    data['availability_mode'] = 'historical_assumption'
    for bar in data['instruments']['1475']['bars']:
        bar['observed_at'] = '2026-11-21T08:00:00+00:00'
    with pytest.raises(ValueError, match='legacy swing execution'):
        simulate(data)


def test_buy_hold_initial_quantity_uses_current_lot_not_a_prior_day_order():
    data = synthetic_dataset(symbols=('1475',))
    data['instruments']['1475']['lots'].append(dict(date=data['calendar'][60], size=5))
    first = simulate(data, 'hold')['fills'][0]
    assert first['date'] == data['calendar'][60] and first['quantity'] % 5 == 0


def test_warmup_correction_known_before_first_use_is_allowed():
    data = observed_fixture()
    data['instruments']['1475']['bars'][0]['observed_at'] = data['calendar'][60]+'T08:00:00+00:00'
    with pytest.raises(ValueError, match='legacy swing execution'):
        simulate(data)


def test_observations_after_evaluation_end_are_not_used():
    data = observed_fixture()
    data['instruments']['1475']['bars'][-1]['observed_at'] = '2026-11-21T08:00:00+00:00'
    result = run_swing(data, strategy='hold', start=data['calendar'][60], end=data['calendar'][-2])
    assert result['curve'][-1]['date'] == data['calendar'][-2]


@pytest.mark.parametrize('strategy', ['A', 'B', 'C'])
@pytest.mark.parametrize('availability', ['observed', 'historical_assumption'])
def test_legacy_execution_cannot_produce_real_pnl_even_with_verification_flags(strategy, availability):
    data = observed_fixture()
    data['availability_mode'] = availability
    with pytest.raises(ValueError, match='legacy swing execution'):
        simulate(data, strategy)


def test_registered_real_comparison_saves_exclusions_without_any_pnl(tmp_path):
    import hashlib
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys

    data = observed_fixture()  # Generated prices only; not real market evidence.
    source = tmp_path / 'input.json'
    source.write_text(json.dumps(data))
    output = tmp_path / 'report.json'
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, str(root / 'scripts/run_multi_etf_swing.py'),
               '--input', str(source), '--sha256', hashlib.sha256(source.read_bytes()).hexdigest(),
               '--as-of', '2026-11-22T00:00:00+00:00', '--output', str(output)]
    env = {**os.environ, 'PYTHONPATH': str(root / 'src')}
    subprocess.run(command, env=env, check=True, capture_output=True)
    report = json.loads(output.read_text())
    assert report['status'] == 'NO_ADOPTED_STRATEGY_EXECUTION_MODEL_BLOCKED'
    assert report['run_count'] == 0 and report['results'] == []
    assert report['adopted_strategies'] == []
    assert all(len(report['execution_exclusions'][s]) == 2 for s in ('A', 'B', 'C'))
    assert source.read_text() == json.dumps(data)
    original = output.read_bytes()
    retry = subprocess.run(command, env=env, capture_output=True)
    assert retry.returncode != 0 and output.read_bytes() == original


def test_unchanged_lot_metadata_does_not_cancel_order():
    data = synthetic_dataset(symbols=('1475',))
    expected = simulate(data)['fills'][0]
    data['instruments']['1475']['lots'].append(dict(date=data['calendar'][61], size=10))
    assert simulate(data)['fills'][0] == expected


def test_unexecutable_existing_position_cannot_be_booked_as_a_sale():
    data = synthetic_dataset(symbols=('1475',))
    data['instruments']['1475']['lots'].append(dict(date=data['calendar'][63], size=1000))
    with pytest.raises(ValueError, match='position cannot be sold in current lot'):
        simulate(data)


@pytest.mark.parametrize('strategy', ['hold', 'A'])
def test_daily_loss_exit_respects_buy_hold_baseline_definition(strategy):
    data = synthetic_dataset(symbols=('1475',))
    # A large, lasting gap triggers the portfolio daily stop after either entry.
    # Larger sizing here is a synthetic stress fixture, not research configuration.
    for bar in data['instruments']['1475']['bars'][62:]:
        for key in ('open', 'high', 'low', 'close'):
            bar[key] *= .5
    result = run_swing(
        data, strategy=strategy, start=data['calendar'][60], end=data['calendar'][-1],
        config=SwingConfig(max_position_ratio=.5, trade_risk_yen=10000),
    )
    assert result['fills']
    if strategy == 'hold':
        assert len(result['trades']) == 1
        assert result['trades'][0]['reason'] == 'period_end'
        assert result['trades'][0]['exit_date'] == data['calendar'][-1]
        assert all(p['positions'] == 1 for p in result['curve'][:-1])
    else:
        assert result['trades'][0]['reason'] == 'daily_loss'
        assert result['trades'][0]['exit_date'] == data['calendar'][62]
