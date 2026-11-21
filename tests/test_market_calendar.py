from datetime import date

import pytest

from stock_ai.data.market_calendar import spot_sessions


def fixture():
    # Synthetic holiday table exercises source validation and exchange-only closures.
    days=['2024/1/1']+[f'2024/2/{i}' for i in range(1,16)]+['2024/5/6']
    return ('国民の祝日・休日月日,国民の祝日・休日名称\n'+''.join(d+',fixture holiday\n' for d in days)).encode('cp932')


def test_exchange_new_year_days_are_not_just_national_holidays():
    assert spot_sessions(fixture(),start='2024-01-01',end='2024-01-08')==['2024-01-04','2024-01-05','2024-01-08']


def test_exchange_year_end_and_source_substitute_day():
    assert spot_sessions(fixture(),start='2024-12-30',end='2024-12-31')==['2024-12-30']
    assert spot_sessions(fixture(),start='2024-05-06',end='2024-05-07')==['2024-05-07']


@pytest.mark.parametrize('start,end',[('2023-01-01','2023-01-10'),('2024-01-01','2025-01-01')])
def test_absent_year_never_falls_back_to_weekdays(start,end):
    with pytest.raises(ValueError,match='absent or incomplete'):
        spot_sessions(fixture(),start=start,end=end)


def test_truncated_source_and_duplicate_holidays_rejected():
    with pytest.raises(ValueError,match='incomplete'):
        spot_sessions('国民の祝日・休日月日,国民の祝日・休日名称\n2024/1/1,元日\n'.encode('cp932'),start='2024-01-01',end='2024-01-10')
    with pytest.raises(ValueError,match='duplicate'):
        spot_sessions(fixture()+'2024/1/1,duplicate\n'.encode('cp932'),start='2024-01-01',end='2024-01-10')


def test_bad_schema_and_invalid_period_rejected():
    with pytest.raises(ValueError,match='schema'):
        spot_sessions(b'date,name\n',start='2024-01-01',end='2024-01-10')
    with pytest.raises(ValueError,match='period'):
        spot_sessions(fixture(),start='2024-01-10',end='2024-01-01')
