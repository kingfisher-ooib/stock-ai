from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from datetime import date, timedelta

import pytest

from stock_ai.backtest.evaluation_v3 import AccountingError, evaluate_v3, expectancy_interval
from stock_ai.backtest.swing import SwingConfig
from stock_ai.backtest.swing_v3 import run_swing_v3
from test_swing_v3 import active, run
from test_swing_v3_schema import AS_OF, BLOB, fixture, load, with_events


@pytest.mark.parametrize('strategy',['cash','hold','A','B','C'])
def test_all_methods_reconcile_and_never_establish_market_edge(strategy):
    data=with_events();result=run(data,strategy=strategy)
    report=evaluate_v3(load(data),result,as_of=AS_OF)
    assert report['reconciliation']=='passed' and report['metrics'] is not None
    assert not report['adopted'] and not report['statistical_edge_confirmed']
    assert not report['qualified_for_real_data']
    assert report['metrics']['net_pnl_yen']==result['restated_curve'][-1]['equity']-100000


def test_no_trade_and_short_period_metrics_have_reasons_not_infinities():
    report=evaluate_v3(load(fixture()),run(strategy='cash'),as_of=AS_OF)
    metrics=report['metrics'];reasons=report['unavailable_reasons']
    assert metrics['net_pnl_yen']==0 and metrics['trade_count']==0
    for key in ['expectancy_yen','profit_factor','annual_return','sharpe_annualized','average_win','average_loss']:
        assert metrics[key] is None and key in reasons
    assert metrics['expectancy_95pct'] is None and not report['statistical_edge_confirmed']


def test_costs_and_distribution_are_reconciled_once():
    data=with_events();result=run(data,strategy='hold')
    report=evaluate_v3(load(data),result,as_of=AS_OF)
    m=report['metrics']
    assert m['fee_cost_yen']==0 and m['impact_cost_yen']>0
    assert m['total_cost_yen']==m['fee_cost_yen']+m['impact_cost_yen']
    assert sum(report['trade_net_pnl'].values())==m['net_pnl_yen']


def test_actual_trade_metrics_and_gaps_use_complete_transactions(active):
    result=run();report=evaluate_v3(load(fixture()),result,as_of=AS_OF)
    assert report['metrics']['trade_count']==len(result['portfolio'].trades)>0
    assert report['metrics']['max_drawdown_basis']=='decision'
    assert report['metrics']['expectancy_95pct'] is None
    assert report['unavailable_reasons']['expectancy_95pct']=='fewer_than_30_trades'


def test_stopped_run_has_no_partial_performance_metrics():
    data=with_events();data['amount_revisions']=data['amount_revisions'][1:]
    data['amount_revisions'][0]['supersedes_revision_id']=None
    result=run(data,strategy='hold');report=evaluate_v3(load(data),result,as_of=AS_OF)
    assert report['status']=='NOT_EVALUATED' and report['metrics'] is None


@pytest.mark.parametrize('mutation',['daily_cash','daily_exposure','daily_equity','restated_equity',
    'missing_session','trade_pnl','trade_quantity','trade_holding','paid_amount'])
def test_corrupted_accounting_cannot_be_reported_as_success(mutation):
    data=with_events();result=deepcopy(run(data,strategy='hold'))
    if mutation=='daily_cash':result['curve'][0]['cash']+=D('1')
    elif mutation=='daily_exposure':result['curve'][0]['exposure']+=D('1')
    elif mutation=='daily_equity':result['curve'][0]['equity']+=D('1')
    elif mutation=='restated_equity':result['restated_curve'][0]['equity']+=D('1')
    elif mutation=='missing_session':result['curve']=result['curve'][1:]
    else:
        state=result['portfolio']
        if mutation=='paid_amount':
            cash=replace(state.cash,distribution_credits=D('1'))
            result['portfolio']=replace(state,cash=cash)
        else:
            trade=state.trades[0]
            if mutation=='trade_pnl':trade=replace(trade,price_pnl=trade.price_pnl+D('1'))
            elif mutation=='trade_quantity':trade=replace(trade,quantity=trade.quantity+1)
            else:trade=replace(trade,holding_sessions=trade.holding_sessions+1)
            result['portfolio']=replace(state,trades=(trade,)+state.trades[1:])
    with pytest.raises(ValueError):evaluate_v3(load(data),result,as_of=AS_OF)


