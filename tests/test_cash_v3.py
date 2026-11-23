from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D

import pytest

from stock_ai.backtest.cash_v3 import (
    BuyRequest, available_cash, cash_balance, credit_sale, freeze_buys,
    new_cash_book, outstanding_receivable, receive_distributions, settle_buy,
)
from stock_ai.backtest.entitlement_v3 import Holding, capture_rights, new_book
from test_swing_v3_schema import load, with_events


def setup(data=None):
    data=data or with_events();snapshot=load(data);days=data['sessions']
    book=new_cash_book(snapshot,as_of=days[60]+'T07:00:00Z',initial_cash=D('100'))
    return snapshot,days,book


def request(order_id='o1',symbol='ETF-X',**changes):
    return replace(BuyRequest(order_id,symbol,1,1,D('40'),D('0'),D('1')),**changes)


def freeze(snapshot,days,book,requests=None,occupied=()):
    return freeze_buys(snapshot,book,decision_at=days[60]+'T07:00:00Z',
        target_session=days[61],requests=(request(),) if requests is None else requests,
        occupied_symbols=occupied)


def rights(snapshot,days):
    return capture_rights(snapshot,new_book(snapshot),ex_session=days[61],
        holdings=(Holding('position-X','ETF-X',3,'ETF-X-old',days[60]),))


def payment_data():
    data=with_events();data['cash_evidence'][0].update(status='explicit_research_assumption',
        amount='24',cash_available_at=data['sessions'][68]+'T00:00:00Z')
    return data


def test_reservation_is_cash_subset_and_fill_does_not_double_charge_fee():
    snapshot,days,original=setup();book=freeze(snapshot,days,original)
    assert cash_balance(snapshot,book,as_of=book.as_of)==100
    assert available_cash(snapshot,book,as_of=book.as_of)==59
    result=settle_buy(snapshot,book,order_id='o1',at=days[61]+'T00:00:00Z',fill_price=D('39'))
    assert cash_balance(snapshot,result,as_of=result.as_of)==60
    assert result.purchase_debits==40 and original.lots[0].amount==100
    assert result.reservations[0].status=='filled' and not result.qualified_for_real_data


def test_two_orders_cannot_spend_same_cash_and_failure_is_atomic():
    snapshot,days,book=setup()
    with pytest.raises(ValueError,match='insufficient'):
        freeze(snapshot,days,book,(request(limit=D('60')),request('o2','ETF-Y',limit=D('60'))))
    assert book.reservations==() and book.lots[0].amount==100


def test_expiry_release_is_not_reallocated_at_same_open_or_paid_twice():
    snapshot,days,book=setup();book=freeze(snapshot,days,book)
    result=settle_buy(snapshot,book,order_id='o1',at=days[61]+'T00:00:00Z')
    assert available_cash(snapshot,result,as_of=result.as_of)==100
    with pytest.raises(ValueError,match='already settled'):
        settle_buy(snapshot,result,order_id='o1',at=result.as_of)
    with pytest.raises(ValueError,match='backwards'):
        freeze(snapshot,days,result)
    with pytest.raises(ValueError,match='prior-close'):
        freeze_buys(snapshot,result,decision_at=result.as_of,target_session=days[62],requests=(request('o2'),))
    next_book=freeze_buys(snapshot,result,decision_at=days[61]+'T07:00:00Z',
                          target_session=days[62],requests=(request('o2'),))
    assert next_book.reservations[-1].status=='pending'


def test_timezone_spelling_cannot_create_second_decision_batch():
    snapshot,days,book=setup();book=freeze(snapshot,days,book,())
    with pytest.raises(ValueError,match='already frozen'):
        freeze_buys(snapshot,book,decision_at=days[60]+'T07:00:00+00:00',
                     target_session=days[61],requests=(request(),))


def test_occupied_symbol_blocks_buy_even_if_sale_is_expected():
    snapshot,days,book=setup()
    with pytest.raises(ValueError,match='slot'):
        freeze(snapshot,days,book,occupied=('ETF-X',))


def test_pending_order_cannot_be_skipped_to_next_decision():
    snapshot,days,book=setup();book=freeze(snapshot,days,book)
    with pytest.raises(ValueError,match='elapsed order'):
        freeze_buys(snapshot,book,decision_at=days[61]+'T07:00:00Z',
                     target_session=days[62],requests=())


