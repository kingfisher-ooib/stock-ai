"""Inventory fixed research periods from original local sources; never run PnL."""
from datetime import date
import hashlib
import json
from pathlib import Path

import yaml

from stock_ai.data.jquants_audit import audit_jquants_day, _object, _prices
from stock_ai.data.jquants_range import audit_jquants_range
from stock_ai.data.market_calendar import spot_sessions
from stock_ai.data.multi_etf import timestamp
from stock_ai.data.official_inventory import CANDIDATES, verified_bytes


def _inside(root, value):
    path = Path(value)
    path = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to(root):
        raise ValueError('source path outside repository')
    return path


def _range_price_checks(root, spec, result, boundary):
    """Optional separately hashed manual evidence; never infer checks from raw presence."""
    has_path, has_hash = 'price_evidence' in spec, 'evidence_sha256' in spec
    if has_path != has_hash:
        raise ValueError('range price evidence requires both path and SHA')
    if not has_path:
        return set()
    evidence = json.loads(verified_bytes(_inside(root, spec['price_evidence']),
                                        spec['evidence_sha256']), object_pairs_hook=_object)
    if 'checked_at' in evidence and timestamp(evidence['checked_at']) > boundary:
        raise ValueError('price evidence checked after as-of boundary')
    by_key = {(r['symbol'], r['date']): r for r in result['rows']}
    checked = set()
    for ref in evidence['rows']:
        key = (ref['symbol'], ref['date'])
        if key in checked or key not in by_key:
            raise ValueError('duplicate or unavailable range price evidence')
        row = by_key[key]
        if (ref.get('visually_checked') is not True
                or type(ref.get('pdf_page_one_based')) is not int or ref['pdf_page_one_based'] < 1
                or row.get('status') != 'raw_ohlcv_available'):
            raise ValueError('manually checked evidence and raw OHLCV required')
        columns = ('open','high','low','close')
        if _prices([row['ohlc'][k] for k in columns]) != _prices([ref['daily_ohlc'][k] for k in columns]):
            raise ValueError('range OHLC differs from JPX price evidence')
        checked.add(key)
    return checked


