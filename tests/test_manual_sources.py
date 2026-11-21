import importlib.util
import json
from pathlib import Path

import pytest

from stock_ai.data.manual_sources import register_manual_source, verify_registered_source


def register(tmp_path,**overrides):
    original=tmp_path/'input.csv'
    if not original.exists():
        original.write_text('date,close\n2024-03-29,100\n')
    params=dict(source_url='https://www.jpx.co.jp/markets/statistics-equities/daily/03.html',
                observed_at='2026-11-21T00:00:00+00:00',destination=tmp_path/'registered',
                note='Synthetic test fixture, not real market evidence')
    params.update(overrides)
    return register_manual_source(original,**params)


def test_registration_keeps_original_and_never_promotes_quality(tmp_path):
    r=register(tmp_path)
    assert verify_registered_source(tmp_path/'registered')==r
    assert (tmp_path/'registered/original.csv').read_bytes()==(tmp_path/'input.csv').read_bytes()
    assert r['qualified_for_backtest'] is False
    with pytest.raises(FileExistsError):
        register(tmp_path)


def test_mutated_original_rejected(tmp_path):
    register(tmp_path)
    (tmp_path/'registered/original.csv').write_text('changed')
    with pytest.raises(ValueError,match='SHA'):
        verify_registered_source(tmp_path/'registered')


@pytest.mark.parametrize('kwargs',[dict(observed_at='2026-11-21'),dict(observed_at='2999-01-01T00:00:00+00:00'),dict(source_url='file:///tmp/a'),dict(note='')])
def test_bad_provenance_rejected_without_destination(tmp_path,kwargs):
    with pytest.raises(ValueError):
        register(tmp_path,**kwargs)
    assert not (tmp_path/'registered').exists()


def test_html_disguised_as_pdf_rejected(tmp_path):
    p=tmp_path/'source.pdf'
    p.write_bytes(b'<html>404</html>')
    with pytest.raises(ValueError,match='signature'):
        register_manual_source(p,source_url='https://www.jpx.co.jp/source.pdf',
                               observed_at='2026-11-21T00:00:00+00:00',destination=tmp_path/'dest',note='test')


def test_registered_path_cannot_escape_directory(tmp_path):
    register(tmp_path)
    p=tmp_path/'registered/manifest.json'
    r=json.loads(p.read_text())
    r['original']='../input.csv'
    p.write_text(json.dumps(r))
    with pytest.raises(ValueError,match='path'):
        verify_registered_source(tmp_path/'registered')


def test_collector_stops_automatic_historical_downloads():
    script=Path(__file__).resolve().parents[1]/'scripts/collect_multi_etf_official.py'
    spec=importlib.util.spec_from_file_location('collector_test',script)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for url in ('https://www.jpx.co.jp/markets/statistics-equities/daily/old/202403.pdf',
                'https://www.jpx.co.jp/automation/markets/statistics-equities/daily/json/tsedaily_report_202403.html'):
        with pytest.raises(ValueError): module.validate_automatic_source(url)
    assert module.validate_automatic_source('https://www.jpx.co.jp/markets/statistics-equities/daily/03.html')