def test_sale_cash_not_usable_until_next_session_close_and_not_backdated():
    snapshot,days,book=setup();book=freeze(snapshot,days,book)
    at=days[61]+'T00:00:00Z'
    result=credit_sale(snapshot,book,transaction_id='sale1',net_amount=D('50'),at=at,source='synthetic')
    assert cash_balance(snapshot,result,as_of=at)==150
    assert available_cash(snapshot,result,as_of=days[61]+'T07:00:00Z')==59
    assert available_cash(snapshot,result,as_of=days[62]+'T07:00:00Z')==109
    with pytest.raises(ValueError,match='duplicate'):
        credit_sale(snapshot,result,transaction_id='sale1',net_amount=D('50'),at=at,source='synthetic')
    with pytest.raises(ValueError,match='backwards'):freeze(snapshot,days,result)


def test_receipt_transfers_gross_entitlement_to_cash_once():
    snapshot,days,book=setup(payment_data());r=rights(snapshot,days)
    before=days[67]+'T07:00:00Z';at=days[68]+'T00:00:00Z'
    assert outstanding_receivable(snapshot,r,book,as_of=before)==24
    book=receive_distributions(snapshot,r,book,as_of=before)
    assert cash_balance(snapshot,book,as_of=before)==100
    book=receive_distributions(snapshot,r,book,as_of=at)
    assert cash_balance(snapshot,book,as_of=at)==124
    assert outstanding_receivable(snapshot,r,book,as_of=at)==0
    again=receive_distributions(snapshot,r,book,as_of=at)
    assert again==book and len(again.payments)==1
    assert book.distribution_credits==24


def test_schedule_only_never_becomes_usable_cash():
    snapshot,days,book=setup();r=rights(snapshot,days)
    at=days[69]+'T07:00:00Z'
    result=receive_distributions(snapshot,r,book,as_of=at)
    assert cash_balance(snapshot,result,as_of=at)==100
    assert outstanding_receivable(snapshot,r,result,as_of=at)==24


def test_per_unit_quote_is_not_account_receipt():
    data=payment_data();data['cash_evidence'][0]['amount']='8'
    snapshot,days,book=setup(data);r=rights(snapshot,days)
    with pytest.raises(ValueError,match='account receipt differs'):
        receive_distributions(snapshot,r,book,as_of=days[68]+'T07:00:00Z')
    assert not book.payments and book.distribution_credits==0


def test_same_day_distribution_does_not_increase_frozen_order_or_reservation():
    snapshot,days,book=setup(payment_data());r=rights(snapshot,days)
    book=freeze_buys(snapshot,book,decision_at=days[67]+'T07:00:00Z',
                     target_session=days[68],requests=(request(),))
    frozen=book.reservations
    book=receive_distributions(snapshot,r,book,as_of=days[68]+'T00:00:00Z')
    assert book.reservations==frozen and book.reservations[0].allocations==( ('initial',D('41')), )
    result=settle_buy(snapshot,book,order_id='o1',at=book.as_of,fill_price=D('40'))
    assert result.lots[0].amount==59 and result.lots[1].amount==24


def test_unknown_final_cannot_be_paid_and_unknown_value_is_not_zero():
    data=payment_data();data['amount_revisions']=data['amount_revisions'][:1]
    snapshot,days,book=setup(data);r=rights(snapshot,days)
    assert outstanding_receivable(snapshot,r,book,as_of=days[61]+'T07:00:00Z',mode='restated') is None
    with pytest.raises(ValueError,match='final entitlement unknown'):
        receive_distributions(snapshot,r,book,as_of=days[68]+'T07:00:00Z')


def test_downward_correction_after_payment_halts_without_fabricating_repayment():
    data=payment_data();data['amount_revisions'].append(dict(data['amount_revisions'][1],
        revision_id='corrected',supersedes_revision_id='final',status='correction',
        quoted_amount='7',available_at=data['sessions'][69]+'T07:00:00Z'))
    snapshot,days,book=setup(data);r=rights(snapshot,days)
    book=receive_distributions(snapshot,r,book,as_of=days[68]+'T00:00:00Z')
    with pytest.raises(ValueError,match='repayment unsupported'):
        outstanding_receivable(snapshot,r,book,as_of=days[69]+'T07:00:00Z')
    assert book.distribution_credits==24