def inventory_coverage(*, source_root, config_path, config_sha256, calendar_path,
                       calendar_sha256, snapshots, as_of):
    root = Path(source_root).resolve()
    boundary = timestamp(as_of)
    config_raw = verified_bytes(config_path, config_sha256)
    config = yaml.safe_load(config_raw)
    if tuple(config['priority']) != CANDIDATES:
        raise ValueError('fixed candidate priority required')
    cal_raw = verified_bytes(calendar_path, calendar_sha256)
    cal = json.loads(cal_raw)
    if cal.get('role') != 'full_period_calendar_audit_no_price_verification_no_pnl':
        raise ValueError('unsupported calendar evidence')
    sources = cal['sources']
    if (len(sources) != 2 or {s['name'] for s in sources}
            != {'cabinet-holidays', 'jpx-session-rules'}):
        raise ValueError('calendar source pair required')
    originals = {}
    for source in sources:
        if source['status'] != 200 or timestamp(source['retrieved_at_utc']) > boundary:
            raise ValueError('calendar source not available as of boundary')
        payload = verified_bytes(_inside(root, source['path']), source['sha256'])
        if len(payload) != source['bytes']:
            raise ValueError('calendar original size mismatch')
        originals[source['name']] = payload
    rules = originals['jpx-session-rules'].decode()
    if not all(t in rules for t in ('年始3日間及び12月31日', '土曜日', '日曜日')):
        raise ValueError('JPX closure rules absent')
    first, last = cal['period']
    sessions = spot_sessions(originals['cabinet-holidays'], start=first, end=last)
    if not sessions or sessions != cal['sessions'] or len(sessions) != cal['expected_count']:
        raise ValueError('calendar sessions differ from reconstructed originals')
    periods = config['periods']
    assigned = {}
    for name, (start, end) in periods.items():
        date.fromisoformat(start)
        date.fromisoformat(end)
        if start > end or start not in sessions or end not in sessions:
            raise ValueError('period endpoints must be covered market sessions')
        for day in sessions:
            if start <= day <= end:
                if day in assigned:
                    raise ValueError('overlapping research periods')
                assigned[day] = name
    if set(assigned) != set(sessions):
        raise ValueError('research periods leave unassigned sessions')
    available = {s: set() for s in CANDIDATES}
    raw_available = {s: set() for s in CANDIDATES}
    no_trade = {s: set() for s in CANDIDATES}
    registered = {s: set() for s in CANDIDATES}
    audited = []
    for spec in snapshots:
        # Re-run the raw-source audit; saved success flags are not accepted.
        format_name = spec.get('format', 'jquants_day_v1')
        checked = set()
        if format_name == 'jquants_day_v1':
            result = audit_jquants_day(
                _inside(root, spec['directory']), manifest_sha256=spec['manifest_sha256'],
                price_evidence=_inside(root, spec['price_evidence']),
                evidence_sha256=spec['evidence_sha256'], as_of=as_of)
        elif format_name == 'jquants_range_v1':
            result = audit_jquants_range(
                _inside(root, spec['directory']), manifest_sha256=spec['manifest_sha256'],
                sessions=sessions, as_of=as_of)
            checked = _range_price_checks(root, spec, result, boundary)
        else:
            raise ValueError('unsupported snapshot format')
        for row in result['rows']:
            symbol, day = row['symbol'], row['date']
            if day not in assigned:
                raise ValueError('snapshot outside research calendar')
            if day in registered[symbol]:
                raise ValueError('duplicate snapshot day; explicitly select one version')
            registered[symbol].add(day)
            if row.get('status') == 'provider_reported_no_trade':
                no_trade[symbol].add(day)
            else:
                raw_available[symbol].add(day)
                if format_name == 'jquants_day_v1' or (symbol,day) in checked:
                    available[symbol].add(day)
        audited.append(dict(directory=spec['directory'], manifest_sha256=spec['manifest_sha256'],
                            price_evidence_sha256=spec.get('evidence_sha256'), format=format_name))
    inventory = {}
    for symbol in CANDIDATES:
        missing = [d for d in sessions if d not in available[symbol]]
        counts = {}
        for name in periods:
            expected = [d for d in sessions if assigned[d] == name]
            observed = sum(d in available[symbol] for d in expected)
            counts[name] = dict(expected=len(expected), source_audited=observed,
                                missing=len(expected)-observed,
                                raw_available=sum(d in raw_available[symbol] for d in expected),
                                provider_no_trade=sum(d in no_trade[symbol] for d in expected))
        inventory[symbol] = dict(expected=len(sessions), source_audited=len(available[symbol]),
                                  missing_count=len(missing), missing_sessions=missing,
                                  raw_available=len(raw_available[symbol]),
                                  provider_no_trade_sessions=sorted(no_trade[symbol]),
                                  raw_missing_sessions=[d for d in sessions if d not in registered[symbol]],
                                  periods=counts, qualified_for_backtest=False)
    complete = all(not i['missing_count'] for i in inventory.values())
    return dict(role='fixed_period_source_coverage_inventory_not_backtest_input',
                status='OHLCV_COVERAGE_ONLY_NOT_QUALIFIED' if complete else 'INCOMPLETE_OHLCV_COVERAGE',
                config_sha256=hashlib.sha256(config_raw).hexdigest(),
                calendar_sha256=hashlib.sha256(cal_raw).hexdigest(), as_of=boundary.isoformat(),
                periods=periods, candidate_priority=list(CANDIDATES), snapshots=audited,
                inventory=inventory, qualified_for_backtest=False, pnl_runs=0,
                limitations=['Coverage counts only explicitly registered J-Quants/JPX-price snapshots',
                             'Range raw availability is not independent price verification',
                             'Legacy Yahoo/NAV sources and other partial evidence are not counted',
                             'Calendar is retrospectively reconstructed, not a historical feed',
                             'Exceptional closures and symbol-specific halts remain unverified',
                             'Corporate actions, lots, distributions and costs remain separate gates'])
