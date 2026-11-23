from dataclasses import replace
from decimal import Decimal as D

import pytest

from stock_ai.backtest.cash_v3 import BuyRequest, credit_sale
from stock_ai.backtest.entitlement_v3 import new_book
from stock_ai.backtest.positions_v3 import (
    apply_market_splits, attributed_trade, capture_portfolio_rights, execute_buy,
    execute_sell, freeze_portfolio_buys, mark_close, new_portfolio, plan_exit,
)
from test_swing_v3_schema import load, with_events


def setup(data=None):
    data=data or with_events();snapshot=load(data);days=data['sessions']
    state=new_portfolio(snapshot,as_of=days[59]+'T07:00:00Z')
    return snapshot,days,state


def buy(snapshot,days,state,*,stop=D('90'),quantity=3,limit=D('101'),fill=True):
    state=freeze_portfolio_buys(snapshot,state,decision_at=days[59]+'T07:00:00Z',
        target_session=days[60],requests=(BuyRequest('position-X','ETF-X',quantity,1,limit,D('0'),D('1')),))
    return execute_buy(snapshot,state,order_id='position-X',at=days[60]+'T00:00:00Z',stop=stop,fill=fill)


def split_and_plan(snapshot,days,state):
    state=mark_close(snapshot,state,session=days[60])
    rights=capture_portfolio_rights(snapshot,state,new_book(snapshot),ex_session=days[61])
    state=apply_market_splits(snapshot,state,session=days[61])
    state=mark_close(snapshot,state,session=days[61])
    state=plan_exit(snapshot,state,sell_id='exit-X',position_id='position-X',
        decision_at=days[61]+'T07:00:00Z',target_session=days[62],impact_bps=D('0'),fee=D('1'),reason='test-only')
    return state,rights


def test_cash_purchase_matches_owned_basis_and_split_preserves_total_basis():
    snapshot,days,original=setup();state=buy(snapshot,days,original)
    assert state.positions[0].total_cost_basis==301
    assert state.cash.purchase_debits==301 and state.cash.lots[0].amount==99699
    state=mark_close(snapshot,state,session=days[60])
    rights=capture_portfolio_rights(snapshot,state,new_book(snapshot),ex_session=days[61])
    changed=apply_market_splits(snapshot,state,session=days[61])
    assert changed.positions[0].quantity==30 and changed.positions[0].stop==9
    assert changed.positions[0].total_cost_basis==state.positions[0].total_cost_basis==301
    assert rights.rights[0].quantity==3 and rights.rights[0].unit_basis_id=='ETF-X-old'
    assert not original.positions and not changed.qualified_for_real_data
    with pytest.raises(ValueError,match='already processed'):
        apply_market_splits(snapshot,changed,session=days[61])


def test_sell_is_owned_and_sized_from_position_not_arbitrary_cash_credit():
    snapshot,days,state=setup();state=buy(snapshot,days,state)
    state,rights=split_and_plan(snapshot,days,state)
    result=execute_sell(snapshot,state,sell_id='exit-X',at=days[62]+'T00:00:00Z')
    assert not result.positions and result.trades[0].quantity==30
    assert result.trades[0].net_proceeds==299 and result.trades[0].price_pnl==-2
    assert result.cash.sale_credits==299 and result.cash.lots[0].amount+result.cash.lots[1].amount==99998
    report=attributed_trade(snapshot,rights,result.trades[0],as_of=days[64]+'T07:00:00Z')
    assert report['distribution_income']==24 and report['net_pnl']==22
    assert result.trades[0].price_pnl==-2  # No overwrite by final distribution.
    with pytest.raises(ValueError,match='no pending'):
        execute_sell(snapshot,result,sell_id='exit-X',at=days[62]+'T00:00:00Z')


def test_fabricated_sale_credit_is_detected_before_next_operation():
    snapshot,days,state=setup()
    cash=credit_sale(snapshot,state.cash,transaction_id='fake',net_amount=D('10'),
        at=days[60]+'T00:00:00Z',source='synthetic')
    with pytest.raises(ValueError,match='journal and cash'):
        mark_close(snapshot,replace(state,cash=cash),session=days[60])


