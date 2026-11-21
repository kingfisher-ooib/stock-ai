from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import hashlib
import json

import pytest

from stock_ai.backtest.swing import SwingConfig, run_swing, summarize_swing, signal
from stock_ai.data.multi_etf import audit_dataset, history_at, load_dataset, lot_at


def dataset(n=85, symbols=('1475','1306','1321','1346','2558')):
    days=[]
    day=date(2024,1,1)
    while len(days)<n:
        if day.weekday()<5:
            days.append(day.isoformat())
        day+=timedelta(days=1)
    instruments={}
    for s in symbols:
        bars=[]
        for j,d in enumerate(days):
            p=100+j*.2
            bars.append(dict(bar_date=d,open=p,high=p+.5,low=p-.5,close=p+.1,
                             volume=10000,observed_at=d+'T08:00:00+00:00',source='synthetic fixture'))
        instruments[s]=dict(price_basis='raw',bars=bars,lots=[dict(date=days[0],size=10)],actions=[])
    return dict(synthetic=True,calendar=days,calendar_source='synthetic weekdays, not JPX',instruments=instruments)


def run(d, strategy='A',cfg=None):
    return run_swing(d,strategy=strategy,start=d['calendar'][60],end=d['calendar'][-1],config=cfg)


def test_next_session_execution_and_reproducibility():
    d=dataset()
    a=run(d)
    assert a==run(d)
    assert a['fills'][0]['date']==d['calendar'][61]
    assert all(p['cash']>=0 and p['positions']<=3 for p in a['curve'])
    assert all(t['quantity']%10==0 and t['holding_days']<=5 for t in a['trades'])
    assert len({f['symbol'] for f in a['fills'][:3]})==3


def test_cash_does_not_double_spend():
    d=dataset()
    a=run(d,cfg=SwingConfig(initial_cash=150,max_position_ratio=1,trade_risk_yen=100))
    assert not a['fills']  # one ten-unit lot costs more than all cash
    assert summarize_swing(a)['net_pnl_yen']==0


def test_costs_and_fixed_fees():
    d=dataset()
    a=run(d,cfg=SwingConfig(spread_bps=0,slippage_bps=0))
    b=run(d)
    assert b['total_cost']>0
    assert summarize_swing(a)['net_pnl_yen']>summarize_swing(b)['net_pnl_yen']
    assert not run(d,cfg=SwingConfig(fee_per_side=55))['fills']


def test_open_over_limit_expires_frozen_order():
    d=dataset(symbols=('1475',))
    bar=d['instruments']['1475']['bars'][61]
    for k in ('open','high','low','close'):
        bar[k]*=1.2
    a=run(d)
    assert not any(f['date']==d['calendar'][61] for f in a['fills'])


def test_same_day_future_close_cannot_change_entry_size():
    d=dataset(symbols=('1475',))
    a=run(d)['fills'][0]
    d['instruments']['1475']['bars'][61]['close']+=.2
    assert run(d)['fills'][0]==a


def test_gap_loss_exceeds_risk_and_stop_is_not_magic_fill():
    d=dataset(symbols=('1475',))
    for j in (62,63):
        bar=d['instruments']['1475']['bars'][j]
        for k in ('open','high','low','close'):
            bar[k]*=.6
    a=run(d)
    assert a['trades'][0]['exit_date']==d['calendar'][63]
    assert a['trades'][0]['net_pnl'] < -100
    assert summarize_swing(a)['risk_budget_exceedances']>=1


def test_intraday_low_alone_never_causes_guaranteed_stop_fill():
    d=dataset(symbols=('1475',))
    d['instruments']['1475']['bars'][62]['low']=1
    assert run(d)['trades'][0]['exit_date']!=d['calendar'][62]


@pytest.mark.parametrize('ratio',[2,.5])
def test_split_or_consolidation_preserves_wealth(ratio):
    d=dataset(symbols=('1475',))
    base=run(d,cfg=SwingConfig(spread_bps=0,slippage_bps=0))
    i=d['instruments']['1475']
    i['actions']=[dict(date=d['calendar'][63],kind='split',ratio=ratio,
                       known_at=d['calendar'][60]+'T00:00:00+00:00',source='synthetic')]
    for b in i['bars'][63:]:
        for k in ('open','high','low','close'):
            b[k]/=ratio
        b['volume']*=ratio
    i['lots'].append(dict(date=d['calendar'][63],size=1))
    a=run(d,cfg=SwingConfig(spread_bps=0,slippage_bps=0))
    assert a['curve'][3]['equity']==pytest.approx(base['curve'][3]['equity'])
    assert history_at(i,60)==history_at(dataset(symbols=('1475',))['instruments']['1475'],60)
    assert lot_at(i,d['calendar'][63])==1


def test_distribution_receivable_does_not_become_cash_early():
    d=dataset(symbols=('1475',))
    i=d['instruments']['1475']
    i['actions']=[dict(date=d['calendar'][63],kind='distribution',amount=2,
                       pay_date=d['calendar'][70],known_at=d['calendar'][60]+'T00:00:00+00:00',source='synthetic')]
    a=run(d)
    assert a['curve'][3]['cash']==a['curve'][2]['cash']
    assert a['trades'][0]['net_pnl'] > 0
    assert a['curve'][-1]['equity']-100000==pytest.approx(sum(t['net_pnl'] for t in a['trades']))


