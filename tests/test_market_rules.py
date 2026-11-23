from decimal import Decimal

import pytest

from stock_ai.data.market_rules import (assess_auction_report, check_limit_order,
    normal_band_width, post_20250507_etf_table, tick_size)


@pytest.mark.parametrize('price,table,expected', [
    ('1000','topix500','.1'),('1000.1','topix500','.5'),
    ('3000','topix500','.5'),('3000.5','topix500','1'),
    ('10000','topix500','1'),('10001','topix500','5'),
    ('30000','etf_one_unit','5'),('30001','etf_one_unit','10'),
    ('338.7','etf_one_unit','1'),('338.7','topix500','.1'),
    ('3000','other','1'),('3001','other','5'),('5001','other','10'),
    ('50000001','other','100000'),('30000001','topix500','10000')])
def test_tick_table_thresholds(price, table, expected):
    assert tick_size(price,table) == Decimal(expected)


@pytest.mark.parametrize('reference,width', [('99.9',30),(100,50),(999,150),(1000,300),
                                             (3000,700),(30000,7000),(50000000,10000000)])
def test_normal_band_thresholds_are_exclusive(reference,width):
    assert normal_band_width(reference) == Decimal(width)


@pytest.mark.parametrize('price', [0,-1,float('nan'),float('inf'),True,None,'garbage'])
def test_invalid_numeric_inputs_rejected(price):
    with pytest.raises(ValueError): tick_size(price,'topix500')
    with pytest.raises(ValueError): normal_band_width(price)


def test_table_depends_on_effective_date_and_contemporaneous_lot():
    assert post_20250507_etf_table('2025-05-07',1) == 'etf_one_unit'
    assert post_20250507_etf_table('2025-05-07',10) == 'topix500'
    for day in ['2025-05-06','2024-01-04','2027-03-01']:
        with pytest.raises(ValueError,match='dated metadata'):
            post_20250507_etf_table(day,1)
    for lot in [0,-1,2,5,True,1.0]:
        with pytest.raises(ValueError): post_20250507_etf_table('2025-05-07',lot)


def test_missing_daily_limits_never_pass_as_a_normal_band():
    result = check_limit_order(price='338.7',quantity=10,lot=10,table='topix500')
    assert result['reasons'] == ['actual_daily_price_band_unconfirmed']
    assert not result['shape_valid'] and not result['execution_confirmed']


def test_supplied_limits_and_ticks_are_checked_without_claiming_execution():
    good = check_limit_order(price='338.7',quantity=10,lot=10,table='topix500',lower=300,upper=400)
    assert good['shape_valid'] and not good['execution_confirmed']
    bad = check_limit_order(price='338.7',quantity=1,lot=1,table='etf_one_unit',lower=300,upper=400)
    assert bad['reasons'] == ['price_not_on_tick']
    bad = check_limit_order(price=350,quantity=15,lot=10,table='topix500',lower=300,upper=340)
    assert set(bad['reasons']) == {'quantity_not_lot_multiple','price_outside_daily_band'}


def test_zero_quantity_and_inverted_limits_are_errors():
    with pytest.raises(ValueError):
        check_limit_order(price=350,quantity=0,lot=10,table='topix500')
    with pytest.raises(ValueError):
        check_limit_order(price=350,quantity=10,lot=10,table='topix500',lower=400,upper=300)
    with pytest.raises(ValueError):tick_size(350,'assumed_table')


def test_ohlc_price_alone_cannot_establish_an_allocation():
    result = assess_auction_report(requested_quantity=100,lot=10,reported_price=338)
    assert result == dict(status='allocation_unconfirmed',execution_confirmed=False)


@pytest.mark.parametrize('quantity,status', [(0,'reported_unfilled'),(20,'reported_partial'),(100,'reported_full')])
def test_explicit_allocation_is_not_expanded_to_full_fill(quantity,status):
    result = assess_auction_report(requested_quantity=100,lot=10,reported_quantity=quantity,
                                   reported_price=338 if quantity else None,limit=340)
    assert result['status'] == status and not result['execution_confirmed']
    if quantity:assert result['reported_quantity'] == quantity


@pytest.mark.parametrize('quantity', [-1,110,15,True,10.0])
def test_bad_reported_quantity_rejected(quantity):
    with pytest.raises(ValueError):
        assess_auction_report(requested_quantity=100,lot=10,reported_quantity=quantity,reported_price=338)


@pytest.mark.parametrize('side,price', [('buy',341),('sell',339)])
def test_reported_fill_cannot_violate_order_limit(side,price):
    with pytest.raises(ValueError,match='violates limit'):
        assess_auction_report(requested_quantity=100,lot=10,reported_quantity=100,
                               reported_price=price,limit=340,side=side)


def test_execution_price_requires_nonzero_allocation():
    with pytest.raises(ValueError):
        assess_auction_report(requested_quantity=100,lot=10,reported_quantity=0,reported_price=338)
    with pytest.raises(ValueError):
        assess_auction_report(requested_quantity=100,lot=10,reported_quantity=100)
