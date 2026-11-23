"""Synthetic I3 cash/reservations; no broker, position engine or strategy PnL."""
from dataclasses import dataclass, replace
from datetime import timedelta, timezone
from decimal import Decimal
from fractions import Fraction

from stock_ai.backtest.entitlement_v3 import _exact_decimal, _snapshot_hash, value_rights
from stock_ai.data.swing_v3_schema import instant


def _amount(value, positive=False):
    if (not isinstance(value, Decimal) or not value.is_finite()
            or value < 0 or (positive and value == 0)):
        raise ValueError('finite nonnegative Decimal required')
    return value


def _sum(values):
    return _exact_decimal(sum((Fraction(x) for x in values), Fraction(0)))


def _difference(a, b):
    return _exact_decimal(Fraction(a)-Fraction(b))


@dataclass(frozen=True)
class CashLot:
    lot_id: str
    amount: Decimal
    usable_at: str
    recorded_at: str
    origin: str


@dataclass(frozen=True)
class BuyRequest:
    order_id: str
    symbol: str
    quantity: int
    lot_size: int
    limit: Decimal
    impact_bps: Decimal
    fee: Decimal


@dataclass(frozen=True)
class Reservation:
    request: BuyRequest
    decision_at: str
    target_session: str
    allocations: tuple[tuple[str, Decimal], ...]
    status: str = 'pending'


@dataclass(frozen=True)
class Payment:
    event_id: str
    position_id: str
    amount: Decimal
    revision_id: str
    recorded_at: str


@dataclass(frozen=True)
class CashBook:
    snapshot_sha256: str
    as_of: str
    initial_cash: Decimal
    lots: tuple[CashLot, ...]
    reservations: tuple[Reservation, ...] = ()
    decision_batches: tuple[str, ...] = ()
    receipts: tuple[str, ...] = ()
    payments: tuple[Payment, ...] = ()
    sale_credits: Decimal = Decimal('0')
    distribution_credits: Decimal = Decimal('0')
    purchase_debits: Decimal = Decimal('0')

    @property
    def qualified_for_real_data(self):
        return False


def new_cash_book(snapshot, *, as_of, initial_cash=Decimal('100000')):
    instant(as_of)
    _amount(initial_cash, positive=True)
    return CashBook(_snapshot_hash(snapshot), as_of, initial_cash,
                    (CashLot('initial', initial_cash, as_of, as_of, 'initial'),))


def _check(snapshot, book, as_of):
    if book.snapshot_sha256 != _snapshot_hash(snapshot):
        raise ValueError('cash book bound to different snapshot')
    if instant(as_of) < instant(book.as_of):
        raise ValueError('cash clock cannot go backwards')
    total = _sum(lot.amount for lot in book.lots)
    expected = _difference(_sum((book.initial_cash, book.sale_credits,
                                book.distribution_credits)), book.purchase_debits)
    if total != expected or total < 0:
        raise ValueError('cash reconciliation failed')
    for lot in book.lots:
        _amount(lot.amount)
    if len({l.lot_id for l in book.lots}) != len(book.lots):
        raise ValueError('duplicate cash lot')
    for lot in book.lots:
        held = _sum(a for r in book.reservations if r.status == 'pending'
                    for lid, a in r.allocations if lid == lot.lot_id)
        if held > lot.amount:
            raise ValueError('cash lot overreserved')


def _jst_day(timestamp):
    return instant(timestamp).astimezone(timezone(timedelta(hours=9))).date().isoformat()


def cash_balance(snapshot, book, *, as_of):
    _check(snapshot, book, as_of)
    return _sum(l.amount for l in book.lots)


def available_cash(snapshot, book, *, as_of):
    _check(snapshot, book, as_of)
    usable = _sum(l.amount for l in book.lots
                  if max(instant(l.usable_at), instant(l.recorded_at)) <= instant(as_of))
    held = _sum(a for r in book.reservations if r.status == 'pending' for _, a in r.allocations)
    result = _difference(usable, held)
    if result < 0:
        raise ValueError('negative available cash')
    return result


