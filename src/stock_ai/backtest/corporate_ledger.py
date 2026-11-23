"""Synthetic accounting prototype, independent of the frozen swing engines.

No orders, fills, tax model, event-date inference or real-data qualification.
Distribution amounts must already use the preceding close's market unit.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal


@dataclass(frozen=True)
class Split:
    event_id: str
    symbol: str
    market_date: str
    legal_date: str
    ratio: Decimal
    known_at: str
    source: str


@dataclass(frozen=True)
class Distribution:
    event_id: str
    symbol: str
    last_cum_date: str
    ex_date: str
    amount_basis_date: str
    amount_per_prior_unit: Decimal
    cash_available_date: str | None
    known_at: str
    source: str


@dataclass(frozen=True)
class Receivable:
    event_id: str
    symbol: str
    amount: Decimal
    cash_available_date: str | None


@dataclass(frozen=True)
class CorporateState:
    as_of: str
    positions: tuple[tuple[str, int], ...]
    cash: Decimal
    receivables: tuple[Receivable, ...] = ()
    processed_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionStep:
    state: CorporateState
    prior_order_cash: Decimal
    distribution_credits: tuple[Receivable, ...]

    @property
    def qualified_for_real_data(self):
        return False


def _money(value, *, zero=False):
    if (not isinstance(value, Decimal) or not value.is_finite()
            or (value < 0 if zero else value <= 0)):
        raise ValueError('finite Decimal with valid sign required')
    return value


def _available_date(value):
    return date.fromisoformat(value) if value is not None else None


def apply_corporate_actions(state, *, sessions, next_session,
                            splits=(), distributions=()):
    """Advance one session from an immutable prior-close holdings snapshot.

    Caller-provided calendars and snapshots are not certified by this function.
    Explicit cash availability is required; a scheduled payment is insufficient.
    """
    splits, distributions = tuple(splits), tuple(distributions)
    days = [date.fromisoformat(day) for day in sessions]
    previous, today = date.fromisoformat(state.as_of), date.fromisoformat(next_session)
    if not days or days != sorted(set(days)) or previous not in days:
        raise ValueError('invalid calendar or prior snapshot date')
    i = days.index(previous)
    if i + 1 >= len(days) or days[i + 1] != today:
        raise ValueError('must advance exactly one session')
    _money(state.cash, zero=True)
    positions = dict(state.positions)
    if (len(positions) != len(state.positions)
            or any(not s or type(q) is not int or q < 0
                   for s, q in state.positions)):
        raise ValueError('invalid positions')
    processed = set(state.processed_ids)
    if len(processed) != len(state.processed_ids) or any(not s for s in processed):
        raise ValueError('invalid processed event IDs')
    pending = list(state.receivables)
    pending_ids = set()
    for r in pending:
        _money(r.amount)
        _available_date(r.cash_available_date)
        if (not r.event_id or not r.symbol or r.event_id in pending_ids
                or r.event_id not in processed):
            raise ValueError('invalid or duplicate receivable')
        pending_ids.add(r.event_id)
    # 07:00 UTC is 16:00 JST, a conservative prior-close information cutoff.
    cutoff = datetime.combine(previous, time(7), timezone.utc)
    all_events = tuple(splits) + tuple(distributions)
    ids, split_symbols, distribution_symbols = set(), set(), set()
    for event in all_events:
        if (not event.event_id or not event.symbol or event.source != 'synthetic'
                or event.event_id in processed or event.event_id in ids):
            raise ValueError('synthetic source and unique unprocessed event IDs required')
        known = datetime.fromisoformat(event.known_at.replace('Z', '+00:00'))
        if known.tzinfo is None or known > cutoff:
            raise ValueError('event not known at prior-close cutoff')
        ids.add(event.event_id)
    for event in splits:
        _money(event.ratio)
        if (date.fromisoformat(event.market_date) != today
                or date.fromisoformat(event.legal_date) < today
                or event.symbol in split_symbols):
            raise ValueError('invalid or ambiguous split')
        split_symbols.add(event.symbol)
    for event in distributions:
        _money(event.amount_per_prior_unit)
        available = _available_date(event.cash_available_date)
        if (date.fromisoformat(event.ex_date) != today
                or date.fromisoformat(event.last_cum_date) != previous
                or event.amount_basis_date != state.as_of
                or (available is not None and available < today)
                or event.symbol in distribution_symbols):
            raise ValueError('invalid distribution date or prior-unit basis')
        distribution_symbols.add(event.symbol)
    # Use the saved prior-close quantity, never today's split-adjusted quantity.
    credits = []
    for event in sorted(distributions, key=lambda e: e.event_id):
        value = positions.get(event.symbol, 0) * event.amount_per_prior_unit
        if value:
            credits.append(Receivable(event.event_id, event.symbol, value,
                                      event.cash_available_date))
    for event in sorted(splits, key=lambda e: e.event_id):
        quantity = positions.get(event.symbol, 0) * event.ratio
        if quantity != quantity.to_integral_value():
            raise ValueError('fractional split quantity unsupported')
        if event.symbol in positions:
            positions[event.symbol] = int(quantity)
    cash = state.cash
    unpaid = []
    for r in pending + credits:
        if r.cash_available_date is not None and date.fromisoformat(r.cash_available_date) <= today:
            cash += r.amount
        else:
            unpaid.append(r)
    updated = CorporateState(next_session, tuple(sorted(positions.items())), cash,
                             tuple(sorted(unpaid, key=lambda r: r.event_id)),
                             tuple(sorted(processed | ids)))
    return ActionStep(updated, state.cash, tuple(credits))
