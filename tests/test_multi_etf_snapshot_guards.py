import hashlib
import json

import pytest

from stock_ai.backtest.swing import run_swing
from stock_ai.data.multi_etf import audit_dataset, load_dataset, quality_reasons
from stock_ai.data.synthetic import synthetic_dataset


def saved(tmp_path, data):
    path = tmp_path/'snapshot.json'
    path.write_text(json.dumps(data))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('kind', ['split', 'distribution'])
def test_asof_rejects_corporate_information_not_yet_known(tmp_path, kind):
    data = synthetic_dataset(symbols=('1475',))
    event = dict(kind=kind, date=data['calendar'][63], source='synthetic',
                 known_at='2027-01-01T00:00:00+00:00')
    event.update({'ratio': 2} if kind == 'split' else
                 {'amount': 2, 'pay_date': data['calendar'][70]})
    data['instruments']['1475']['actions'] = [event]
    path, sha = saved(tmp_path, data)
    with pytest.raises(ValueError, match='corporate action not yet known'):
        load_dataset(path, sha256=sha, as_of='2026-11-21T00:00:00+00:00')


def test_asof_rejects_not_yet_known_lot_metadata(tmp_path):
    data = synthetic_dataset(symbols=('1475',))
    data['instruments']['1475']['lots'][0]['known_at'] = '2027-01-01T00:00:00+00:00'
    path, sha = saved(tmp_path, data)
    with pytest.raises(ValueError, match='lot metadata not yet known'):
        load_dataset(path, sha256=sha, as_of='2026-11-21T00:00:00+00:00')


@pytest.mark.parametrize('flag', ['true', 1, None])
def test_synthetic_flag_must_be_boolean(flag):
    data = synthetic_dataset()
    data['synthetic'] = flag
    with pytest.raises(ValueError, match='synthetic flag'):
        audit_dataset(data)


@pytest.mark.parametrize('origin', ['bar', 'calendar', 'action', 'lot', 'unverified_marker'])
def test_market_data_cannot_bypass_quality_by_synthetic_flag(origin):
    data = synthetic_dataset(symbols=('1475',))
    if origin == 'bar':
        data['instruments']['1475']['bars'][0]['source'] = 'yahoo-finance'
    elif origin == 'calendar':
        data['calendar_source'] = 'yahoo-finance trading dates'
    elif origin == 'action':
        data['instruments']['1475']['actions'] = [dict(
            kind='split', date=data['calendar'][63], ratio=2,
            known_at=data['calendar'][60]+'T00:00:00+00:00', source='issuer')]
    elif origin == 'lot':
        data['instruments']['1475']['lots'][0]['source'] = 'issuer'
    else:
        data['not_verified'] = True
    assert quality_reasons(data, data['instruments']['1475'])
    with pytest.raises(ValueError, match='synthetic provenance'):
        run_swing(data, strategy='cash', start=data['calendar'][60], end=data['calendar'][-1])


def test_old_synthetic_fixture_remains_supported(tmp_path):
    data = synthetic_dataset(symbols=('1475',))
    path, sha = saved(tmp_path, data)
    assert load_dataset(path, sha256=sha, as_of='2026-11-21T00:00:00+00:00') == data
    assert quality_reasons(data, data['instruments']['1475']) == []


def test_recorded_lot_known_at_requires_timezone():
    data = synthetic_dataset()
    data['instruments']['1475']['lots'][0]['known_at'] = '2024-01-01T00:00:00'
    with pytest.raises(ValueError, match='timezone'):
        audit_dataset(data)


def test_knowledge_exactly_at_asof_is_inclusive_and_does_not_mutate(tmp_path):
    data = synthetic_dataset(symbols=('1475',))
    boundary = '2026-11-21T00:00:00+00:00'
    instrument = data['instruments']['1475']
    instrument['lots'][0]['known_at'] = boundary
    instrument['actions'] = [dict(kind='split', date=data['calendar'][63], ratio=2,
                                  known_at=boundary, source='synthetic')]
    path, sha = saved(tmp_path, data)
    before = path.read_bytes()
    assert load_dataset(path, sha256=sha, as_of=boundary) == data
    assert path.read_bytes() == before