@pytest.mark.parametrize('bad',['missing','duplicate','nan','ohlc','volume','time','lot'])
def test_bad_data_rejected(bad):
    d=dataset()
    i=d['instruments']['1475']
    if bad=='missing': i['bars'].pop(5)
    if bad=='duplicate': i['bars'][5]=i['bars'][4]
    if bad=='nan': i['bars'][5]['close']=float('nan')
    if bad=='ohlc': i['bars'][5]['low']=999
    if bad=='volume': i['bars'][5]['volume']=-1
    if bad=='time': i['bars'][5]['observed_at']='2024-01-01'
    if bad=='lot': i['lots'][0]['size']=0
    with pytest.raises(ValueError): run(d)


def test_unqualified_real_data_refused():
    d=dataset()
    d['synthetic']=False
    d['availability_mode']='historical_assumption'
    with pytest.raises(ValueError,match='unqualified'): run(d)


def test_asof_and_hash_guards(tmp_path):
    p=tmp_path/'snapshot.json'
    p.write_text(json.dumps(dataset()))
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    assert load_dataset(p,sha256=sha,as_of='2026-11-21T00:00:00+00:00')
    with pytest.raises(ValueError,match='not yet observed'):
        load_dataset(p,sha256=sha,as_of='2024-01-01T00:00:00+00:00')
    with pytest.raises(ValueError,match='SHA'):
        load_dataset(p,sha256='0'*64,as_of='2026-11-21T00:00:00+00:00')


@pytest.mark.parametrize('change',[dict(max_positions=4),dict(max_holding_days=6),dict(spread_bps=-1),dict(trade_risk_yen=0)])
def test_invalid_configuration(change):
    with pytest.raises(ValueError): replace(SwingConfig(),**change)


def test_no_trade_metrics_are_undefined():
    a=run(dataset(),strategy='cash')
    m=summarize_swing(a)
    assert m['net_pnl_yen']==0 and m['trade_count']==0
    assert m['expectancy_yen'] is None and m['expectancy_95pct'] is None
    assert m['sharpe_annualized'] is None and m['profit_factor'] is None


def test_breakout_excludes_current_high_and_volume_from_reference():
    d=dataset(symbols=('1475',))
    bars=d['instruments']['1475']['bars']
    bars[-1].update(close=120,open=120,high=121,low=119,volume=20000)
    assert signal(bars,'C')[0]


def test_daily_portfolio_loss_forces_exit_and_blocks_buys():
    d=dataset(symbols=('1475',))
    b=d['instruments']['1475']['bars'][62]
    for k in ('open','high','low','close'):
        b[k]*=.6
    a=run(d,cfg=SwingConfig(max_daily_loss_ratio=.001))
    assert a['trades'][0]['reason']=='daily_loss'
    assert a['trades'][0]['exit_date']==d['calendar'][62]
    assert not any(f['date']==d['calendar'][62] for f in a['fills'])


def test_bootstrap_interval_is_reproducible_and_clusters_exit_dates():
    a=run(dataset(),strategy='cash')
    day=a['curve'][0]['date']
    a['trades']=[dict(net_pnl=1,exit_date=day,holding_days=1) for _ in range(30)]
    first=summarize_swing(a)
    assert first==summarize_swing(a)
    assert first['expectancy_95pct']==[1,1]


def test_real_observed_mode_prevents_retrospective_decisions():
    d=dataset(symbols=('1475',))
    d.update(synthetic=False,availability_mode='observed')
    i=d['instruments']['1475']
    keys=('ohlcv_verified','calendar_verified','lot_history_verified',
          'actions_complete','distributions_complete','execution_cost_verified')
    i['verification']={k:True for k in keys}
    i['verification_evidence']={k:'test evidence' for k in keys}
    for b in i['bars']:
        b['observed_at']='2026-11-21T08:00:00+00:00'
    with pytest.raises(ValueError,match='not yet observed'): run(d)


def test_incomplete_evaluation_period_is_rejected():
    d=dataset()
    with pytest.raises(ValueError,match='incomplete'):
        run_swing(d,strategy='A',start='2023-01-01',end=d['calendar'][-1])


def test_runner_preserves_existing_results_and_records_synthetic_flag(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    root=Path(__file__).resolve().parents[1]
    out=tmp_path/'synthetic.json'
    command=[sys.executable,str(root/'scripts/run_multi_etf_swing.py'),'--synthetic','--output',str(out)]
    env={**os.environ,'PYTHONPATH':str(root/'src')}
    subprocess.run(command,env=env,check=True,capture_output=True)
    original=out.read_bytes()
    result=json.loads(original)
    assert result['run_count']==150
    assert result['adopted_strategies']==[]
    assert all(r['simulation']['synthetic'] for r in result['results'])
    failed=subprocess.run(command,env=env,capture_output=True)
    assert failed.returncode!=0 and out.read_bytes()==original
    checked=json.loads((root/'data/results/multi-etf-swing-synthetic-2026-11-21.json').read_bytes())
    assert result==checked
