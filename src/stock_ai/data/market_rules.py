"""Offline order-shape checks; neither market-history certification nor fill inference."""
from datetime import date
from decimal import Decimal, InvalidOperation


# Inclusive upper prices. Table identity must come from contemporaneous metadata.
TICKS = {
    'topix500': ((1000, '.1'), (3000, '.5'), (10000, '1'), (30000, '5'),
                 (100000, '10'), (300000, '50'), (1000000, '100'),
                 (3000000, '500'), (10000000, '1000'), (30000000, '5000')),
    'etf_one_unit': ((10000, '1'), (30000, '5'), (100000, '10'),
                     (300000, '50'), (1000000, '100'), (3000000, '500'),
                     (10000000, '1000'), (30000000, '5000')),
    'other': ((3000, '1'), (5000, '5'), (30000, '10'), (50000, '50'),
              (300000, '100'), (500000, '500'), (3000000, '1000'),
              (5000000, '5000'), (30000000, '10000'), (50000000, '50000')),
}
FINAL_TICK = {'topix500': '10000', 'etf_one_unit': '10000', 'other': '100000'}
# Exclusive upper reference prices: unlike the inclusive tick thresholds above.
NORMAL_BANDS = ((100,30),(200,50),(500,80),(700,100),(1000,150),(1500,300),
                (2000,400),(3000,500),(5000,700),(7000,1000),(10000,1500),
                (15000,3000),(20000,4000),(30000,5000),(50000,7000),(70000,10000),
                (100000,15000),(150000,30000),(200000,40000),(300000,50000),
                (500000,70000),(700000,100000),(1000000,150000),(1500000,300000),
                (2000000,400000),(3000000,500000),(5000000,700000),
                (7000000,1000000),(10000000,1500000),(15000000,3000000),
                (20000000,4000000),(30000000,5000000),(50000000,7000000))


def positive_decimal(value):
    if isinstance(value, bool):
        raise ValueError('positive finite price required')
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('positive finite price required') from None
    if not number.is_finite() or number <= 0:
        raise ValueError('positive finite price required')
    return number


def tick_size(price, table):
    price = positive_decimal(price)
    if table not in TICKS:
        raise ValueError('explicit recognized tick table required')
    return next((Decimal(tick) for upper, tick in TICKS[table] if price <= upper),
                Decimal(FINAL_TICK[table]))


def post_20250507_etf_table(day, lot):
    """General rule only; callers still need per-symbol historical metadata."""
    day = date.fromisoformat(day)
    if not date(2025,5,7) <= day < date(2027,3,1):
        raise ValueError('outside documented general-rule interval; dated metadata required')
    if type(lot) is not int or (lot != 1 and lot < 10):
        raise ValueError('unsupported ETF lot category')
    return 'etf_one_unit' if lot == 1 else 'topix500'


def normal_band_width(reference):
    """Normal width only; NOT actual daily limits or expansion determination."""
    reference = positive_decimal(reference)
    return next((Decimal(width) for upper, width in NORMAL_BANDS if reference < upper),
                Decimal(10000000))


def check_limit_order(*, price, quantity, lot, table, lower=None, upper=None):
    """Check supplied metadata; never infer daily limits from previous OHLC."""
    price = positive_decimal(price)
    if type(lot) is not int or lot <= 0 or type(quantity) is not int or quantity <= 0:
        raise ValueError('positive integer quantity and lot required')
    reasons = []
    if quantity % lot:
        reasons.append('quantity_not_lot_multiple')
    if price % tick_size(price, table):
        reasons.append('price_not_on_tick')
    if lower is None or upper is None:
        reasons.append('actual_daily_price_band_unconfirmed')
    else:
        lower, upper = positive_decimal(lower), positive_decimal(upper)
        if lower > upper:
            raise ValueError('inverted daily price band')
        if not lower <= price <= upper:
            reasons.append('price_outside_daily_band')
    return dict(shape_valid=not reasons, reasons=reasons, execution_confirmed=False)


def assess_auction_report(*, requested_quantity, lot, reported_quantity=None,
                          reported_price=None, limit=None, side='buy'):
    """Classify an explicit allocation report, not an OHLC-implied fill.

    Positive allocation remains a supplied report, not independently verified
    execution evidence. No cash, fill, or PnL is produced by this function.
    """
    if (type(requested_quantity) is not int or requested_quantity <= 0
            or type(lot) is not int or lot <= 0 or requested_quantity % lot
            or side not in ('buy', 'sell')):
        raise ValueError('invalid order quantity, lot or side')
    if reported_quantity is None:
        return dict(status='allocation_unconfirmed', execution_confirmed=False)
    if (type(reported_quantity) is not int or not 0 <= reported_quantity <= requested_quantity
            or reported_quantity % lot):
        raise ValueError('invalid reported allocation')
    if reported_quantity == 0:
        if reported_price is not None:
            raise ValueError('zero allocation cannot have an execution price')
        return dict(status='reported_unfilled', execution_confirmed=False)
    if reported_price is None:
        raise ValueError('positive allocation requires reported price')
    price = positive_decimal(reported_price)
    if limit is not None:
        limit = positive_decimal(limit)
        if (side == 'buy' and price > limit) or (side == 'sell' and price < limit):
            raise ValueError('reported price violates limit')
    return dict(status='reported_full' if reported_quantity == requested_quantity else 'reported_partial',
                reported_quantity=reported_quantity, reported_price=str(price), execution_confirmed=False)