def freeze_buys(snapshot, book, *, decision_at, target_session, requests,
                occupied_symbols=()):
    """One complete prior-close batch; no second allocation after a release.

    Occupied symbols are an explicit external snapshot; I4/I5 must verify them.
    No risk/price/venue eligibility is certified by this cash-only component.
    """
    _check(snapshot, book, decision_at)
    day = _jst_day(decision_at)
    if day not in snapshot.sessions or instant(decision_at) != instant(day+'T07:00:00Z'):
        raise ValueError('orders require conservative prior-close cutoff')
    i = snapshot.sessions.index(day)
    if i+1 >= len(snapshot.sessions) or snapshot.sessions[i+1] != target_session:
        raise ValueError('target must be next session')
    if any(instant(decision_at) == instant(t) for t in book.decision_batches):
        raise ValueError('decision batch already frozen')
    if any(r.status == 'pending' and r.target_session <= day for r in book.reservations):
        raise ValueError('elapsed order must be settled or expired')
    requests, occupied = tuple(requests), tuple(occupied_symbols)
    if len(set(occupied)) != len(occupied) or any(s not in snapshot.symbols for s in occupied):
        raise ValueError('invalid occupied symbols')
    active = [r for r in book.reservations if r.status == 'pending']
    symbols = occupied+tuple(r.request.symbol for r in active)+tuple(r.symbol for r in requests)
    if len(symbols) > 3 or len(set(symbols)) != len(symbols):
        raise ValueError('three position slots or duplicate symbol')
    ids = {r.request.order_id for r in book.reservations}
    balances = {}
    for lot in book.lots:
        held = _sum(a for r in active for lid, a in r.allocations if lid == lot.lot_id)
        balances[lot.lot_id] = (_difference(lot.amount, held)
            if max(instant(lot.usable_at), instant(lot.recorded_at)) <= instant(decision_at)
            else Decimal('0'))
    reservations = []
    for request in requests:
        if (not request.order_id or request.order_id in ids or request.symbol not in snapshot.symbols
                or type(request.quantity) is not int or request.quantity <= 0
                or type(request.lot_size) is not int or request.lot_size <= 0
                or request.quantity % request.lot_size):
            raise ValueError('invalid request ID, symbol or lot quantity')
        rules = [r for r in snapshot.lots if r.symbol == request.symbol
                 and r.effective_session <= day]
        rule = max(rules, key=lambda r: r.effective_session) if rules else None
        if (rule is None or instant(rule.available_at) > instant(decision_at)
                or rule.size != request.lot_size):
            raise ValueError('lot rule unknown or inconsistent with request')
        _amount(request.limit, positive=True); _amount(request.impact_bps); _amount(request.fee)
        needed = _exact_decimal(Fraction(request.quantity)*Fraction(request.limit)
                    * (1+Fraction(request.impact_bps)/10000)+Fraction(request.fee))
        allocations = []
        for lot in book.lots:
            take = min(needed, balances[lot.lot_id])
            if take:
                allocations.append((lot.lot_id, take))
                balances[lot.lot_id] = _difference(balances[lot.lot_id], take)
                needed = _difference(needed, take)
        if needed:
            raise ValueError('insufficient unreserved usable cash')
        ids.add(request.order_id)
        reservations.append(Reservation(request, decision_at, target_session, tuple(allocations)))
    updated = replace(book, as_of=decision_at, reservations=book.reservations+tuple(reservations),
                      decision_batches=book.decision_batches+(decision_at,))
    _check(snapshot, updated, decision_at)
    return updated


def settle_buy(snapshot, book, *, order_id, at, fill_price=None):
    """Synthetic opening settlement only; price is supplied, never invented."""
    _check(snapshot, book, at)
    matching = [r for r in book.reservations if r.request.order_id == order_id]
    if len(matching) != 1 or matching[0].status != 'pending':
        raise ValueError('unknown or already settled order')
    r = matching[0]
    if instant(at) != instant(r.target_session+'T00:00:00Z'):
        raise ValueError('settlement must be target synthetic open')
    debit = Decimal('0')
    if fill_price is not None:
        _amount(fill_price, positive=True)
        if fill_price > r.request.limit:
            raise ValueError('fee-exclusive impacted fill price exceeds limit')
        debit = _exact_decimal(Fraction(r.request.quantity)*Fraction(fill_price)+Fraction(r.request.fee))
    if debit > _sum(a for _, a in r.allocations):
        raise ValueError('debit exceeds frozen reservation')
    remaining = debit
    deductions = {}
    for lid, allocation in r.allocations:
        take = min(remaining, allocation)
        deductions[lid] = take
        remaining = _difference(remaining, take)
    lots = tuple(replace(l, amount=_difference(l.amount, deductions.get(l.lot_id, Decimal('0'))))
                 for l in book.lots)
    updated = replace(book, as_of=at, lots=lots,
        purchase_debits=_sum((book.purchase_debits, debit)),
        reservations=tuple(replace(x, status='filled' if fill_price is not None else 'expired')
                           if x.request.order_id == order_id else x for x in book.reservations))
    _check(snapshot, updated, at)
    return updated