def test_no_holding_or_no_prior_instruction_cannot_be_sold():
    snapshot,days,state=setup()
    with pytest.raises(ValueError,match='invalid or duplicate'):
        plan_exit(snapshot,state,sell_id='s',position_id='missing',
            decision_at=days[59]+'T07:00:00Z',target_session=days[60],
            impact_bps=D('0'),fee=D('1'),reason='test-only')
    with pytest.raises(ValueError,match='no pending'):
        execute_sell(snapshot,state,sell_id='missing',at=days[60]+'T00:00:00Z')


@pytest.mark.parametrize('fill,limit',[(False,D('101')),(True,D('99'))])
def test_unfilled_order_creates_neither_position_nor_purchase(fill,limit):
    snapshot,days,state=setup();result=buy(snapshot,days,state,fill=fill,limit=limit)
    assert not result.positions and not result.entries and result.cash.purchase_debits==0
    assert result.cash.reservations[0].status=='expired'


def test_gap_below_stop_is_not_retroactively_cancelled():
    snapshot,days,state=setup()
    result=buy(snapshot,days,state,stop=D('120'))
    assert result.positions[0].stop==120 and result.positions[0].quantity==3


def test_occupied_positions_cannot_be_hidden_from_cash_reservations():
    snapshot,days,state=setup();state=buy(snapshot,days,state)
    with pytest.raises(ValueError,match='duplicate symbol'):
        freeze_portfolio_buys(snapshot,state,decision_at=days[60]+'T07:00:00Z',
            target_session=days[61],requests=(BuyRequest('add','ETF-X',1,1,D('101'),D('0'),D('1')),))


def test_fractional_consolidation_stops_without_changing_cash_or_position():
    data=with_events();data['splits'][0]['ratio_new_per_old']='0.5'
    snapshot,days,state=setup(data);state=buy(snapshot,days,state)
    with pytest.raises(ValueError,match='fractional'):
        apply_market_splits(snapshot,state,session=days[61])
    assert state.positions[0].quantity==3 and state.cash.purchase_debits==301


def test_unsellable_new_lot_cannot_be_booked_as_proceeds():
    data=with_events();data['lots'].append(dict(data['lots'][0],
        effective_session=data['sessions'][62],size=100))
    snapshot,days,state=setup(data);state=buy(snapshot,days,state)
    state,_=split_and_plan(snapshot,days,state)
    with pytest.raises(ValueError,match='unsellable'):
        execute_sell(snapshot,state,sell_id='exit-X',at=days[62]+'T00:00:00Z')
    assert state.cash.sale_credits==0 and not state.trades


def test_split_processing_cannot_be_skipped_or_capture_after_split_units():
    snapshot,days,state=setup();state=buy(snapshot,days,state)
    with pytest.raises(ValueError,match='processed first'):
        mark_close(snapshot,state,session=days[61])
    state=mark_close(snapshot,state,session=days[60])
    state=apply_market_splits(snapshot,state,session=days[61])
    with pytest.raises(ValueError,match='prior-close'):
        capture_portfolio_rights(snapshot,state,new_book(snapshot),ex_session=days[61])


def test_new_buy_on_corporate_day_expires_without_using_wrong_unit():
    snapshot,days,state=setup()
    request=BuyRequest('late','ETF-X',1,1,D('101'),D('0'),D('1'))
    state=freeze_portfolio_buys(snapshot,state,decision_at=days[60]+'T07:00:00Z',
        target_session=days[61],requests=(request,))
    state=apply_market_splits(snapshot,state,session=days[61])
    result=execute_buy(snapshot,state,order_id='late',at=days[61]+'T00:00:00Z',stop=D('90'))
    assert not result.positions and result.cash.purchase_debits==0


def test_early_sell_and_early_trade_attribution_are_rejected():
    snapshot,days,state=setup();state=buy(snapshot,days,state)
    state,rights=split_and_plan(snapshot,days,state)
    with pytest.raises(ValueError):execute_sell(snapshot,state,sell_id='exit-X',at=days[61]+'T00:00:00Z')
    result=execute_sell(snapshot,state,sell_id='exit-X',at=days[62]+'T00:00:00Z')
    with pytest.raises(ValueError,match='predates exit'):
        attributed_trade(snapshot,rights,result.trades[0],as_of=days[61]+'T07:00:00Z')


