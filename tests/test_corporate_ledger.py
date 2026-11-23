from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D

import pytest

from stock_ai.backtest.corporate_ledger import (
    CorporateState, Distribution, Receivable, Split, apply_corporate_actions,
)


DAYS = ('2025-01-06', '2025-01-07', '2025-01-08', '2025-01-09',
        '2025-01-10', '2025-01-14')
KNOWN = '2025-01-06T07:00:00+00:00'


def snapshot():
    return CorporateState(DAYS[0], (('ETF-X', 3), ('ETF-Y', 2)), D('100'))


def split(**changes):
    return replace(Split('split-X', 'ETF-X', DAYS[1], DAYS[3], D('10'),
                         KNOWN, 'synthetic'), **changes)


def dividend(**changes):
    return replace(Distribution('div-X', 'ETF-X', DAYS[0], DAYS[1], DAYS[0],
                               D('7'), DAYS[3], KNOWN, 'synthetic'), **changes)


def step(state=None, **kwargs):
    return apply_corporate_actions(state or snapshot(), sessions=DAYS,
                                   next_session=DAYS[1], **kwargs)


def test_same_day_split_uses_prior_units_and_payment_only_transfers_asset():
    original = snapshot()
    result = step(original, splits=[split()], distributions=[dividend()])
    state = result.state
    assert state.positions == (('ETF-X', 30), ('ETF-Y', 2))
    assert state.cash == D('100') and state.receivables[0].amount == D('21')
    assert result.prior_order_cash == D('100')
    assert result.distribution_credits[0].amount == D('21')
    assert not result.qualified_for_real_data
    for day in DAYS[2:4]:
        state = apply_corporate_actions(state, sessions=DAYS, next_session=day).state
        assert state.cash + sum(r.amount for r in state.receivables) == D('121')
    assert state.cash == D('121') and state.receivables == ()
    later = apply_corporate_actions(state, sessions=DAYS, next_session=DAYS[4]).state
    assert later.cash == D('121')  # No duplicate payment.
    assert original == snapshot()
    with pytest.raises(FrozenInstanceError):
        original.cash = D('0')


def test_receivable_survives_removal_of_position_after_ex_date():
    state = step(distributions=[dividend()]).state
    # External position removal stands in for an independently verified sale;
    # no price, sale proceeds or trading profit are fabricated here.
    state = replace(state, positions=())
    for day in DAYS[2:4]:
        state = apply_corporate_actions(state, sessions=DAYS, next_session=day).state
    assert state.cash == D('121') and not state.receivables


def test_no_prior_holding_means_no_dividend_even_if_later_position_added():
    state = replace(snapshot(), positions=())
    state = step(state, distributions=[dividend()]).state
    assert not state.receivables and state.processed_ids == ('div-X',)
    state = replace(state, positions=(('ETF-X', 50),))
    for day in DAYS[2:4]:
        state = apply_corporate_actions(state, sessions=DAYS, next_session=day).state
    assert state.cash == D('100')


def test_unknown_cash_date_stays_receivable():
    state = step(distributions=[dividend(cash_available_date=None)]).state
    for day in DAYS[2:]:
        state = apply_corporate_actions(state, sessions=DAYS, next_session=day).state
    assert state.cash == D('100') and state.receivables[0].amount == D('21')


def test_non_session_cash_date_rolls_forward_without_raising_order_cash():
    state = step(distributions=[dividend(cash_available_date='2025-01-11')]).state
    for day in DAYS[2:5]:
        state = apply_corporate_actions(state, sessions=DAYS, next_session=day).state
    result = apply_corporate_actions(state, sessions=DAYS, next_session=DAYS[5])
    assert result.state.cash == D('121') and result.prior_order_cash == D('100')


def test_same_day_cash_is_not_added_to_prior_order_cash():
    result = step(distributions=[dividend(cash_available_date=DAYS[1])])
    assert result.state.cash == D('121') and result.prior_order_cash == D('100')
    assert result.state.receivables == ()


def test_multi_symbol_order_and_generator_inputs_are_reproducible():
    splits = [split(), split(event_id='split-Y', symbol='ETF-Y', ratio=D('0.5'))]
    dividends = [dividend(), dividend(event_id='div-Y', symbol='ETF-Y',
                                     amount_per_prior_unit=D('11'))]
    expected = step(splits=splits, distributions=dividends)
    assert expected == step(splits=reversed(splits), distributions=reversed(dividends))
    assert dict(expected.state.positions) == {'ETF-X': 30, 'ETF-Y': 1}
    assert sum(r.amount for r in expected.state.receivables) == D('43')


@pytest.mark.parametrize('changes', [
    {'source': 'official PDF'}, {'known_at': '2025-01-06T07:00:01+00:00'},
    {'known_at': '2025-01-06T07:00:00'}, {'amount_basis_date': DAYS[1]},
    {'last_cum_date': '2025-01-05'}, {'ex_date': DAYS[2]},
    {'cash_available_date': DAYS[0]}, {'amount_per_prior_unit': D('NaN')},
    {'amount_per_prior_unit': D('-1')}, {'amount_per_prior_unit': 7.0},
])
def test_bad_or_future_distribution_information_is_rejected(changes):
    with pytest.raises(ValueError):
        step(distributions=[dividend(**changes)])


@pytest.mark.parametrize('changes', [
    {'ratio': D('0')}, {'ratio': D('Infinity')}, {'ratio': D('0.5')},
    {'market_date': DAYS[2]}, {'legal_date': DAYS[0]}, {'source': 'real'},
])
def test_invalid_or_fractional_split_is_rejected_atomically(changes):
    state = snapshot()
    with pytest.raises(ValueError):
        step(state, splits=[split(**changes)], distributions=[dividend()])
    assert state == snapshot()


def test_duplicate_event_ids_or_ambiguous_symbol_events_rejected():
    cases = [dict(splits=[split(), split()]),
             dict(distributions=[dividend(), dividend(event_id='other')]),
             dict(splits=[split(), split(event_id='other')]),
             dict(splits=[split()], distributions=[dividend(event_id='split-X')])]
    for case in cases:
        with pytest.raises(ValueError):
            step(**case)
    with pytest.raises(ValueError):
        step(replace(snapshot(), processed_ids=('div-X',)), distributions=[dividend()])


def test_skipped_duplicate_and_missing_calendar_sessions_rejected():
    for days, next_day in [(DAYS, DAYS[2]), (DAYS + (DAYS[-1],), DAYS[1]),
                           (DAYS[1:], DAYS[1]), ((), DAYS[1])]:
        with pytest.raises(ValueError):
            apply_corporate_actions(snapshot(), sessions=days, next_session=next_day)


@pytest.mark.parametrize('state', [
    replace(snapshot(), cash=D('-1')),
    replace(snapshot(), positions=(('ETF-X', True),)),
    replace(snapshot(), positions=(('ETF-X', 1), ('ETF-X', 2))),
    replace(snapshot(), processed_ids=('id', 'id')),
    replace(snapshot(), receivables=(Receivable('missing', 'ETF-X', D('7'), None),)),
])
def test_invalid_snapshot_cannot_create_assets(state):
    with pytest.raises(ValueError):
        step(state)
