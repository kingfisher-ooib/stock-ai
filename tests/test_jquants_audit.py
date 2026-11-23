"""Synthetic API-shaped fixtures only; no real prices or API credentials."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from stock_ai.data.jquants_audit import audit_jquants_day
from stock_ai.data.official_inventory import CANDIDATES


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def snapshot(tmp_path):
    root = tmp_path / 'raw'
    root.mkdir()
    evidence_path = tmp_path / 'prices.json'
    refs, requests = [], []
    for symbol in CANDIDATES:
        path = root / (symbol + '.json')
        path.write_text(json.dumps({'data': [dict(Code=symbol+'0', Date='2025-10-24',
                                                  O=100, H=110, L=90, C=105, Vo=1000,
                                                  AdjO=10, AdjH=11, AdjL=9, AdjC=10.5, AdjVo=10000)]}))
        refs.append(dict(symbol=symbol, date='2025-10-24', visually_checked=True,
                         pdf_page_one_based=1, daily_ohlc=dict(open=100,high=110,low=90,close=105)))
        requests.append(dict(symbol=symbol, file=path.name, bytes=path.stat().st_size,
                             sha256=digest(path), http_status=200,
                             url='https://api.jquants.com/v2/equities/bars/daily?code='+symbol+'0&date=2025-10-24',
                             requested_at='2026-11-21T10:00:00+00:00',
                             observed_at='2026-11-21T10:00:01+00:00'))
    evidence_path.write_text(json.dumps({'rows': refs}))
    manifest = dict(date='2025-10-24', price_audit_sha256=digest(evidence_path),
                    requests=requests, rows=[{'fake_cached_result': True}])
    (root/'manifest.json').write_text(json.dumps(manifest))
    return root, evidence_path


def audit(snapshot, **overrides):
    root, evidence = snapshot
    args = dict(manifest_sha256=digest(root/'manifest.json'), price_evidence=evidence,
                evidence_sha256=digest(evidence), as_of='2026-11-21T11:00:00+00:00')
    args.update(overrides)
    return audit_jquants_day(root, **args)


def edit_manifest(snapshot, change):
    path = snapshot[0]/'manifest.json'
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def edit_payload(snapshot, change):
    path = snapshot[0]/'1475.json'
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))
    def update(m):
        m['requests'][0].update(sha256=digest(path), bytes=path.stat().st_size)
    edit_manifest(snapshot, update)


def test_reproducible_raw_not_adjusted_and_never_qualified(snapshot):
    original = {p.name:p.read_bytes() for p in snapshot[0].iterdir()}
    result = audit(snapshot)
    assert result == audit(snapshot)
    assert result['rows'][0]['ohlc']['open'] == 100
    assert result['rows'][0]['volume'] == 1000
    assert result['qualified_for_backtest'] is False and result['synthetic'] is False
    assert {p.name:p.read_bytes() for p in snapshot[0].iterdir()} == original


@pytest.mark.parametrize('which', ['manifest','evidence','original'])
def test_modified_originals_or_hashes_fail(snapshot, which):
    if which == 'manifest':
        with pytest.raises(ValueError, match='SHA'):
            audit(snapshot, manifest_sha256='0'*64)
    elif which == 'evidence':
        with pytest.raises(ValueError, match='SHA'):
            audit(snapshot, evidence_sha256='0'*64)
    else:
        (snapshot[0]/'1475.json').write_text('{}')
        with pytest.raises(ValueError, match='SHA'):
            audit(snapshot)


@pytest.mark.parametrize('field,value', [('O',None),('C',True),('Vo',None),('Vo',0),
                                        ('Vo',1.5),('Vo',float('inf')),('H',80)])
def test_invalid_or_missing_ohlcv_never_filled(snapshot, field, value):
    edit_payload(snapshot, lambda p:p['data'][0].update({field:value}))
    with pytest.raises(ValueError):
        audit(snapshot)


@pytest.mark.parametrize('change', [
    lambda p:p['data'][0].update(Code='13060'),
    lambda p:p['data'][0].update(Date='2025-10-23'),
    lambda p:p['data'].append(p['data'][0].copy()),
    lambda p:p.update(data=[]),
    lambda p:p.update(pagination_key='more'),
    lambda p:p['data'][0].update(C=106),
])
def test_wrong_identity_duplicates_pagination_or_price_mismatch_fail(snapshot, change):
    edit_payload(snapshot, change)
    with pytest.raises(ValueError):
        audit(snapshot)


@pytest.mark.parametrize('change', [
    lambda m:m['requests'].pop(),
    lambda m:m['requests'].append(m['requests'][0].copy()),
    lambda m:m['requests'][0].update(http_status=403),
    lambda m:m['requests'][0].update(file='../1475.json'),
    lambda m:m['requests'][0].update(bytes=1),
    lambda m:m['requests'][0].update(url='https://example.com/data'),
    lambda m:m['requests'][0].update(url=m['requests'][0]['url']+'&x-api-key=fixture'),
    lambda m:m['requests'][0].update(observed_at='2026-11-22T10:00:00+00:00'),
    lambda m:m['requests'][0].update(observed_at='2026-11-21T09:00:00+00:00'),
    lambda m:m.update(price_audit_sha256='0'*64),
])
def test_provenance_or_time_failure_rejected(snapshot, change):
    edit_manifest(snapshot, change)
    with pytest.raises(ValueError):
        audit(snapshot)


def test_as_of_cannot_read_later_snapshot(snapshot):
    with pytest.raises(ValueError, match='as-of'):
        audit(snapshot, as_of='2025-10-24T23:00:00+00:00')


def test_symlink_cannot_escape_snapshot(snapshot, tmp_path):
    path = snapshot[0]/'1475.json'
    outside = tmp_path/'outside.json'
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match='path'):
        audit(snapshot)


def test_duplicate_json_keys_are_not_silently_overwritten(snapshot):
    path = snapshot[0]/'1475.json'
    path.write_text('{"data":[],"data":[]}')
    edit_manifest(snapshot, lambda m:m['requests'][0].update(sha256=digest(path),bytes=path.stat().st_size))
    with pytest.raises(ValueError, match='duplicate JSON'):
        audit(snapshot)


def test_unchecked_price_evidence_is_refused(snapshot):
    path = snapshot[1]
    data = json.loads(path.read_text())
    data['rows'][0]['visually_checked'] = False
    path.write_text(json.dumps(data))
    edit_manifest(snapshot, lambda m:m.update(price_audit_sha256=digest(path)))
    with pytest.raises(ValueError, match='manually checked'):
        audit(snapshot)


def cli(snapshot, output):
    repo = Path(__file__).resolve().parents[1]
    root, evidence = snapshot
    args = [sys.executable, str(repo/'scripts/audit_jquants_day.py'),
            '--directory', str(root), '--manifest-sha256', digest(root/'manifest.json'),
            '--price-evidence', str(evidence), '--price-evidence-sha256', digest(evidence),
            '--as-of', '2026-11-21T11:00:00+00:00', '--output', str(output)]
    return subprocess.run(args, env={**os.environ, 'PYTHONPATH': str(repo/'src')},
                          text=True, capture_output=True)


def test_cli_preserves_previous_output(snapshot, tmp_path):
    output = tmp_path/'audit.json'
    assert cli(snapshot, output).returncode == 0
    original = output.read_bytes()
    assert cli(snapshot, output).returncode != 0
    assert output.read_bytes() == original


def test_cli_failure_cannot_emit_success_report(snapshot, tmp_path):
    output = tmp_path/'audit.json'
    edit_payload(snapshot, lambda p:p['data'][0].update(Vo=None))
    assert cli(snapshot, output).returncode != 0
    assert not output.exists()
