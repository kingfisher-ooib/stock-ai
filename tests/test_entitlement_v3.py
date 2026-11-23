from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from stock_ai.backtest.entitlement_v3 import (
    Holding, capture_rights, decision_history_sha256, new_book,
    record_decision, value_rights,
)
from test_swing_v3_schema import load, with_events


def setup(data=None, quantity=3):
    data = data or with_events()
    snapshot = load(data)
    days = data['sessions']
    holding = Holding('position-X', 'ETF-X', quantity, 'ETF-X-old', days[60])
    return data, snapshot, days, holding


def capture(snapshot, days, holding):
    return capture_rights(snapshot, new_book(snapshot), ex_session=days[61],
                          holdings=(holding,))


def test_prior_units_survive_same_day_split_and_late_final_without_rewriting_history():
    data, snapshot, days, holding = setup()
    book = capture(snapshot, days, holding)
    assert book.rights[0].quantity == 3 and book.rights[0].unit_basis_id == 'ETF-X-old'
    early = days[61]+'T07:00:00Z'
    book = record_decision(snapshot, book, decision_at=early)
    assert book.decisions[-1].total == Decimal('21')
    old_hash = decision_history_sha256(book)
    old_frame = book.decisions[0]
    report = value_rights(snapshot, book, as_of=days[64]+'T07:00:00Z', mode='restated')
    assert report.total == Decimal('24') and report.mode == 'restated'
    assert decision_history_sha256(book) == old_hash
    updated = record_decision(snapshot, book, decision_at=days[64]+'T07:00:00Z')
    assert updated.decisions[0] is old_frame and updated.decisions[-1].total == Decimal('24')
    assert updated.changes[-1].delta == Decimal('3')
    assert book.decisions[-1].total == Decimal('21') and not updated.qualified_for_real_data
    with pytest.raises(FrozenInstanceError):
        book.rights[0].quantity = 30


def test_sale_after_ex_does_not_erase_right_or_reassign_to_new_position():
    _, snapshot, days, holding = setup()
    book = capture(snapshot, days, holding)
    # No current holdings are used in valuation: sale and later re-entry are
    # external to I2, with no fabricated price or proceeds.
    report = value_rights(snapshot, book, as_of=days[64]+'T07:00:00Z', mode='restated')
    assert report.lines[0].position_id == 'position-X' and report.total == Decimal('24')


@pytest.mark.parametrize('zero_holding', [False, True])
def test_zero_or_no_holding_does_not_get_later_distribution(zero_holding):
    _, snapshot, days, holding = setup(quantity=0)
    book = capture_rights(snapshot, new_book(snapshot), ex_session=days[61],
                          holdings=(holding,) if zero_holding else ())
    assert not book.rights and book.captured_events == ('div',)
    assert value_rights(snapshot, book, as_of=days[64]+'T07:00:00Z', mode='restated').total == 0
    with pytest.raises(ValueError):
        capture_rights(snapshot, book, ex_session=days[61], holdings=(replace(holding,quantity=3),))


def test_unknown_decision_value_is_not_zero_and_comparison_cannot_resume():
    data = with_events(); data['amount_revisions'] = data['amount_revisions'][1:]
    data['amount_revisions'][0]['supersedes_revision_id'] = None
    _, snapshot, days, holding = setup(data)
    book = capture(snapshot, days, holding)
    halted = record_decision(snapshot, book, decision_at=days[61]+'T07:00:00Z')
    frame = halted.decisions[-1]
    assert frame.total is None and frame.lines[0].amount is None
    assert frame.status == 'HALT_UNRESOLVED_VALUATION'
    assert value_rights(snapshot, halted, as_of=days[64]+'T07:00:00Z',mode='restated').total == 24
    with pytest.raises(ValueError,match='halted comparison'):
        record_decision(snapshot, halted, decision_at=days[64]+'T07:00:00Z')


def test_estimate_alone_is_not_a_final_restatement():
    _, snapshot, days, holding = setup()
    book = capture(snapshot, days, holding)
    report = value_rights(snapshot, book, as_of=days[61]+'T07:00:00Z', mode='restated')
    assert report.total is None and report.status == 'INCOMPLETE_FINAL_AMOUNTS'


