from dataclasses import replace
from decimal import Decimal as D

import pytest

from stock_ai.backtest.swing import SwingConfig
from stock_ai.backtest.swing_v3 import run_swing_v3
from stock_ai.backtest.terminal_v3 import TerminalPolicy, execute_final_open, liquidate_terminal
from stock_ai.backtest.positions_v3 import new_portfolio
from test_swing_v3_schema import AS_OF, BLOB, fixture, load, with_events


def run(data=None,strategy='A',config=None,priority=None):
    snapshot=load(data or fixture())
    return run_swing_v3(snapshot,as_of=AS_OF,source_blobs={'s':BLOB},strategy=strategy,
                        priority=priority or snapshot.symbols,config=config)


@pytest.fixture
def active(monkeypatch):
    monkeypatch.setattr('stock_ai.backtest.swing_v3.signal',
        lambda h,s:(True,h[-1]['close']-1,h[-1]['close']-2))


@pytest.mark.parametrize('strategy',['cash','hold','A','B','C'])
def test_all_methods_complete_synthetic_with_no_remaining_positions(strategy):
    result=run(strategy=strategy)
    assert result['status']=='COMPLETED_SYNTHETIC' and result['complete']
    assert not result['portfolio'].positions and not result['qualified_for_real_data']
    assert len(result['curve'])==10 and len(result['restated_curve'])==10
    if strategy=='cash':assert all(p['equity']==100000 for p in result['curve'])


def test_same_day_split_rights_and_terminal_sale_preserve_prior_units():
    result=run(with_events(),strategy='hold')
    assert result['complete']
    rights=[r for r in result['rights'].rights if r.symbol=='ETF-X']
    entry=next(p for p in result['portfolio'].entries if p.symbol=='ETF-X')
    trade=next(t for t in result['portfolio'].trades if t.symbol=='ETF-X')
    assert rights[0].quantity==entry.quantity and trade.quantity==entry.quantity*10
    assert entry.total_cost_basis==trade.total_cost_basis
    assert trade.reason=='period_end' and trade.decision_at==result['terminal_policy']['registered_at']
    ex=with_events()['sessions'][61]
    order=[stage for day,stage in result['stages'] if day==ex]
    assert order[:5]==['rights_before_split','market_splits','cash_before_frozen_fills','prior_close_sells','frozen_buys']


def test_late_final_restatement_does_not_rewrite_orders_or_decision_curve():
    data=with_events();base=run(data,strategy='hold')
    data['amount_revisions'][1]['quoted_amount']='9'
    changed=run(data,strategy='hold')
    assert base['portfolio'].cash.reservations==changed['portfolio'].cash.reservations
    day=data['sessions'][61]
    a=next(p for p in base['curve'] if p['session']==day)
    b=next(p for p in changed['curve'] if p['session']==day)
    assert a==b
    ra=next(p for p in base['restated_curve'] if p['session']==day)
    rb=next(p for p in changed['restated_curve'] if p['session']==day)
    assert ra['equity']!=rb['equity']


def test_unknown_opening_entitlement_halts_before_sell_or_buy():
    data=with_events();data['amount_revisions']=data['amount_revisions'][1:]
    data['amount_revisions'][0]['supersedes_revision_id']=None
    result=run(data,strategy='hold')
    assert result['status']=='HALT_UNRESOLVED_VALUATION'
    assert not result['complete'] and result['restated_curve'] is None
    assert len(result['curve'])==1 and not result['portfolio'].trades


def test_missing_final_amount_cannot_produce_complete_restatement():
    data=with_events();data['amount_revisions']=data['amount_revisions'][:1]
    result=run(data,strategy='hold')
    assert result['status']=='HALT_INCOMPLETE_FINAL_AMOUNTS'
    assert not result['complete'] and result['restated_curve'] is None