def test_expectancy_interval_preserves_same_day_grouping_and_seed():
    sessions=tuple(f'2025-01-{i:02d}' for i in range(1,21))
    trades=tuple((sessions[i%20],D('3')) for i in range(40))
    a=expectancy_interval(trades,sessions);b=expectancy_interval(trades,sessions)
    assert a==b and a['interval']==[3.,3.] and a['resamples']==1000
    clustered=tuple((sessions[0],D('3')) for _ in range(40))
    c=expectancy_interval(clustered,sessions)
    assert c['interval']==[3.,3.] and 0<c['resamples']<=1000


def test_ci_requires_sufficient_trades_and_sessions_and_valid_trade_dates():
    sessions=('2025-01-01',)
    assert expectancy_interval([(sessions[0],D('1'))],sessions)['reason']=='fewer_than_30_trades'
    assert expectancy_interval([(sessions[0],D('1'))]*30,sessions)['reason']=='fewer_than_10_sessions'
    with pytest.raises(ValueError):expectancy_interval([('unknown',D('1'))],sessions)


def test_real_result_flag_cannot_be_evaluated_as_synthetic():
    result=run(strategy='cash');result['qualified_for_real_data']=True
    with pytest.raises(AccountingError):evaluate_v3(load(fixture()),result,as_of=AS_OF)


def long_fixture(length):
    data=fixture();current=date.fromisoformat(data['sessions'][0]);sessions=[]
    while len(sessions)<length:
        if current.weekday()<5:sessions.append(current.isoformat())
        current+=timedelta(days=1)
    templates={s:next(b for b in data['bars'] if b['symbol']==s) for s in data['symbols']}
    data.update(sessions=sessions,evaluation_end_session=sessions[-1])
    data['bars']=[dict(templates[s],session_date=d,available_at=d+'T07:00:00Z') for s in data['symbols'] for d in sessions]
    for rule in data['execution_rules']:rule['end_session']=sessions[-1]
    return data


def test_more_than_30_actual_synthetic_trades_get_ci_without_adoption(active):
    data=long_fixture(140);snapshot=load(data)
    result=run_swing_v3(snapshot,as_of=AS_OF,source_blobs={'s':BLOB},strategy='A',
                        priority=snapshot.symbols,config=SwingConfig(max_holding_days=1))
    report=evaluate_v3(snapshot,result,as_of=AS_OF)
    assert report['metrics']['trade_count']>=30 and report['metrics']['expectancy_95pct'] is not None
    assert not report['statistical_edge_confirmed'] and not report['adopted']


def test_annual_return_branch_with_long_synthetic_cash_period():
    data=long_fixture(320);as_of='2027-01-01T00:00:00Z';snapshot=load(data,as_of=as_of)
    result=run_swing_v3(snapshot,as_of=as_of,source_blobs={'s':BLOB},strategy='cash',priority=snapshot.symbols)
    report=evaluate_v3(snapshot,result,as_of=as_of)
    assert len(result['curve'])==260 and report['metrics']['annual_return']==0


def test_account_receipt_does_not_double_count_income_in_metrics():
    data=with_events();base=run(data,strategy='hold')
    expected=evaluate_v3(load(data),base,as_of=AS_OF)['metrics']['net_pnl_yen']
    quantity=base['rights'].rights[0].quantity
    data['cash_evidence'][0].update(status='explicit_research_assumption',amount=str(quantity*8),
        cash_available_at=data['sessions'][68]+'T00:00:00Z')
    result=run(data,strategy='hold');report=evaluate_v3(load(data),result,as_of=AS_OF)
    assert report['metrics']['net_pnl_yen']==expected
    assert result['curve'][-1]['receivable']==0 and result['portfolio'].cash.payments


def test_fee_component_counts_both_sides_exactly_once():
    data=fixture()
    for rule in data['execution_rules']:rule['fee_per_side']='1'
    result=run(data,strategy='hold',config=SwingConfig(fee_per_side=1))
    report=evaluate_v3(load(data),result,as_of=AS_OF)
    assert report['metrics']['fee_cost_yen']==4
    assert report['metrics']['trade_count']==2


def test_decision_and_restated_risk_statistics_are_kept_separate():
    data=with_events();result=run(data,strategy='hold')
    report=evaluate_v3(load(data),result,as_of=AS_OF)
    assert report['metrics']['max_drawdown_basis']=='decision'
    assert report['metrics']['sharpe_annualized']!=report['metrics']['sharpe_restated']
    assert 'max_drawdown_restated' in report['metrics']
