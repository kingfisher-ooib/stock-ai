"""Immutable synthetic v3 input contract; never a real-data execution permit."""
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


Name = Annotated[str, Field(min_length=1, max_length=160)]
Money = Annotated[str, Field(pattern=r'^(0|[1-9][0-9]*)(\.[0-9]+)?$', max_length=64)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]


def instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone required')
    return parsed


def day(value):
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError('canonical ISO date required')
    return value


class Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', strict=True)

    @field_validator('*')
    @classmethod
    def dates_and_times(cls, value, info):
        if value is not None:
            if info.field_name.endswith('_at'):
                instant(value)
            elif info.field_name.endswith(('_date', '_session')):
                day(value)
        return value


class Source(Record):
    source_id: Name
    origin: Literal['synthetic', 'official']
    locator: Name
    sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    retrieved_at: str
    document_date: str
    available_at: str
    availability_basis: Literal['synthetic', 'observed', 'documented_publication',
                                'historical_assumption', 'unconfirmed']


class Sourced(Record):
    source_id: Name
    available_at: str


class UnitBasis(Sourced):
    basis_id: Name
    symbol: Name
    effective_session: str


class Bar(Sourced):
    symbol: Name
    session_date: str
    unit_basis_id: Name
    open: Money
    high: Money
    low: Money
    close: Money
    volume: PositiveInt


class LotRule(Sourced):
    symbol: Name
    effective_session: str
    size: PositiveInt


class SplitEvent(Sourced):
    event_id: Name
    symbol: Name
    ratio_new_per_old: Money
    market_switch_date: str
    legal_effective_date: str
    split_record_date: str
    from_basis_id: Name
    to_basis_id: Name


class Entitlement(Sourced):
    event_id: Name
    symbol: Name
    last_cum_session: str
    ex_session: str
    distribution_record_date: str
    quote_unit_basis_id: Name
    date_evidence: Literal['direct', 'definition', 'calendar_candidate']


class AmountRevision(Sourced):
    revision_id: Name
    event_id: Name
    supersedes_revision_id: Name | None
    quoted_amount: Money
    quoted_units: PositiveInt
    quote_unit_basis_id: Name
    status: Literal['estimate', 'final', 'correction']


class CashEvidence(Sourced):
    event_id: Name
    scheduled_payment_date: str | None
    cash_available_at: str | None
    status: Literal['schedule_only', 'observed', 'explicit_research_assumption']
    amount: Money


class SyntheticExecutionRule(Sourced):
    symbol: Name
    start_session: str
    end_session: str
    tick_yen: Money
    fee_per_side: Money
    spread_bps: Money
    slippage_bps: Money
    assumption_id: Name


class Snapshot(Record):
    schema_version: Literal['stock-ai-swing-v3-synthetic-1']
    synthetic: Literal[True]
    calendar_source_id: Name
    sessions: tuple[str, ...]
    symbols: tuple[Name, ...]
    evaluation_start_session: str
    evaluation_end_session: str
    sources: tuple[Source, ...]
    unit_bases: tuple[UnitBasis, ...]
    bars: tuple[Bar, ...]
    lots: tuple[LotRule, ...]
    splits: tuple[SplitEvent, ...]
    entitlements: tuple[Entitlement, ...]
    amount_revisions: tuple[AmountRevision, ...]
    cash_evidence: tuple[CashEvidence, ...]
    execution_rules: tuple[SyntheticExecutionRule, ...]

    @property
    def qualified_for_real_data(self):
        return False


def _unique(records, key):
    result = {}
    for record in records:
        identifier = key(record)
        if identifier in result:
            raise ValueError('duplicate identifier')
        result[identifier] = record
    return result