def test_downward_gap_entry_is_not_cancelled_and_loss_exceeds_100(active):
    data=fixture();days=data['sessions']
    for bar in data['bars']:
        if bar['symbol']=='ETF-X' and bar['session_date']>=days[61]:
            factor=D('0.5') if bar['session_date']==days[61] else D('0.25')
            for k in ('open','high','low','close'):bar[k]=str(D(bar[k])*factor)
    result=run(data)
    entry=next(p for p in result['portfolio'].entries if p.symbol=='ETF-X')
    trade=next(t for t in result['portfolio'].trades if t.position_id==entry.position_id)
    assert entry.entry_session==days[61] and trade.exit_session==days[62]
    assert trade.price_pnl < -100


def test_daily_loss_at_close_sells_at_following_open(active):
    data=fixture();days=data['sessions']
    for bar in data['bars']:
        if bar['session_date']>=days[62]:
            for k in ('open','high','low','close'):bar[k]=str(D(bar[k])*D('0.5'))
    result=run(data)
    forced=[t for t in result['portfolio'].trades if t.reason=='daily_loss_prior_close']
    assert forced and all(t.exit_session==days[63] for t in forced)
    assert all(t.decision_at==days[62]+'T07:00:00Z' for t in forced)


def test_max_holding_and_no_same_day_fills(active):
    result=run();data=fixture();days=data['sessions']
    for r in result['portfolio'].cash.reservations:
        assert r.decision_at[:10] < r.target_session
    for t in result['portfolio'].trades:
        if t.reason!='period_end':assert t.holding_sessions<=5
    assert all(p['cash']>=0 and p['positions']<=3 for p in result['curve'])


def test_frozen_risk_quantity_respects_cash_allocation_and_risk_budget(active):
    result=run()
    for reservation in result['portfolio'].cash.reservations:
        r=reservation.request;stop=D('100')
        entry=r.limit*(1+r.impact_bps/10000)
        unit_risk=entry-stop*(1-r.impact_bps/10000)
        assert r.quantity*unit_risk+2*r.fee<=D('100')
        assert sum(a for _,a in reservation.allocations)<=D('6000')


def test_insufficient_minimum_lot_is_rejected_not_a_profitable_trade(active):
    data=fixture()
    for lot in data['lots']:lot['size']=10000
    result=run(data)
    assert not result['portfolio'].entries and not result['portfolio'].trades
    assert any(r['reason']=='minimum_lot_or_budget' for r in result['rejections'])


def test_terminal_closes_position_entered_on_last_day_under_prior_policy(active):
    result=run(config=SwingConfig(max_holding_days=1))
    end=fixture()['sessions'][-1]
    terminal=[t for t in result['portfolio'].trades if t.reason=='period_end']
    assert terminal and all(t.exit_session==end for t in terminal)
    assert not result['portfolio'].positions


def test_synthetic_cost_contract_mismatch_is_not_silently_overridden():
    with pytest.raises(ValueError,match='cost assumptions disagree'):
        run(config=SwingConfig(fee_per_side=55))


def test_unverified_real_input_and_missing_source_bytes_are_rejected():
    snapshot=load(fixture())
    for invalid in [snapshot.model_copy(update={'synthetic':False}),{}]:
        with pytest.raises(ValueError):
            run_swing_v3(invalid,as_of=AS_OF,source_blobs={'s':BLOB},strategy='cash',priority=snapshot.symbols)
    with pytest.raises(ValueError,match='source SHA'):
        run_swing_v3(snapshot,as_of=AS_OF,source_blobs={},strategy='cash',priority=snapshot.symbols)


def test_period_end_policy_cannot_be_registered_after_start():
    snapshot=load(fixture());days=snapshot.sessions
    state=new_portfolio(snapshot,as_of=days[59]+'T07:00:00Z')
    policy=TerminalPolicy(days[-1],days[60]+'T07:00:00Z',D('5'),D('0'))
    with pytest.raises(ValueError,match='predeclared'):
        liquidate_terminal(snapshot,state,policy)