@pytest.mark.parametrize('basis,amount,units', [
    ('ETF-X-old','7',1), ('ETF-X-new','0.7',1), ('ETF-X-new','7',10),
])
def test_quote_units_and_split_conversion_conserve_total(basis, amount, units):
    data = with_events()
    data['amount_revisions'][0].update(quote_unit_basis_id=basis,
                                       quoted_amount=amount,quoted_units=units)
    _, snapshot, days, holding = setup(data)
    book = capture(snapshot,days,holding)
    assert value_rights(snapshot,book,as_of=days[61]+'T07:00:00Z',mode='decision').total == 21


def test_unit_conversion_does_not_use_future_known_split():
    data=with_events()
    data['amount_revisions'][0]['quote_unit_basis_id']='ETF-X-new'
    data['splits'][0]['available_at']=data['sessions'][63]+'T07:00:00Z'
    _, snapshot, days, holding=setup(data)
    frame=value_rights(snapshot,capture(snapshot,days,holding),
                       as_of=days[61]+'T07:00:00Z',mode='decision')
    assert frame.total is None and frame.status=='HALT_UNRESOLVED_VALUATION'


def test_correction_is_append_only_and_preserves_old_final():
    data=with_events();final=data['amount_revisions'][1]
    data['amount_revisions'].append(dict(final, revision_id='correction',
        supersedes_revision_id='final',quoted_amount='6',status='correction',
        available_at=data['sessions'][66]+'T07:00:00Z'))
    _, snapshot, days, holding=setup(data)
    book=record_decision(snapshot,capture(snapshot,days,holding),decision_at=days[64]+'T07:00:00Z')
    updated=record_decision(snapshot,book,decision_at=days[66]+'T07:00:00Z')
    assert updated.decisions[0].total==24 and updated.decisions[1].total==18
    assert updated.changes[-1].delta==-6
    assert updated.changes[-1].old_revision_id=='final'


def test_fractional_monetary_conversion_requires_explicit_rounding_policy():
    data=with_events();data['amount_revisions'][0].update(quoted_amount='1',quoted_units=7)
    _,snapshot,days,holding=setup(data)
    with pytest.raises(ValueError,match='rounding policy'):
        value_rights(snapshot,capture(snapshot,days,holding),as_of=days[61]+'T07:00:00Z',mode='decision')


def test_large_amount_is_not_truncated_by_default_decimal_precision():
    data=with_events();amount='99999999999999999999999999999999'
    data['amount_revisions'][0]['quoted_amount']=amount
    _,snapshot,days,holding=setup(data)
    report=value_rights(snapshot,capture(snapshot,days,holding),as_of=days[61]+'T07:00:00Z',mode='decision')
    assert report.total==Decimal(str(int(amount)*3))


@pytest.mark.parametrize('changes', [
    {'quantity':True}, {'quantity':-1}, {'unit_basis_id':'ETF-X-new'},
    {'unit_basis_id':'ETF-Y-old'}, {'as_of_session':'2025-01-01'},
    {'symbol':'unknown'}, {'position_id':''},
])
def test_invalid_holdings_cannot_create_rights(changes):
    _,snapshot,days,holding=setup()
    with pytest.raises(ValueError):capture(snapshot,days,replace(holding,**changes))


def test_duplicate_holdings_and_missing_elapsed_capture_are_rejected():
    _,snapshot,days,holding=setup()
    book=new_book(snapshot)
    with pytest.raises(ValueError,match='duplicate'):
        capture_rights(snapshot,book,ex_session=days[61],holdings=(holding,holding))
    with pytest.raises(ValueError,match='snapshot missing'):
        value_rights(snapshot,book,as_of=days[61]+'T07:00:00Z',mode='decision')
    with pytest.raises(ValueError):capture_rights(snapshot,book,ex_session=days[60],holdings=())


