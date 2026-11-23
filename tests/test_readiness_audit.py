"""Synthetic inventory fixtures; the delegated raw auditor has its own tests."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from stock_ai.data.readiness_audit import audit_readiness
from stock_ai.data.official_inventory import CANDIDATES
from test_coverage_inventory import inputs, run, sha


def save(path, data):
    path.write_text(json.dumps(data))


@pytest.fixture
def bundle(inputs):
    root = inputs['root']
    holidays = root/'holidays.csv'
    holidays.write_bytes(holidays.read_bytes() +
                         ''.join(f'2024/1/{i},fixture\n' for i in range(1, 17)).encode('cp932'))
    cal = json.loads(inputs['calendar'].read_text())
    cal['sources'][0].update(sha256=sha(holidays), bytes=holidays.stat().st_size)
    save(inputs['calendar'], cal)
    index = root/'index.json'
    save(index, inputs['snapshots'])
    coverage = run(inputs)
    coverage['snapshot_index_sha256'] = sha(index)
    cp = root/'coverage.json'
    save(cp, coverage)
    report = dict(role='consolidated_research_readiness_not_profitability',
                  status='NO_ADOPTED_STRATEGY_EVIDENCE_INCOMPLETE',
                  created_at='2026-11-21T12:00:00+00:00', adopted_strategies=[],
                  untouched_period=None, qualified_real_pnl_runs=0,
                  new_real_pnl_runs_this_step=0,
                  input_sha256={'coverage.json': sha(cp), 'index.json': sha(index)},
                  inventory=[dict(symbol=s, expected_sessions=5, raw_available=1,
                                  raw_missing=4, independently_price_checked=1,
                                  warmup_extra_missing=60, combined_missing_sessions=64,
                                  eligible_for_real_pnl=False,
                                  exclusion_reasons=['synthetic_incomplete']) for s in CANDIDATES])
    rp = root/'readiness.json'
    save(rp, report)
    return dict(source_root=root, readiness_path=rp, coverage_path=cp,
                config_path=inputs['config'], calendar_path=inputs['calendar'],
                snapshot_index_path=index, as_of='2026-11-21T13:00:00+00:00')


def audit(bundle):
    return audit_readiness(**bundle, readiness_sha256=sha(bundle['readiness_path']))


def edit_report(bundle, change):
    p = bundle['readiness_path']
    report = json.loads(p.read_text())
    change(report)
    save(p, report)


def test_recomputed_coverage_and_warmup_are_repeatable_but_never_qualify(bundle):
    result = audit(bundle)
    assert result == audit(bundle)
    assert not result['qualified_for_real_data'] and result['pnl_runs_this_audit'] == 0
    for row in result['inventory']:
        assert row['combined_missing_sessions'] == 64
        assert row['warmup_periods']['development']['required'] == 60
        assert row['warmup_periods']['development']['raw_available'] == 0
        assert len(row['warmup_periods']['development']['missing_sessions']) == 60


def test_wrong_trusted_report_hash_refused(bundle):
    with pytest.raises(ValueError, match='SHA'):
        audit_readiness(**bundle, readiness_sha256='0'*64)


def test_changed_referenced_file_refused(bundle):
    bundle['snapshot_index_path'].write_text('[]')
    with pytest.raises(ValueError, match='SHA'):
        audit(bundle)


@pytest.mark.parametrize('field,value', [
    ('raw_available', 5), ('raw_missing', 0), ('warmup_extra_missing', 0),
    ('combined_missing_sessions', 4), ('expected_sessions', 1),
    ('independently_price_checked', True),
])
def test_rehashed_summary_cannot_forge_counts(bundle, field, value):
    edit_report(bundle, lambda r:r['inventory'][0].update({field:value}))
    with pytest.raises(ValueError, match='counts differ'):
        audit(bundle)


@pytest.mark.parametrize('change', [
    lambda r:r['inventory'][0].update(eligible_for_real_pnl=True),
    lambda r:r['inventory'][0].update(exclusion_reasons=[]),
    lambda r:r.update(qualified_real_pnl_runs=True),
    lambda r:r.update(qualified_real_pnl_runs=1),
    lambda r:r.update(adopted_strategies=['A']),
    lambda r:r.update(untouched_period=['2025-01-01','2025-12-31']),
])
def test_unverified_success_or_adoption_claim_refused(bundle, change):
    edit_report(bundle, change)
    with pytest.raises(ValueError, match='claim|blocked candidate'):
        audit(bundle)


@pytest.mark.parametrize('change', [
    lambda r:r['inventory'].reverse(),
    lambda r:r['inventory'].append(r['inventory'][0]),
    lambda r:r['inventory'][1].update(symbol='1475'),
])
def test_missing_duplicate_or_reordered_candidates_refused(bundle, change):
    edit_report(bundle, change)
    with pytest.raises(ValueError, match='candidates'):
        audit(bundle)


def test_duplicate_json_keys_refused(bundle):
    p = bundle['readiness_path']
    p.write_text(p.read_text()[:-1] + ',"adopted_strategies":[]}')
    with pytest.raises(ValueError, match='duplicate JSON'):
        audit(bundle)


def test_escaping_evidence_path_refused(bundle):
    edit_report(bundle, lambda r:r['input_sha256'].update({'../outside':'0'*64}))
    with pytest.raises(ValueError, match='outside repository'):
        audit(bundle)


def test_symlink_evidence_escape_refused(bundle, tmp_path):
    outside = tmp_path.parent/(tmp_path.name+'-outside')
    outside.write_text('external')
    (tmp_path/'linked').symlink_to(outside)
    edit_report(bundle, lambda r:r['input_sha256'].update({'linked':sha(outside)}))
    with pytest.raises(ValueError, match='outside repository'):
        audit(bundle)


def test_two_names_cannot_alias_same_evidence(bundle):
    edit_report(bundle, lambda r:r['input_sha256'].update({'./index.json':sha(bundle['snapshot_index_path'])}))
    with pytest.raises(ValueError, match='alias'):
        audit(bundle)


def test_report_not_yet_observed_refused(bundle):
    bundle['as_of']='2026-11-21T11:30:00+00:00'
    with pytest.raises(ValueError, match='report not observed'):
        audit(bundle)


def test_rehashed_coverage_not_accepted_without_raw_recomputation(bundle):
    cp=bundle['coverage_path'];c=json.loads(cp.read_text())
    c['inventory']['1475']['raw_available']=5;save(cp,c)
    edit_report(bundle,lambda r:r['input_sha256'].update({'coverage.json':sha(cp)}))
    with pytest.raises(ValueError,match='original-source recomputation'):
        audit(bundle)


def test_changed_calendar_original_refused(bundle):
    (bundle['source_root']/'holidays.csv').write_text('broken')
    with pytest.raises(ValueError,match='SHA'):
        audit(bundle)


def test_insufficient_extended_calendar_refused(bundle):
    path=bundle['source_root']/'holidays.csv'
    path.write_bytes(('国民の祝日・休日月日,国民の祝日・休日名称\n'+
                      ''.join(f'2025/1/{i},fixture\n' for i in range(1,17))).encode('cp932'))
    cal=json.loads(bundle['calendar_path'].read_text())
    cal['sources'][0].update(sha256=sha(path),bytes=path.stat().st_size)
    save(bundle['calendar_path'],cal)
    cp=bundle['coverage_path'];c=json.loads(cp.read_text())
    c['calendar_sha256']=sha(bundle['calendar_path']);save(cp,c)
    edit_report(bundle,lambda r:r['input_sha256'].update({'coverage.json':sha(cp)}))
    with pytest.raises(ValueError,match='holiday year absent'):
        audit(bundle)


def test_unregistered_selected_index_refused(bundle):
    edit_report(bundle,lambda r:r['input_sha256'].pop('index.json'))
    with pytest.raises(ValueError,match='not in evidence'):
        audit(bundle)


def test_cli_output_is_exclusive_and_contains_no_profitability(bundle, monkeypatch):
    script=Path(__file__).resolve().parents[1]/'scripts/audit_swing_readiness.py'
    spec=importlib.util.spec_from_file_location('readiness_cli',script)
    cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    cli.ROOT=bundle['source_root']
    output=bundle['source_root']/'output.json'
    args=[str(script),'--readiness-sha256',sha(bundle['readiness_path'])]
    for k in ('readiness','coverage','config','calendar','snapshot-index'):
        source=bundle[k.replace('-','_')+'_path']
        args.extend(['--'+k,str(source)])
    args.extend(['--as-of',bundle['as_of'],'--output',str(output)])
    monkeypatch.setattr(sys,'argv',args)
    cli.main()
    assert json.loads(output.read_text())['qualified_for_real_data'] is False
    original=output.read_bytes()
    with pytest.raises(FileExistsError):cli.main()
    assert output.read_bytes()==original