def test_reproducibility_and_original_snapshot_unchanged(active):
    snapshot=load(fixture());original=snapshot.model_dump_json()
    kwargs=dict(as_of=AS_OF,source_blobs={'s':BLOB},strategy='A',priority=snapshot.symbols)
    assert run_swing_v3(snapshot,**kwargs)==run_swing_v3(snapshot,**kwargs)
    assert snapshot.model_dump_json()==original


def test_actual_account_receipt_transfers_receivable_without_changing_equity():
    data=with_events();baseline=run(data,strategy='hold')
    quantity=baseline['rights'].rights[0].quantity
    data['cash_evidence'][0].update(status='explicit_research_assumption',amount=str(quantity*8),
        cash_available_at=data['sessions'][68]+'T00:00:00Z')
    received=run(data,strategy='hold')
    assert [p['equity'] for p in received['curve']]==[p['equity'] for p in baseline['curve']]
    assert received['portfolio'].cash.distribution_credits==quantity*8
    assert received['curve'][-1]['receivable']==0


def test_post_period_downward_revision_is_checked_per_right_not_net_total():
    data=with_events();base=run(data,strategy='hold');quantity=base['rights'].rights[0].quantity
    data['cash_evidence'][0].update(status='explicit_research_assumption',amount=str(quantity*8),
        cash_available_at=data['sessions'][68]+'T00:00:00Z')
    data['entitlements'].append(dict(data['entitlements'][0],event_id='div-Y',symbol='ETF-Y',quote_unit_basis_id='ETF-Y-old'))
    for r in list(data['amount_revisions']):
        data['amount_revisions'].append(dict(r,event_id='div-Y',revision_id=r['revision_id']+'-Y',
            supersedes_revision_id=None if r['supersedes_revision_id'] is None else r['supersedes_revision_id']+'-Y',
            quote_unit_basis_id='ETF-Y-old'))
    data['amount_revisions'].append(dict(data['amount_revisions'][1],revision_id='late-correction',
        supersedes_revision_id='final',status='correction',quoted_amount='7',available_at='2025-04-14T07:00:00Z'))
    result=run(data,strategy='hold')
    assert result['status']=='HALT_REPAYMENT_UNSUPPORTED' and not result['complete']


def test_final_day_prior_close_sale_is_handled_before_terminal_close(active):
    data=fixture();days=data['sessions']
    for bar in data['bars']:
        if bar['session_date']==days[-2]:
            for k in ('open','high','low','close'):bar[k]=str(D(bar[k])*D('0.5'))
    result=run(data)
    sales=[t for t in result['portfolio'].trades if t.exit_session==days[-1] and t.reason=='daily_loss_prior_close']
    assert sales and result['complete']
    lots=[l for l in result['portfolio'].cash.lots if l.origin=='final_open_valuation_only']
    assert lots and all(l.usable_at==days[-1]+'T07:00:00Z' for l in lots)


@pytest.mark.parametrize('strategy',['A','C'])
def test_existing_technical_signals_drive_rising_synthetic_data(strategy):
    data=fixture();days=data['sessions']
    for bar in data['bars']:
        i=days.index(bar['session_date']);base=D('100')*D('1.003')**i
        bar.update(open=str(base),high=str(base+D('0.1')),low=str(base-D('0.1')),
                   close=str(base+D('0.05')),volume=2**i)
    result=run(data,strategy=strategy)
    assert result['complete'] and result['portfolio'].entries
    assert result['portfolio'].trades


def test_final_open_cannot_bypass_policy_registration_cutoff():
    snapshot=load(fixture());days=snapshot.sessions
    state=new_portfolio(snapshot,as_of=days[59]+'T07:00:00Z')
    policy=TerminalPolicy(days[-1],days[60]+'T07:00:00Z',D('5'),D('0'))
    with pytest.raises(ValueError,match='predeclared'):
        execute_final_open(snapshot,state,sell_id='unknown',policy=policy)
