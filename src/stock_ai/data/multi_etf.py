"""Fail-closed versioned JSON input; no network access or source mutation."""
import hashlib
import json
from datetime import date, datetime, time, timezone
from math import isfinite
from pathlib import Path


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone required')
    return result


def _synthetic_provenance_reasons(data):
    """Consistency guard, not proof that arbitrary caller-supplied data is genuine."""
    reasons = []
    source = data.get('calendar_source')
    if not isinstance(source, str) or not source.startswith('synthetic '):
        reasons.append('synthetic_calendar_origin')
    if data.get('not_verified'):
        reasons.append('unverified_market_data_marker')
    fixture_sources = ('synthetic', 'synthetic fixture')
    for instrument in data['instruments'].values():
        if any(b.get('source') != 'synthetic fixture' for b in instrument['bars']):
            reasons.append('synthetic_bar_origin')
        if any(e.get('source') not in fixture_sources for e in instrument['actions']):
            reasons.append('synthetic_action_origin')
        if any(e.get('source') not in fixture_sources for e in instrument['lots'] if 'source' in e):
            reasons.append('synthetic_lot_origin')
    return sorted(set(reasons))


def audit_dataset(data):
    if type(data.get('synthetic', False)) is not bool:
        raise ValueError('synthetic flag must be boolean')
    if data.get('synthetic') and _synthetic_provenance_reasons(data):
        raise ValueError('synthetic provenance conflicts with input sources')
    calendar = data['calendar']
    if not calendar or calendar != sorted(set(calendar)):
        raise ValueError('invalid calendar')
    for day in calendar:
        date.fromisoformat(day)
    if not data.get('calendar_source'):
        raise ValueError('calendar source required')
    if not data.get('synthetic') and data.get('availability_mode') not in ('observed', 'historical_assumption'):
        raise ValueError('explicit availability mode required')
    if not data['instruments']:
        raise ValueError('empty universe')
    for symbol, instrument in data['instruments'].items():
        bars = instrument['bars']
        if [b['bar_date'] for b in bars] != calendar:
            raise ValueError(f'{symbol}: missing, duplicate or unexpected sessions')
        if instrument.get('price_basis') != 'raw':
            raise ValueError('raw contemporaneous prices required')
        lots = instrument['lots']
        if (not lots or lots != sorted(lots, key=lambda x: x['date'])
                or len({x['date'] for x in lots}) != len(lots)
                or lots[0]['date'] > calendar[0]):
            raise ValueError('lot history required')
        for event in lots:
            date.fromisoformat(event['date'])
            if type(event['size']) is not int or event['size'] < 1:
                raise ValueError('invalid lot')
            if 'known_at' in event:
                timestamp(event['known_at'])
        for bar in bars:
            o, h, l, c, v = [float(bar[k]) for k in ('open','high','low','close','volume')]
            if not all(isfinite(x) for x in (o,h,l,c,v)) or not 0 < l <= min(o,c) <= max(o,c) <= h or v <= 0 or not v.is_integer():
                raise ValueError('invalid OHLCV')
            observed = timestamp(bar['observed_at'])
            cutoff = datetime.combine(date.fromisoformat(bar['bar_date']), time(7), timezone.utc)
            if observed < cutoff or not bar.get('source'):
                raise ValueError('invalid observation or source')
        for event in instrument['actions']:
            if event['kind'] not in ('split','distribution') or event['date'] not in calendar:
                raise ValueError('invalid action date/type')
            if not event.get('source'):
                raise ValueError('action source required')
            timestamp(event['known_at'])
            value = event['ratio'] if event['kind'] == 'split' else event['amount']
            if not isfinite(value) or value <= 0:
                raise ValueError('invalid action value')
            if event['kind'] == 'distribution':
                if date.fromisoformat(event['pay_date']) < date.fromisoformat(event['date']):
                    raise ValueError('invalid payment date')
        dates = [e['date'] for e in instrument['actions']]
        if len(dates) != len(set(dates)):
            raise ValueError('multiple same-day actions require explicit ordering; unsupported')
    return True


def lot_at(instrument, day):
    return [e['size'] for e in instrument['lots'] if e['date'] <= day][-1]


def history_at(instrument, index):
    """Only splits effective by this decision; future splits never normalize inputs."""
    bars = [dict(b) for b in instrument['bars'][:index+1]]
    day = bars[-1]['bar_date']
    for event in instrument['actions']:
        if event['kind'] == 'split' and event['date'] <= day:
            for bar in bars:
                if bar['bar_date'] < event['date']:
                    for key in ('open','high','low','close'):
                        bar[key] /= event['ratio']
                    bar['volume'] *= event['ratio']
    return bars


def load_dataset(path, *, sha256, as_of):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError('SHA-256 mismatch')
    data = json.loads(raw)
    audit_dataset(data)
    boundary = timestamp(as_of)
    # Check every recorded observation/knowledge time, without truncating coverage.
    # Legacy lots have no knowledge timestamp; this cannot establish their PIT provenance.
    if any(timestamp(b['observed_at']) > boundary for i in data['instruments'].values() for b in i['bars']):
        raise ValueError('snapshot not yet observed as of requested time')
    if any(timestamp(e['known_at']) > boundary for i in data['instruments'].values() for e in i['actions']):
        raise ValueError('corporate action not yet known as of requested time')
    if any(timestamp(e['known_at']) > boundary for i in data['instruments'].values()
           for e in i['lots'] if 'known_at' in e):
        raise ValueError('lot metadata not yet known as of requested time')
    return data


def quality_reasons(data, instrument):
    if type(data.get('synthetic', False)) is not bool:
        return ['invalid_synthetic_flag']
    if data.get('synthetic'):
        return _synthetic_provenance_reasons(data)
    checks = ('ohlcv_verified','calendar_verified','lot_history_verified',
              'actions_complete','distributions_complete','execution_cost_verified')
    return [key for key in checks if instrument.get('verification', {}).get(key) is not True
            or not instrument.get('verification_evidence', {}).get(key)]