@pytest.mark.parametrize('changes',[{'quantity':True},{'quantity':0},{'lot_size':True},
    {'quantity':3,'lot_size':2},{'limit':D('0')},{'fee':D('-1')},
    {'impact_bps':D('NaN')},{'limit':40.0},{'symbol':'unknown'},{'order_id':''}])
def test_invalid_reservations_rejected(changes):
    snapshot,days,book=setup()
    with pytest.raises(ValueError):freeze(snapshot,days,book,(request(**changes),))


@pytest.mark.parametrize('price',[D('41'),D('-1'),D('NaN'),40.0])
def test_infeasible_fill_never_debits_cash(price):
    snapshot,days,book=setup();book=freeze(snapshot,days,book)
    with pytest.raises(ValueError):
        settle_buy(snapshot,book,order_id='o1',at=days[61]+'T00:00:00Z',fill_price=price)
    assert book.purchase_debits==0 and book.reservations[0].status=='pending'


def test_actual_fill_and_expiry_are_reproducible_with_no_mutation():
    snapshot,days,book=setup();book=freeze(snapshot,days,book,(request(),request('o2','ETF-Y')))
    before=deepcopy(book);at=days[61]+'T00:00:00Z'
    a=settle_buy(snapshot,book,order_id='o1',at=at,fill_price=D('40'))
    a=settle_buy(snapshot,a,order_id='o2',at=at)
    b=settle_buy(snapshot,book,order_id='o2',at=at)
    b=settle_buy(snapshot,b,order_id='o1',at=at,fill_price=D('40'))
    assert a==b and book==before


def test_three_slot_limit_and_occupied_positions_count():
    data=with_events()
    for symbol in ['ETF-Z','ETF-W']:
        data['symbols'].append(symbol)
        data['unit_bases'].append(dict(data['unit_bases'][1],symbol=symbol,basis_id=symbol+'-old'))
        data['lots'].append(dict(data['lots'][1],symbol=symbol))
        data['execution_rules'].append(dict(data['execution_rules'][1],symbol=symbol))
        data['bars'].extend(dict(b,symbol=symbol,unit_basis_id=symbol+'-old')
            for b in list(data['bars']) if b['symbol']=='ETF-Y')
    snapshot,days,book=setup(data)
    with pytest.raises(ValueError,match='three position slots'):
        freeze(snapshot,days,book,(request('o1','ETF-Z'),request('o2','ETF-W')),
               occupied=('ETF-X','ETF-Y'))
    allowed=freeze(snapshot,days,book,(request('o1','ETF-Z'),),occupied=('ETF-X','ETF-Y'))
    assert len(allowed.reservations)==1


def test_corrupt_cash_and_real_sale_source_are_rejected():
    snapshot,days,book=setup()
    corrupt=replace(book,lots=(replace(book.lots[0],amount=D('101')),))
    with pytest.raises(ValueError,match='reconciliation'):cash_balance(snapshot,corrupt,as_of=book.as_of)
    with pytest.raises(ValueError):
        credit_sale(snapshot,book,transaction_id='s',net_amount=D('10'),at=days[61]+'T00:00:00Z',source='real')


def test_request_cannot_replace_actual_lot_size_with_smaller_unit():
    data=with_events();data['lots'][0]['size']=10
    snapshot,days,book=setup(data)
    with pytest.raises(ValueError,match='lot rule'):
        freeze(snapshot,days,book)


def test_insufficient_funds_cannot_be_repaired_by_same_day_sale():
    snapshot,days,book=setup()
    with pytest.raises(ValueError,match='insufficient'):
        freeze(snapshot,days,book,(request(limit=D('100')),))
    result=credit_sale(snapshot,book,transaction_id='s',net_amount=D('50'),
                       at=days[61]+'T00:00:00Z',source='synthetic')
    with pytest.raises(ValueError,match='backwards'):
        freeze(snapshot,days,result,(request(limit=D('100')),))


@pytest.mark.parametrize('amount',[D('0'),D('-1'),D('NaN'),100.0])
def test_invalid_initial_cash_rejected(amount):
    snapshot,days,_=setup()
    with pytest.raises(ValueError):
        new_cash_book(snapshot,as_of=days[60]+'T07:00:00Z',initial_cash=amount)