def credit_sale(snapshot, book, *, transaction_id, net_amount, at, source):
    """Synthetic net proceeds only. I4 must verify position, proceeds and fee."""
    _check(snapshot, book, at); _amount(net_amount, positive=True)
    identifier = 'sale:'+transaction_id
    day = _jst_day(at)
    if (source != 'synthetic' or not transaction_id or identifier in book.receipts
            or day not in snapshot.sessions):
        raise ValueError('invalid or duplicate synthetic sale')
    i = snapshot.sessions.index(day)
    if i+1 >= len(snapshot.sessions):
        raise ValueError('next usable session not covered')
    usable = snapshot.sessions[i+1]+'T07:00:00Z'
    lot = CashLot(identifier, net_amount, usable, at, 'sale')
    updated = replace(book, as_of=at, lots=book.lots+(lot,),
        receipts=book.receipts+(identifier,), sale_credits=_sum((book.sale_credits,net_amount)))
    _check(snapshot, updated, at)
    return updated


def receive_distributions(snapshot, rights, book, *, as_of):
    """Credit full synthetic account receipts, never a per-unit payout quote.

    CashEvidence.amount must equal this account's final gross entitlement.
    Partial payments, withholding and supplemental receipts are unsupported.
    """
    _check(snapshot, book, as_of)
    valuation = value_rights(snapshot, rights, as_of=as_of, mode='restated')
    lots, receipts, payments = list(book.lots), list(book.receipts), list(book.payments)
    credits = Decimal('0')
    for evidence in sorted(snapshot.cash_evidence, key=lambda e: e.event_id):
        identifier = 'distribution:'+evidence.event_id
        if (identifier in receipts or evidence.status == 'schedule_only'
                or instant(evidence.available_at) > instant(as_of)
                or instant(evidence.cash_available_at) > instant(as_of)):
            continue
        lines = [l for l in valuation.lines if l.event_id == evidence.event_id]
        if any(l.amount is None for l in lines):
            raise ValueError('final entitlement unknown; cannot settle payment')
        total = _sum(l.amount for l in lines)
        if total != Decimal(evidence.amount):
            raise ValueError('account receipt differs from final entitlement; quote basis unresolved')
        lots.append(CashLot(identifier, total, evidence.cash_available_at, as_of, 'distribution'))
        receipts.append(identifier)
        payments.extend(Payment(l.event_id, l.position_id, l.amount, l.revision_id, as_of) for l in lines)
        credits = _sum((credits, total))
    updated = replace(book, as_of=as_of, lots=tuple(lots), receipts=tuple(receipts),
        payments=tuple(payments), distribution_credits=_sum((book.distribution_credits,credits)))
    _check(snapshot, updated, as_of)
    outstanding_receivable(snapshot, rights, updated, as_of=as_of)
    return updated


def outstanding_receivable(snapshot, rights, book, *, as_of, mode='decision'):
    _check(snapshot, book, as_of)
    valuation = value_rights(snapshot, rights, as_of=as_of, mode=mode)
    if valuation.total is None:
        return None
    by_right = {(l.event_id,l.position_id): l.amount for l in valuation.lines}
    paid = {}
    for p in book.payments:
        key = (p.event_id,p.position_id)
        paid[key] = _sum((paid.get(key,Decimal('0')),p.amount))
    if any(key not in by_right or amount > by_right[key] for key,amount in paid.items()):
        raise ValueError('payment exceeds revised entitlement; repayment unsupported')
    return _difference(valuation.total, _sum(p.amount for p in book.payments))
