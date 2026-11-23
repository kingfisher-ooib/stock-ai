"""Recompute the current blocked research inventory; never authorize market PnL."""
from datetime import date
import json
from pathlib import Path

import yaml

from stock_ai.data.coverage_inventory import inventory_coverage
from stock_ai.data.jquants_audit import _object
from stock_ai.data.market_calendar import spot_sessions
from stock_ai.data.multi_etf import timestamp
from stock_ai.data.official_inventory import CANDIDATES, verified_bytes


def audit_readiness(*, source_root, readiness_path, readiness_sha256,
                    coverage_path, config_path, calendar_path,
                    snapshot_index_path, as_of):
    """Audit an explicitly pinned *blocked* report and its selected raw inventory.

    Hashes anchor local bytes, not the truth or historical publication time of a
    document. Extra warmup observations outside the registered fixed inventory
    are not inferred from legacy files or summaries. This function has no path
    that grants real-market qualification, even with complete price coverage.
    """
    root = Path(source_root).resolve()
    boundary = timestamp(as_of)

    def inside(value):
        path = Path(value)
        path = (root / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_relative_to(root):
            raise ValueError('source path outside repository')
        return path

    def read(value, digest):
        return json.loads(verified_bytes(inside(value), digest), object_pairs_hook=_object)

    report = read(readiness_path, readiness_sha256)
    if (report.get('role') != 'consolidated_research_readiness_not_profitability'
            or report.get('status') != 'NO_ADOPTED_STRATEGY_EVIDENCE_INCOMPLETE'):
        raise ValueError('only blocked research readiness reports supported')
    if timestamp(report['created_at']) > boundary:
        raise ValueError('report not observed by as-of boundary')
    if (report.get('adopted_strategies') != []
            or report.get('untouched_period') is not None
            or type(report.get('qualified_real_pnl_runs')) is not int
            or report['qualified_real_pnl_runs'] != 0
            or type(report.get('new_real_pnl_runs_this_step')) is not int
            or report['new_real_pnl_runs_this_step'] != 0):
        raise ValueError('unsupported qualification or adoption claim')
    pins = report['input_sha256']
    if not isinstance(pins, dict) or not pins:
        raise ValueError('nonempty evidence hash registry required')
    checked = {}
    for name, digest in pins.items():
        path = inside(name)
        canonical = str(path.relative_to(root))
        if canonical in checked:
            raise ValueError('duplicate evidence path alias')
        verified_bytes(path, digest)
        checked[canonical] = digest

    def registered(value):
        name = str(inside(value).relative_to(root))
        if name not in checked:
            raise ValueError('selected artifact not in evidence hash registry')
        return checked[name]

    coverage_hash = registered(coverage_path)
    coverage = read(coverage_path, coverage_hash)
    if timestamp(coverage['as_of']) > boundary:
        raise ValueError('coverage not observed by as-of boundary')
    index_hash = registered(snapshot_index_path)
    if coverage['snapshot_index_sha256'] != index_hash:
        raise ValueError('snapshot index differs from selected coverage')
    index = read(snapshot_index_path, index_hash)
    recomputed = inventory_coverage(
        source_root=root, config_path=inside(config_path),
        config_sha256=coverage['config_sha256'], calendar_path=inside(calendar_path),
        calendar_sha256=coverage['calendar_sha256'], snapshots=index,
        as_of=coverage['as_of'])
    recomputed['snapshot_index_sha256'] = index_hash
    if coverage != recomputed:
        raise ValueError('saved coverage differs from original-source recomputation')

    config = yaml.safe_load(verified_bytes(inside(config_path), coverage['config_sha256']))
    calendar = read(calendar_path, coverage['calendar_sha256'])
    # Reconstruct the extra leading year from the same hashed holiday original.
    # The source auditor above has already checked its provenance and observation.
    holidays = next(s for s in calendar['sources'] if s['name'] == 'cabinet-holidays')
    first_year = date.fromisoformat(calendar['period'][0]).year - 1
    extended = spot_sessions(verified_bytes(inside(holidays['path']), holidays['sha256']),
                             start=f'{first_year}-01-01', end=calendar['period'][1])
    fixed = set(calendar['sessions'])
    warmups = {}
    for name, (start, _) in config['periods'].items():
        preceding = [day for day in extended if day < start][-60:]
        if len(preceding) != 60:
            raise ValueError('insufficient calendar for 60-session warmup')
        warmups[name] = preceding
    extra = set().union(*map(set, warmups.values())) - fixed
    rows = report['inventory']
    if (not isinstance(rows, list) or len(rows) != len(CANDIDATES)
            or [row['symbol'] for row in rows] != list(CANDIDATES)):
        raise ValueError('five unique candidates in fixed priority required')
    output = []
    for row in rows:
        symbol = row['symbol']
        inv = recomputed['inventory'][symbol]
        raw_days = fixed - set(inv['raw_missing_sessions']) - set(inv['provider_no_trade_sessions'])
        expected = dict(expected_sessions=inv['expected'], raw_available=inv['raw_available'],
                        raw_missing=len(inv['raw_missing_sessions']),
                        independently_price_checked=inv['source_audited'],
                        warmup_extra_missing=len(extra),
                        combined_missing_sessions=len(inv['raw_missing_sessions']) + len(extra))
        if any(type(row.get(k)) is not int or row[k] != v for k, v in expected.items()):
            raise ValueError('readiness counts differ from source inventory or warmup')
        if row.get('eligible_for_real_pnl') is not False or not row.get('exclusion_reasons'):
            raise ValueError('blocked candidate requires explicit exclusion reasons')
        output.append(dict(symbol=symbol, **expected, warmup_periods={
            name: dict(first=sessions[0], last=sessions[-1], required=60,
                       raw_available=sum(day in raw_days for day in sessions),
                       missing_sessions=[day for day in sessions if day not in raw_days])
            for name, sessions in warmups.items()},
            eligible_for_real_pnl=False, exclusion_reasons=row['exclusion_reasons']))
    return dict(role='offline_blocked_readiness_reaudit_not_market_authorization',
                as_of=boundary.isoformat(), readiness_sha256=readiness_sha256,
                coverage_sha256=coverage_hash, checked_evidence_count=len(checked),
                original_source_coverage_recomputed=True, inventory=output,
                qualified_for_real_data=False, adopted_strategies=[], pnl_runs_this_audit=0,
                limitations=[
                    'Hash integrity is not historical availability or market-history certification',
                    'Warmup uses reconstructed general calendar, not exceptional trading-halt evidence',
                    'Only registered fixed-period observations count; extra warmup sources need explicit registration',
                    'Corporate, cash, cost and execution claims remain unqualified; no positive release path'])