def test_late_final_does_not_get_imputed_into_early_trade_income():
    data=with_events();data['amount_revisions']=data['amount_revisions'][1:]
    data['amount_revisions'][0]['supersedes_revision_id']=None
    snapshot,days,state=setup(data);state=buy(snapshot,days,state)
    state,rights=split_and_plan(snapshot,days,state)
    state=execute_sell(snapshot,state,sell_id='exit-X',at=days[62]+'T00:00:00Z')
    early=attributed_trade(snapshot,rights,state.trades[0],as_of=days[62]+'T07:00:00Z',mode='decision')
    assert early['distribution_income'] is None and early['net_pnl'] is None
    assert attributed_trade(snapshot,rights,state.trades[0],as_of=days[64]+'T07:00:00Z')['net_pnl']==22


def test_integer_consolidation_preserves_basis_and_market_value_identity():
    data=with_events();data['splits'][0]['ratio_new_per_old']='0.5'
    for bar in data['bars']:
        if bar['symbol']=='ETF-X' and bar['session_date']>=data['sessions'][61]:
            bar.update(open='200',high='204',low='198',close='202')
    snapshot,days,state=setup(data);state=buy(snapshot,days,state,quantity=4)
    changed=apply_market_splits(snapshot,state,session=days[61])
    assert changed.positions[0].quantity==2 and changed.positions[0].stop==180
    assert changed.positions[0].total_cost_basis==state.positions[0].total_cost_basis==401
    assert state.positions[0].quantity*100==changed.positions[0].quantity*200


def test_gap_loss_above_risk_budget_is_recorded_not_removed():
    data=with_events()
    for bar in data['bars']:
        if bar['symbol']=='ETF-X' and bar['session_date']==data['sessions'][62]:
            bar.update(open='1',high='1.02',low='0.99',close='1.01')
    snapshot,days,state=setup(data);state=buy(snapshot,days,state)
    state,_=split_and_plan(snapshot,days,state)
    result=execute_sell(snapshot,state,sell_id='exit-X',at=days[62]+'T00:00:00Z')
    assert result.trades[0].price_pnl==-272 and result.trades[0].price_pnl < -100
    assert result.cash.sale_credits==29


def test_impacted_prices_and_fees_enter_cost_basis_and_proceeds_once():
    snapshot,days,state=setup()
    state=freeze_portfolio_buys(snapshot,state,decision_at=days[59]+'T07:00:00Z',
        target_session=days[60],requests=(BuyRequest('position-X','ETF-X',3,1,D('101'),D('5'),D('1')),))
    state=execute_buy(snapshot,state,order_id='position-X',at=days[60]+'T00:00:00Z',stop=D('90'))
    assert state.positions[0].total_cost_basis==D('301.15')
    state=apply_market_splits(snapshot,state,session=days[61])
    state=mark_close(snapshot,state,session=days[61])
    state=plan_exit(snapshot,state,sell_id='exit-X',position_id='position-X',
        decision_at=days[61]+'T07:00:00Z',target_session=days[62],impact_bps=D('10'),fee=D('1'),reason='test-only')
    state=execute_sell(snapshot,state,sell_id='exit-X',at=days[62]+'T00:00:00Z')
    assert state.trades[0].net_proceeds==D('298.7')
    assert state.trades[0].price_pnl==D('-2.45')


def test_repeat_buy_cannot_create_position_without_another_cash_debit():
    snapshot,days,state=setup();state=buy(snapshot,days,state)
    with pytest.raises(ValueError,match='already processed'):
        execute_buy(snapshot,state,order_id='position-X',at=days[60]+'T00:00:00Z',stop=D('90'))
    assert len(state.entries)==1 and state.cash.purchase_debits==301


def test_unknown_split_unit_definition_cannot_change_owned_quantity():
    data=with_events();data['unit_bases'][-1]['available_at']=data['sessions'][63]+'T07:00:00Z'
    snapshot,days,state=setup(data);state=buy(snapshot,days,state)
    with pytest.raises(ValueError,match='target unit basis not yet known'):
        apply_market_splits(snapshot,state,session=days[61])
    assert state.positions[0].quantity==3


def test_unknown_entry_unit_definition_cannot_create_position():
    data=with_events();data['unit_bases'][0]['available_at']=data['sessions'][63]+'T07:00:00Z'
    snapshot,days,state=setup(data)
    with pytest.raises(ValueError,match='buy unit basis not yet known'):
        buy(snapshot,days,state)
    assert not state.positions and state.cash.purchase_debits==0