def test_late_schedule_is_not_treated_as_prior_known_entitlement():
    data=with_events();late=data['sessions'][61]+'T07:00:00Z'
    data['entitlements'][0]['available_at']=late
    data['amount_revisions'][0]['available_at']=late
    _,snapshot,days,holding=setup(data)
    with pytest.raises(ValueError,match='schedule not known'):capture(snapshot,days,holding)


def test_bound_snapshot_and_strict_decision_chronology():
    data,snapshot,days,holding=setup();book=capture(snapshot,days,holding)
    timestamp=days[61]+'T07:00:00Z'
    book=record_decision(snapshot,book,decision_at=timestamp)
    data['amount_revisions'][1]['quoted_amount']='999'
    with pytest.raises(ValueError,match='different snapshot'):
        value_rights(load(data),book,as_of=timestamp,mode='restated')
    with pytest.raises(ValueError,match='strictly'):
        record_decision(snapshot,book,decision_at=timestamp)
    with pytest.raises(ValueError,match='predates'):
        value_rights(snapshot,book,as_of=days[60]+'T07:00:00Z',mode='decision')


def test_multiple_symbols_keep_separate_rights_and_totals():
    data=with_events();days=data['sessions']
    event=dict(data['entitlements'][0],event_id='div-Y',symbol='ETF-Y',
               quote_unit_basis_id='ETF-Y-old')
    data['entitlements'].append(event)
    data['amount_revisions'].append(dict(data['amount_revisions'][0],
        revision_id='amount-Y',event_id='div-Y',quoted_amount='11',
        quote_unit_basis_id='ETF-Y-old',status='final'))
    _,snapshot,days,holding=setup(data)
    book=capture_rights(snapshot,new_book(snapshot),ex_session=days[61],holdings=(
        holding,Holding('position-Y','ETF-Y',5,'ETF-Y-old',days[60])))
    early=value_rights(snapshot,book,as_of=days[61]+'T07:00:00Z',mode='decision')
    later=value_rights(snapshot,book,as_of=days[64]+'T07:00:00Z',mode='restated')
    assert early.total==76 and later.total==79
    assert {l.position_id:l.amount for l in later.lines}=={
        'position-X':Decimal('24'),'position-Y':Decimal('55')}


def test_later_entitlement_after_split_converts_back_to_old_quoted_units():
    data=with_events();days=data['sessions']
    data['entitlements'].append(dict(data['entitlements'][0],event_id='later',
        last_cum_session=days[64],ex_session=days[65],distribution_record_date=days[66]))
    data['amount_revisions'].append(dict(data['amount_revisions'][0],
        revision_id='later-amount',event_id='later',status='final'))
    snapshot=load(data)
    book=capture_rights(snapshot,new_book(snapshot),ex_session=days[61],holdings=())
    holding=Holding('later-position','ETF-X',30,'ETF-X-new',days[64])
    book=capture_rights(snapshot,book,ex_session=days[65],holdings=(holding,))
    result=value_rights(snapshot,book,as_of=days[65]+'T07:00:00Z',mode='decision')
    assert result.total==21
    with pytest.raises(ValueError,match='prior entitlement snapshots missing'):
        capture_rights(snapshot,new_book(snapshot),ex_session=days[65],holdings=(holding,))


def test_documented_zero_amount_is_distinct_from_unknown():
    data=with_events();data['amount_revisions'][0]['quoted_amount']='0'
    _,snapshot,days,holding=setup(data)
    result=value_rights(snapshot,capture(snapshot,days,holding),
                        as_of=days[61]+'T07:00:00Z',mode='decision')
    assert result.total==0 and result.status=='COMPLETE'


def test_quote_basis_not_yet_known_is_unresolved_even_with_known_ratio():
    data=with_events()
    data['unit_bases'][-1]['available_at']=data['sessions'][63]+'T07:00:00Z'
    data['amount_revisions'][0]['quote_unit_basis_id']='ETF-X-new'
    _,snapshot,days,holding=setup(data)
    result=value_rights(snapshot,capture(snapshot,days,holding),
                        as_of=days[61]+'T07:00:00Z',mode='decision')
    assert result.total is None and result.status=='HALT_UNRESOLVED_VALUATION'
