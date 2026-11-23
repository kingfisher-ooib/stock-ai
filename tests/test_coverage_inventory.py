"""Generated calendar fixtures and mocked already-unit-tested source auditor."""
import hashlib
import json

import pytest
import yaml

import stock_ai.data.coverage_inventory as module
from stock_ai.data.official_inventory import CANDIDATES


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    # Synthetic holidays, not real Japanese market evidence.
    holiday = tmp_path/'holidays.csv'
    holiday.write_bytes(('国民の祝日・休日月日,国民の祝日・休日名称\n'+
                         ''.join(f'2025/1/{i},fixture\n' for i in range(1,17))).encode('cp932'))
    rules = tmp_path/'rules.html'
    rules.write_text('年始3日間及び12月31日 土曜日 日曜日')
    sessions = ['2025-10-'+str(i) for i in range(20,25)]
    sources = [dict(name=name, path=p.name, sha256=sha(p), bytes=p.stat().st_size,
                    status=200, retrieved_at_utc='2026-11-21T00:00:00+00:00')
               for name,p in [('cabinet-holidays', holiday), ('jpx-session-rules', rules)]]
    cal = tmp_path/'calendar.json'
    cal.write_text(json.dumps(dict(role='full_period_calendar_audit_no_price_verification_no_pnl',
                                   sources=sources, period=[sessions[0],sessions[-1]],
                                   sessions=sessions, expected_count=5)))
    cfg = tmp_path/'config.yaml'
    cfg.write_text(yaml.safe_dump(dict(priority=list(CANDIDATES),
                                      periods={'development':[sessions[0],sessions[-1]]})))
    def auditor(*args, **kwargs):
        return dict(rows=[dict(symbol=s, date='2025-10-24') for s in CANDIDATES])
    monkeypatch.setattr(module, 'audit_jquants_day', auditor)
    spec = dict(directory='raw',manifest_sha256='fixture',price_evidence='prices.json',
                evidence_sha256='fixture')
    return dict(root=tmp_path, config=cfg, calendar=cal, snapshots=[spec])


def run(inputs, **overrides):
    args = dict(source_root=inputs['root'], config_path=inputs['config'],
                config_sha256=sha(inputs['config']), calendar_path=inputs['calendar'],
                calendar_sha256=sha(inputs['calendar']), snapshots=inputs['snapshots'],
                as_of='2026-11-21T11:00:00+00:00')
    args.update(overrides)
    return module.inventory_coverage(**args)


def edit(path, change):
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def test_missing_sessions_remain_explicit_and_no_backtest_qualification(inputs):
    result = run(inputs)
    assert result == run(inputs)
    assert result['qualified_for_backtest'] is False and result['pnl_runs'] == 0
    for row in result['inventory'].values():
        assert row['expected'] == 5 and row['source_audited'] == 1
        assert row['missing_sessions'] == ['2025-10-20','2025-10-21','2025-10-22','2025-10-23']
        assert row['periods']['development']['missing'] == 4


def test_empty_registry_cannot_count_legacy_prices(inputs):
    result = run(inputs, snapshots=[])
    assert all(i['source_audited'] == 0 and i['missing_count'] == 5
               for i in result['inventory'].values())


@pytest.mark.parametrize('field', ['config_sha256','calendar_sha256'])
def test_changed_input_hash_refused(inputs, field):
    with pytest.raises(ValueError, match='SHA'):
        run(inputs, **{field:'0'*64})


def test_calendar_original_mutation_refused(inputs):
    (inputs['root']/'holidays.csv').write_bytes(b'changed')
    with pytest.raises(ValueError, match='SHA'):
        run(inputs)


def test_calendar_cannot_be_shrunk_to_available_days(inputs):
    edit(inputs['calendar'], lambda d:d.update(sessions=['2025-10-24'],expected_count=1))
    with pytest.raises(ValueError, match='reconstructed'):
        run(inputs)


@pytest.mark.parametrize('periods', [
    {'dev':['2025-10-20','2025-10-22'],'val':['2025-10-22','2025-10-24']},
    {'dev':['2025-10-20','2025-10-21'],'val':['2025-10-23','2025-10-24']},
    {'dev':['2025-10-19','2025-10-24']},
])
def test_overlapping_gapped_or_incomplete_periods_refused(inputs, periods):
    cfg = yaml.safe_load(inputs['config'].read_text())
    cfg['periods'] = periods
    inputs['config'].write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError, match='period|unassigned'):
        run(inputs)


def test_duplicate_snapshot_versions_not_silently_selected(inputs):
    with pytest.raises(ValueError, match='duplicate snapshot'):
        run(inputs, snapshots=inputs['snapshots']*2)


def test_snapshot_outside_calendar_not_used(inputs, monkeypatch):
    monkeypatch.setattr(module,'audit_jquants_day',lambda *a,**k:
                        dict(rows=[dict(symbol=s,date='2025-10-19') for s in CANDIDATES]))
    with pytest.raises(ValueError, match='outside research calendar'):
        run(inputs)


