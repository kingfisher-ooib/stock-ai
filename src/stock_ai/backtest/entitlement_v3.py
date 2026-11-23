"""Synthetic I2 entitlement accounting; no cash movement, orders or PnL."""
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timezone
from decimal import Decimal
from fractions import Fraction
import hashlib
import json

from stock_ai.data.swing_v3_schema import Snapshot, instant


@dataclass(frozen=True)
class Holding:
    position_id: str
    symbol: str
    quantity: int
    unit_basis_id: str
    as_of_session: str


@dataclass(frozen=True)
class Right:
    event_id: str
    position_id: str
    symbol: str
    quantity: int
    unit_basis_id: str
    last_cum_session: str
    captured_at: str


@dataclass(frozen=True)
class ValuationLine:
    event_id: str
    position_id: str
    revision_id: str | None
    amount: Decimal | None


@dataclass(frozen=True)
class Valuation:
    as_of: str
    mode: str
    lines: tuple[ValuationLine, ...]
    total: Decimal | None
    status: str


@dataclass(frozen=True)
class Change:
    recorded_at: str
    event_id: str
    position_id: str
    old_revision_id: str | None
    new_revision_id: str | None
    old_amount: Decimal | None
    new_amount: Decimal | None
    delta: Decimal | None


@dataclass(frozen=True)
class EntitlementBook:
    snapshot_sha256: str
    captured_events: tuple[str, ...] = ()
    rights: tuple[Right, ...] = ()
    decisions: tuple[Valuation, ...] = ()
    changes: tuple[Change, ...] = ()

    @property
    def qualified_for_real_data(self):
        return False


def _snapshot_hash(snapshot):
    if (not isinstance(snapshot, Snapshot) or snapshot.synthetic is not True
            or any(s.origin != 'synthetic' or s.availability_basis != 'synthetic'
                   for s in snapshot.sources)):
        raise ValueError('validated synthetic snapshot required')
    return hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest()


def new_book(snapshot):
    """Use an I1-loaded, sealed full-history snapshot; knowledge is filtered later."""
    return EntitlementBook(_snapshot_hash(snapshot))


def _check(snapshot, book):
    if book.snapshot_sha256 != _snapshot_hash(snapshot):
        raise ValueError('book is bound to a different snapshot version')


def capture_rights(snapshot, book, *, ex_session, holdings):
    """Save prior-close holdings before ex-date trades or market-unit splits.

    Holdings are caller-supplied synthetic snapshots, not proof of ownership.
    Empty holdings explicitly mean no entitlement; never fill missing history.
    """
    _check(snapshot, book)
    if ex_session not in snapshot.sessions:
        raise ValueError('ex session outside calendar')
    events = [e for e in snapshot.entitlements if e.ex_session == ex_session]
    if not events or any(e.event_id in book.captured_events for e in events):
        raise ValueError('no new entitlement events on session')
    if any(e.ex_session < ex_session and e.event_id not in book.captured_events
           for e in snapshot.entitlements):
        raise ValueError('prior entitlement snapshots missing')
    captured_at = ex_session + 'T00:00:00+00:00'
    if book.decisions and instant(book.decisions[-1].as_of) >= instant(captured_at):
        raise ValueError('cannot add entitlement behind a recorded decision')
    i = snapshot.sessions.index(ex_session)
    if i == 0:
        raise ValueError('prior session required')
    previous = snapshot.sessions[i-1]
    cutoff = datetime.combine(date.fromisoformat(previous), time(7), timezone.utc)
    positions = tuple(holdings)
    if (len({p.position_id for p in positions}) != len(positions)
            or len({p.symbol for p in positions}) != len(positions)):
        raise ValueError('duplicate position or symbol')
    for p in positions:
        if (not p.position_id or p.symbol not in snapshot.symbols
                or type(p.quantity) is not int or p.quantity < 0
                or p.as_of_session != previous):
            raise ValueError('invalid prior-close holdings')
        bases = [b for b in snapshot.unit_bases if b.symbol == p.symbol
                 and b.effective_session <= previous]
        basis = max(bases, key=lambda b: b.effective_session) if bases else None
        if (basis is None or basis.basis_id != p.unit_basis_id
                or instant(basis.available_at) > cutoff):
            raise ValueError('holdings unit not known and contemporaneous')
    additions = []
    for e in events:
        if e.last_cum_session != previous or instant(e.available_at) > cutoff:
            raise ValueError('entitlement schedule not known at prior close')
        for p in positions:
            if p.symbol == e.symbol and p.quantity:
                additions.append(Right(e.event_id, p.position_id, p.symbol, p.quantity,
                                       p.unit_basis_id, previous, captured_at))
    return replace(book, captured_events=tuple(sorted(set(book.captured_events)
                   | {e.event_id for e in events})),
                   rights=tuple(sorted(book.rights+tuple(additions),
                                       key=lambda r: (r.event_id, r.position_id))))