def validate_snapshot(snapshot, *, as_of, source_blobs):
    """Check hashes of explicitly supplied bytes, without opening source locators.

    A snapshot may include later revisions; decision_view separately filters them.
    Passing checks is not certification of a calendar or a source's authenticity.
    """
    boundary = instant(as_of)
    sessions = snapshot.sessions
    if (not sessions or any(day(d) != d for d in sessions)
            or list(sessions) != sorted(set(sessions))
            or not snapshot.symbols or len(set(snapshot.symbols)) != len(snapshot.symbols)):
        raise ValueError('invalid sessions or universe')
    start, end = snapshot.evaluation_start_session, snapshot.evaluation_end_session
    if start not in sessions or end not in sessions or start > end or sessions.index(start) < 60:
        raise ValueError('complete period and 60 preceding sessions required')
    sources = _unique(snapshot.sources, lambda r: r.source_id)
    if snapshot.calendar_source_id not in sources:
        raise ValueError('calendar source missing')
    for s in sources.values():
        if s.origin != 'synthetic' or s.availability_basis != 'synthetic':
            raise ValueError('synthetic source provenance required; real input disabled')
        if max(instant(s.retrieved_at), instant(s.available_at)) > boundary:
            raise ValueError('source outside snapshot as-of')
        blob = source_blobs.get(s.source_id)
        if not isinstance(blob, bytes) or hashlib.sha256(blob).hexdigest() != s.sha256:
            raise ValueError('source SHA-256 mismatch or missing bytes')
    collections = (snapshot.unit_bases, snapshot.bars, snapshot.lots, snapshot.splits,
                   snapshot.entitlements, snapshot.amount_revisions,
                   snapshot.cash_evidence, snapshot.execution_rules)
    for records in collections:
        for r in records:
            if r.source_id not in sources:
                raise ValueError('unknown source')
            if not instant(sources[r.source_id].available_at) <= instant(r.available_at) <= boundary:
                raise ValueError('record availability outside source or snapshot boundary')
            if hasattr(r, 'symbol') and r.symbol not in snapshot.symbols:
                raise ValueError('unknown symbol')
    bases = _unique(snapshot.unit_bases, lambda r: r.basis_id)

    def basis(identifier, symbol):
        if identifier not in bases or bases[identifier].symbol != symbol:
            raise ValueError('unknown or cross-symbol unit basis')
        return bases[identifier]

    def active_basis(symbol, session):
        candidates = [b for b in bases.values() if b.symbol == symbol and b.effective_session <= session]
        if not candidates:
            raise ValueError('initial unit basis missing')
        return max(candidates, key=lambda b: b.effective_session)

    _unique(snapshot.unit_bases, lambda r: (r.symbol, r.effective_session))
    _unique(snapshot.bars, lambda r: (r.symbol, r.session_date))
    _unique(snapshot.lots, lambda r: (r.symbol, r.effective_session))
    for symbol in snapshot.symbols:
        bars = sorted((b for b in snapshot.bars if b.symbol == symbol), key=lambda b: b.session_date)
        if tuple(b.session_date for b in bars) != sessions:
            raise ValueError('missing or unexpected OHLCV sessions')
        lots = sorted((r for r in snapshot.lots if r.symbol == symbol), key=lambda r: r.effective_session)
        if not lots or lots[0].effective_session > sessions[0]:
            raise ValueError('initial lot rule missing')
        for r in lots:
            if r.effective_session > sessions[0] and r.effective_session not in sessions:
                raise ValueError('lot change outside calendar')
        for b in bars:
            if basis(b.unit_basis_id, symbol) != active_basis(symbol, b.session_date):
                raise ValueError('bar unit basis not contemporaneous')
            o, h, l, c = (Decimal(getattr(b, k)) for k in ('open', 'high', 'low', 'close'))
            if not 0 < l <= min(o, c) <= max(o, c) <= h:
                raise ValueError('invalid OHLC')
            close_cutoff = datetime.combine(date.fromisoformat(b.session_date), time(7), timezone.utc)
            if instant(b.available_at) < close_cutoff:
                raise ValueError('bar available before conservative close cutoff')
    splits = _unique(snapshot.splits, lambda r: r.event_id)
    _unique(snapshot.splits, lambda r: (r.symbol, r.market_switch_date))
    for r in splits.values():
        before, after = basis(r.from_basis_id, r.symbol), basis(r.to_basis_id, r.symbol)
        if (Decimal(r.ratio_new_per_old) <= 0 or r.market_switch_date not in sessions
                or not before.effective_session < r.market_switch_date == after.effective_session
                or r.legal_effective_date < r.split_record_date
                or r.legal_effective_date < r.market_switch_date):
            raise ValueError('invalid split dates, ratio or unit transition')
        i = sessions.index(r.market_switch_date)
        if i == 0 or active_basis(r.symbol, sessions[i-1]) != before:
            raise ValueError('split unit chain missing or ambiguous')
    for b in bases.values():
        if b.effective_session > sessions[0]:
            links = [r for r in splits.values() if r.to_basis_id == b.basis_id]
            if len(links) != 1:
                raise ValueError('unit transition lacks unique split')
    events = _unique(snapshot.entitlements, lambda r: r.event_id)
    _unique(snapshot.entitlements, lambda r: (r.symbol, r.ex_session))
    if set(events) & set(splits):
        raise ValueError('event ID reused across types')
    for r in events.values():
        if (r.ex_session not in sessions or sessions.index(r.ex_session) == 0
                or sessions[sessions.index(r.ex_session)-1] != r.last_cum_session
                or r.distribution_record_date < r.ex_session
                or r.date_evidence == 'calendar_candidate'):
            raise ValueError('unconfirmed or inconsistent entitlement dates')
        basis(r.quote_unit_basis_id, r.symbol)
    revisions = _unique(snapshot.amount_revisions, lambda r: r.revision_id)
    children = set()
    for r in revisions.values():
        if r.event_id not in events:
            raise ValueError('revision without entitlement')
        event = events[r.event_id]
        basis(r.quote_unit_basis_id, event.symbol)
        if instant(r.available_at) < instant(event.available_at):
            raise ValueError('revision predates entitlement information')
        parent = r.supersedes_revision_id
        if r.status == 'correction' and parent is None:
            raise ValueError('correction requires previous revision')
        if parent is not None:
            if (parent not in revisions or parent in children
                    or revisions[parent].event_id != r.event_id
                    or instant(revisions[parent].available_at) >= instant(r.available_at)):
                raise ValueError('invalid, cyclic or branching revision chain')
            if revisions[parent].status in ('final', 'correction') and r.status == 'estimate':
                raise ValueError('final amount cannot be downgraded to estimate')
            children.add(parent)
    for event_id in events:
        roots = [r for r in revisions.values() if r.event_id == event_id and r.supersedes_revision_id is None]
        if len(roots) > 1:
            raise ValueError('ambiguous initial amount revisions')
    _unique(snapshot.cash_evidence, lambda r: r.event_id)
    for r in snapshot.cash_evidence:
        if r.event_id not in events:
            raise ValueError('cash without entitlement')
        if r.status == 'schedule_only' and r.cash_available_at is not None:
            raise ValueError('schedule is not cash availability')
        if r.status != 'schedule_only' and r.cash_available_at is None:
            raise ValueError('explicit cash availability required')
        if (r.status == 'observed'
                and instant(r.cash_available_at) > instant(r.available_at)):
            raise ValueError('cash observation precedes cash availability')
        if ((r.scheduled_payment_date is not None and r.scheduled_payment_date < events[r.event_id].ex_session)
                or (r.cash_available_at is not None and instant(r.cash_available_at).astimezone(
                    timezone(timedelta(hours=9))).date().isoformat() < events[r.event_id].ex_session)):
            raise ValueError('cash precedes entitlement')
    for r in snapshot.execution_rules:
        if (r.start_session not in sessions or r.end_session not in sessions
                or r.start_session > r.end_session or Decimal(r.tick_yen) <= 0):
            raise ValueError('invalid synthetic execution rule')
    for symbol in snapshot.symbols:
        for session in sessions[sessions.index(start):sessions.index(end)+1]:
            if sum(r.symbol == symbol and r.start_session <= session <= r.end_session
                   for r in snapshot.execution_rules) != 1:
                raise ValueError('missing or overlapping execution rules')
    return snapshot


def _no_duplicates(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError('duplicate JSON key')
        result[k] = v
    return result


def load_snapshot(raw, *, sha256, as_of, source_blobs):
    if not isinstance(raw, bytes) or not re.fullmatch(r'[0-9a-f]{64}', sha256):
        raise ValueError('bytes and SHA-256 required')
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError('snapshot SHA-256 mismatch')
    # Check duplicates before Pydantic parses JSON arrays into immutable tuples.
    decoded = json.loads(raw, object_pairs_hook=_no_duplicates)
    if not isinstance(decoded, dict) or decoded.get('synthetic') is not True:
        raise ValueError('v3 real-data input disabled')
    snapshot = Snapshot.model_validate_json(raw)
    return validate_snapshot(snapshot, as_of=as_of, source_blobs=source_blobs)


def decision_view(snapshot, *, decision_at):
    """Filter availability only; never chooses a revision or runs a strategy."""
    cutoff = instant(decision_at)
    return {name: tuple(r for r in getattr(snapshot, name) if instant(r.available_at) <= cutoff)
            for name in ('unit_bases', 'bars', 'lots', 'splits', 'entitlements',
                         'amount_revisions', 'cash_evidence', 'execution_rules')}