def test_raw_audit_failure_is_not_turned_into_coverage(inputs, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError('invalid original')
    monkeypatch.setattr(module,'audit_jquants_day',fail)
    with pytest.raises(ValueError, match='invalid original'):
        run(inputs)


def test_sources_not_observed_by_boundary_refused(inputs):
    with pytest.raises(ValueError, match='as of'):
        run(inputs, as_of='2026-11-20T00:00:00+00:00')


def test_snapshot_path_escape_refused(inputs):
    inputs['snapshots'][0]['directory'] = '../outside'
    with pytest.raises(ValueError, match='outside repository'):
        run(inputs)


def test_complete_price_coverage_still_does_not_qualify_strategy(inputs, monkeypatch):
    inputs['snapshots'] = [dict(inputs['snapshots'][0],directory=str(i)) for i in range(20,25)]
    def auditor(path, **kwargs):
        return dict(rows=[dict(symbol=s,date='2025-10-'+path.name) for s in CANDIDATES])
    monkeypatch.setattr(module,'audit_jquants_day',auditor)
    result = run(inputs)
    assert result['status'] == 'OHLCV_COVERAGE_ONLY_NOT_QUALIFIED'
    assert result['qualified_for_backtest'] is False
    assert all(i['missing_count'] == 0 and i['qualified_for_backtest'] is False
               for i in result['inventory'].values())


def test_range_availability_cannot_be_promoted_to_price_verification(inputs, monkeypatch):
    inputs['snapshots'][0]['format'] = 'jquants_range_v1'
    inputs['snapshots'][0].pop('price_evidence')
    inputs['snapshots'][0].pop('evidence_sha256')
    rows = [dict(symbol=s,date='2025-10-24',status='raw_ohlcv_available') for s in CANDIDATES]
    monkeypatch.setattr(module,'audit_jquants_range',lambda *a,**k:dict(rows=rows))
    result = run(inputs)
    for inv in result['inventory'].values():
        assert inv['raw_available'] == 1 and inv['source_audited'] == 0
        assert inv['missing_count'] == 5 and len(inv['raw_missing_sessions']) == 4


def test_range_no_trade_is_neither_missing_record_nor_tradable_bar(inputs, monkeypatch):
    inputs['snapshots'][0]['format'] = 'jquants_range_v1'
    inputs['snapshots'][0].pop('price_evidence')
    inputs['snapshots'][0].pop('evidence_sha256')
    rows = [dict(symbol=s,date='2025-10-24',status='provider_reported_no_trade') for s in CANDIDATES]
    monkeypatch.setattr(module,'audit_jquants_range',lambda *a,**k:dict(rows=rows))
    for inv in run(inputs)['inventory'].values():
        assert inv['raw_available'] == 0 and inv['source_audited'] == 0
        assert inv['provider_no_trade_sessions'] == ['2025-10-24']
        assert '2025-10-24' not in inv['raw_missing_sessions']


def test_unknown_snapshot_format_is_not_silently_treated_as_day(inputs):
    inputs['snapshots'][0]['format'] = 'unverified_summary'
    with pytest.raises(ValueError,match='unsupported snapshot format'):
        run(inputs)


def range_with_evidence(inputs, monkeypatch):
    spec = inputs['snapshots'][0]
    spec['format'] = 'jquants_range_v1'
    rows = [dict(symbol=s,date='2025-10-24',status='raw_ohlcv_available',
                 ohlc=dict(open=100,high=110,low=90,close=105)) for s in CANDIDATES]
    evidence = inputs['root']/'prices.json'
    evidence.write_text(json.dumps(dict(checked_at='2026-11-21T09:00:00+00:00',rows=[
        dict(symbol=s,date='2025-10-24',visually_checked=True,pdf_page_one_based=1,
             daily_ohlc=dict(open=100,high=110,low=90,close=105)) for s in CANDIDATES])))
    spec['evidence_sha256'] = sha(evidence)
    monkeypatch.setattr(module,'audit_jquants_range',lambda *a,**k:dict(rows=rows))
    return rows, evidence


def test_range_prices_are_crosschecked_only_when_evidence_matches(inputs,monkeypatch):
    range_with_evidence(inputs,monkeypatch)
    for inv in run(inputs)['inventory'].values():
        assert inv['source_audited'] == 1 and inv['raw_available'] == 1
        assert inv['missing_count'] == 4 and inv['qualified_for_backtest'] is False


def test_range_price_mismatch_refused(inputs,monkeypatch):
    rows,_ = range_with_evidence(inputs,monkeypatch)
    rows[0]['ohlc']['close'] = 106
    with pytest.raises(ValueError,match='differs'):
        run(inputs)


@pytest.mark.parametrize('change', [
    lambda e:e['rows'][0].update(visually_checked=False),
    lambda e:e['rows'].append(e['rows'][0].copy()),
    lambda e:e['rows'][0].update(date='2025-10-23'),
    lambda e:e.update(checked_at='2027-01-01T00:00:00+00:00'),
])
def test_range_unchecked_duplicate_missing_or_future_evidence_refused(inputs,monkeypatch,change):
    _,path = range_with_evidence(inputs,monkeypatch)
    edit(path,change)
    inputs['snapshots'][0]['evidence_sha256'] = sha(path)
    with pytest.raises(ValueError):
        run(inputs)


def test_range_evidence_hash_mismatch_refused(inputs,monkeypatch):
    range_with_evidence(inputs,monkeypatch)
    inputs['snapshots'][0]['evidence_sha256'] = '0'*64
    with pytest.raises(ValueError,match='SHA'):
        run(inputs)


def test_range_half_configured_evidence_refused(inputs,monkeypatch):
    range_with_evidence(inputs,monkeypatch)
    inputs['snapshots'][0].pop('price_evidence')
    with pytest.raises(ValueError,match='both path and SHA'):
        run(inputs)
