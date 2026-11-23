import pytest

from stock_ai.data.entitlement_calendar import reconstruct_ex_date


def derive(record, days):
    return reconstruct_ex_date(record,days,coverage_start=days[0],coverage_end='2025-08-12')


@pytest.mark.parametrize('record,days,cum,ex,settlement', [
    ('2025-07-10',['2025-07-07','2025-07-08','2025-07-09','2025-07-10','2025-07-11'],
     '2025-07-08','2025-07-09','2025-07-10'),
    ('2025-07-08',['2025-07-04','2025-07-07','2025-07-08','2025-07-09'],
     '2025-07-04','2025-07-07','2025-07-08'),
    ('2025-02-09',['2025-02-04','2025-02-05','2025-02-06','2025-02-07','2025-02-10'],
     '2025-02-05','2025-02-06','2025-02-07'),
    ('2025-08-09',['2025-08-05','2025-08-06','2025-08-07','2025-08-08','2025-08-12'],
     '2025-08-06','2025-08-07','2025-08-08'),
])
def test_business_weekend_and_holiday_dates(record,days,cum,ex,settlement):
    result=derive(record,days)
    assert result['candidate_last_cum_date']==cum
    assert result['candidate_ex_date']==ex
    assert result['assumed_latest_settlement_date']==settlement
    assert not result['directly_verified'] and not result['qualified_for_backtest']


@pytest.mark.parametrize('days', [[],['2025-07-07','2025-07-07'],['2025-07-08','2025-07-07']])
def test_bad_calendar_rejected(days):
    with pytest.raises(ValueError):
        reconstruct_ex_date('2025-07-10',days,coverage_start='2025-07-01',coverage_end='2025-07-11')


def test_incomplete_edge_or_outside_coverage_rejected():
    days=['2025-07-09','2025-07-10','2025-07-11']
    with pytest.raises(ValueError,match='insufficient'):
        reconstruct_ex_date('2025-07-10',days,coverage_start=days[0],coverage_end=days[-1])
    with pytest.raises(ValueError,match='outside'):
        reconstruct_ex_date('2025-07-12',days,coverage_start=days[0],coverage_end=days[-1])


def test_transition_to_tplus2_is_not_applied_retroactively():
    for record in ['2019-07-12','2019-07-16']:
        with pytest.raises(ValueError,match=r'T\+2'):
            reconstruct_ex_date(record,['2019-07-10','2019-07-11','2019-07-12','2019-07-16'],
                                 coverage_start='2019-07-10',coverage_end='2019-07-16')


def test_input_calendar_is_preserved():
    days=['2025-07-07','2025-07-08','2025-07-09','2025-07-10']
    original=list(days)
    assert derive('2025-07-10',days)==derive('2025-07-10',days)
    assert days==original
