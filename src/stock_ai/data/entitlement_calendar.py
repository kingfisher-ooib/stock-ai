"""Rule-derived date candidates; never event confirmation or a backtest action feed."""
from bisect import bisect_right
from datetime import date


def reconstruct_ex_date(record_date, sessions, *, coverage_start, coverage_end):
    """Assume this complete calendar describes both trading and settlement sessions.

    For a non-session record date, the latest settlement on/before it is used.
    Corporate-action exceptions and historical publication timing are not inferred.
    """
    record = date.fromisoformat(record_date)
    first, last = date.fromisoformat(coverage_start), date.fromisoformat(coverage_end)
    parsed = [date.fromisoformat(day) for day in sessions]
    if (not parsed or parsed != sorted(set(parsed)) or first > last
            or parsed[0] < first or parsed[-1] > last):
        raise ValueError('invalid or duplicate calendar')
    if not first <= record <= last:
        raise ValueError('record date outside calendar coverage')
    if record < date(2019,7,16):
        raise ValueError('T+2 rule not applicable before 2019-07-16')
    settlement_index = bisect_right(parsed, record)-1
    if settlement_index < 2:
        raise ValueError('insufficient preceding sessions')
    cum_index = settlement_index-2
    if parsed[cum_index] < date(2019,7,16):
        raise ValueError('trade date crosses T+2 transition')
    return dict(record_date=record.isoformat(), record_is_session=record in parsed,
                assumed_latest_settlement_date=parsed[settlement_index].isoformat(),
                candidate_last_cum_date=parsed[cum_index].isoformat(),
                candidate_ex_date=parsed[cum_index+1].isoformat(),
                method='T+2_latest_settlement_session_on_or_before_record_date',
                directly_verified=False, qualified_for_backtest=False)