def _unit_factor(snapshot, symbol, before, after, cutoff):
    """Exact quote-unit conversion using only split ratios known at cutoff."""
    known_bases = {b.basis_id for b in snapshot.unit_bases
                   if b.symbol == symbol and instant(b.available_at) <= cutoff}
    if before not in known_bases or after not in known_bases:
        return None
    if before == after:
        return Fraction(1)
    graph = {}
    for s in snapshot.splits:
        if (s.symbol != symbol or instant(s.available_at) > cutoff
                or s.from_basis_id not in known_bases or s.to_basis_id not in known_bases):
            continue
        ratio = Fraction(Decimal(s.ratio_new_per_old))
        graph.setdefault(s.from_basis_id, []).append((s.to_basis_id, ratio))
        graph.setdefault(s.to_basis_id, []).append((s.from_basis_id, 1/ratio))
    stack, visited = [(before, Fraction(1))], set()
    while stack:
        current, factor = stack.pop()
        if current == after:
            return factor
        if current in visited:
            continue
        visited.add(current)
        stack.extend((other, factor*ratio) for other, ratio in graph.get(current, [])
                     if other not in visited)
    return None


def _exact_decimal(value):
    # Do not silently round a non-terminating entitlement or use Decimal's
    # process-wide precision to truncate a large exact amount.
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValueError('non-terminating monetary conversion requires rounding policy')
    scale = max(twos, fives)
    integer = value.numerator * 2**(scale-twos) * 5**(scale-fives)
    digits = str(abs(integer))
    return Decimal((1 if integer < 0 else 0, tuple(map(int, digits)), -scale))


def value_rights(snapshot, book, *, as_of, mode):
    """Value gross entitlement amounts, not cash, net assets or strategy income.

    'restated' requires final/correction amounts and is labelled separately.
    Unknown decision amounts produce a halt result, not a zero dividend.
    """
    _check(snapshot, book)
    if mode not in ('decision', 'restated'):
        raise ValueError('unknown valuation mode')
    cutoff = instant(as_of)
    # A caller must capture every elapsed ex-date, even when holdings were zero.
    if any(instant(e.ex_session+'T00:00:00+00:00') <= cutoff
           and e.event_id not in book.captured_events for e in snapshot.entitlements):
        raise ValueError('elapsed entitlement snapshot missing')
    lines = []
    for right in book.rights:
        if cutoff < instant(right.captured_at):
            raise ValueError('valuation predates rights capture')
        revisions = [r for r in snapshot.amount_revisions if r.event_id == right.event_id
                     and instant(r.available_at) <= cutoff
                     and (mode == 'decision' or r.status in ('final', 'correction'))]
        revision = max(revisions, key=lambda r: instant(r.available_at)) if revisions else None
        amount = None
        if revision is not None:
            factor = _unit_factor(snapshot, right.symbol, right.unit_basis_id,
                                  revision.quote_unit_basis_id, cutoff)
            if factor is not None:
                amount = _exact_decimal(Fraction(right.quantity) * factor
                                        * Fraction(Decimal(revision.quoted_amount))
                                        / revision.quoted_units)
        lines.append(ValuationLine(right.event_id, right.position_id,
                                    revision.revision_id if revision else None, amount))
    complete = all(line.amount is not None for line in lines)
    total = _exact_decimal(sum((Fraction(line.amount) for line in lines), Fraction(0))) if complete else None
    status = 'COMPLETE' if complete else ('HALT_UNRESOLVED_VALUATION'
                if mode == 'decision' else 'INCOMPLETE_FINAL_AMOUNTS')
    return Valuation(as_of, mode, tuple(lines), total, status)


def record_decision(snapshot, book, *, decision_at):
    if book.decisions and instant(decision_at) <= instant(book.decisions[-1].as_of):
        raise ValueError('decision history must advance strictly')
    frame = value_rights(snapshot, book, as_of=decision_at, mode='decision')
    if any(f.status != 'COMPLETE' for f in book.decisions):
        raise ValueError('halted comparison cannot resume; start a separate experiment')
    previous = {(l.event_id, l.position_id): l for l in
                (book.decisions[-1].lines if book.decisions else ())}
    changes = []
    for line in frame.lines:
        old = previous.get((line.event_id, line.position_id))
        if old != line:
            delta = (_exact_decimal(Fraction(line.amount)-Fraction(old.amount))
                     if old is not None and line.amount is not None and old.amount is not None else None)
            changes.append(Change(decision_at, line.event_id, line.position_id,
                                  old.revision_id if old else None, line.revision_id,
                                  old.amount if old else None, line.amount, delta))
    return replace(book, decisions=book.decisions+(frame,),
                   changes=book.changes+tuple(changes))


def decision_history_sha256(book):
    return hashlib.sha256(json.dumps([asdict(f) for f in book.decisions],
                        sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()
