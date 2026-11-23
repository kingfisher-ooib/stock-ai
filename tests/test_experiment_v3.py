import fcntl
import hashlib
import json

import pytest

from stock_ai.backtest.experiment_v3 import Case, create_registration, execute_registered, save_all_excluded
from stock_ai.backtest.swing import SwingConfig
from test_swing_v3_schema import AS_OF, BLOB, fixture, with_events


def register(tmp_path,data=None,*,budget=1,cases=None):
    data=data or fixture();raw=json.dumps(data).encode();root=tmp_path/'experiment'
    create_registration(root,experiment_id='unit-test',raw=raw,
        snapshot_sha256=hashlib.sha256(raw).hexdigest(),as_of=AS_OF,source_blobs={'s':BLOB},
        cases=cases or [Case('cash','cash',tuple(data['symbols']))],max_runs=budget)
    return root


def test_exclusive_registration_and_no_implicit_second_attempt(tmp_path):
    root=register(tmp_path);manifest=(root/'registration.json').read_bytes()
    outcome=execute_registered(root,case_id='cash')
    assert outcome['status']=='COMPLETED' and outcome['evaluation']['metrics']['net_pnl_yen']=='0'
    assert not outcome['qualified_for_real_data']
    assert (root/'attempts/cash.json').is_file() and (root/'outcomes/cash.json').is_file()
    assert (root/'registration.json').read_bytes()==manifest
    with pytest.raises(ValueError,match='already attempted'):execute_registered(root,case_id='cash')
    with pytest.raises(FileExistsError):register(tmp_path)


def test_unregistered_case_and_path_traversal_never_execute(tmp_path):
    root=register(tmp_path)
    with pytest.raises(ValueError,match='not registered'):execute_registered(root,case_id='../other')
    assert not list((root/'attempts').glob('*.json'))


def test_failed_source_check_is_saved_and_consumes_fixed_budget(tmp_path):
    data=fixture();cases=[Case('one','cash',tuple(data['symbols'])),Case('two','hold',tuple(data['symbols']))]
    root=register(tmp_path,data,budget=1,cases=cases)
    (root/'source-0000.bin').write_bytes(b'changed synthetic bytes')
    outcome=execute_registered(root,case_id='one')
    assert outcome['status']=='FAILED' and outcome['stage']=='preflight' and outcome['evaluation'] is None
    assert (root/'outcomes/one.json').is_file()
    with pytest.raises(ValueError,match='budget exhausted'):execute_registered(root,case_id='two')
    with pytest.raises(ValueError,match='already attempted'):execute_registered(root,case_id='one')


def test_unknown_valuation_is_persisted_as_stopped_without_metrics(tmp_path):
    data=with_events();data['amount_revisions']=data['amount_revisions'][1:]
    data['amount_revisions'][0]['supersedes_revision_id']=None
    root=register(tmp_path,data,cases=[Case('hold','hold',tuple(data['symbols']))])
    result=execute_registered(root,case_id='hold')
    assert result['status']=='STOPPED' and result['evaluation']['metrics'] is None
    assert result['evaluation']['status']=='NOT_EVALUATED'


def test_interrupted_attempt_remains_consumed_without_fake_success(tmp_path,monkeypatch):
    root=register(tmp_path)
    def interrupted(*args,**kwargs):raise KeyboardInterrupt
    monkeypatch.setattr('stock_ai.backtest.experiment_v3.run_swing_v3',interrupted)
    with pytest.raises(KeyboardInterrupt):execute_registered(root,case_id='cash')
    assert (root/'attempts/cash.json').is_file() and not (root/'outcomes/cash.json').exists()
    with pytest.raises(ValueError,match='already attempted'):execute_registered(root,case_id='cash')


def test_changed_code_is_saved_as_failure_after_attempt_reservation(tmp_path,monkeypatch):
    root=register(tmp_path)
    monkeypatch.setattr('stock_ai.backtest.experiment_v3._code_hashes',lambda:{'changed':'0'*64})
    result=execute_registered(root,case_id='cash')
    assert result['status']=='FAILED' and result['stage']=='preflight'


def test_input_hash_mismatch_is_saved(tmp_path):
    root=register(tmp_path);data=fixture();data['bars'][0]['close']='100'
    (root/'input.json').write_text(json.dumps(data))
    result=execute_registered(root,case_id='cash')
    assert result['status']=='FAILED' and result['error_type']=='ValueError'


def test_manifest_hash_mismatch_prevents_unregistered_configuration(tmp_path):
    root=register(tmp_path);manifest=json.loads((root/'registration.json').read_text())
    manifest['max_runs']=450;(root/'registration.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='registration SHA'):execute_registered(root,case_id='cash')
    assert not list((root/'attempts').glob('*.json'))


def test_lock_prevents_competing_attempts(tmp_path):
    root=register(tmp_path)
    with (root/'.lock').open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(ValueError,match='busy'):execute_registered(root,case_id='cash')
    assert not list((root/'attempts').glob('*.json'))


@pytest.mark.parametrize('budget',[0,True,451,2])
def test_invalid_budget_cannot_create_registration(tmp_path,budget):
    with pytest.raises(ValueError):register(tmp_path,budget=budget)
    assert not (tmp_path/'experiment').exists()


def test_real_input_cannot_be_registered(tmp_path):
    data=fixture();data['synthetic']=False
    with pytest.raises(ValueError):register(tmp_path,data)
    assert not (tmp_path/'experiment').exists()


def test_evaluation_failure_is_saved_without_metrics(tmp_path,monkeypatch):
    root=register(tmp_path)
    def broken(*args,**kwargs):raise ValueError('synthetic internal failure')
    monkeypatch.setattr('stock_ai.backtest.experiment_v3.evaluate_v3',broken)
    result=execute_registered(root,case_id='cash')
    assert result['status']=='FAILED' and result['stage']=='evaluation'
    assert result['evaluation'] is None and 'synthetic internal failure' not in json.dumps(result)


def test_same_parameters_cannot_be_retried_under_another_case_id(tmp_path):
    data=fixture();priority=tuple(data['symbols'])
    with pytest.raises(ValueError,match='duplicate parameter'):
        register(tmp_path,data,budget=2,cases=[Case('one','cash',priority),Case('two','cash',priority)])
    assert not (tmp_path/'experiment').exists()


def test_all_excluded_record_has_no_metrics_or_run_and_never_overwrites(tmp_path):
    path=tmp_path/'excluded.json';kwargs=dict(experiment_id='unit-test',
        candidates=('ETF-X','ETF-Y'),reasons={'ETF-X':['missing_history'],'ETF-Y':['unknown_lot']})
    report=save_all_excluded(path,**kwargs)
    assert report['status']=='ALL_EXCLUDED' and report['metrics'] is None and report['run_count']==0
    with pytest.raises(FileExistsError):save_all_excluded(path,**kwargs)
    with pytest.raises(ValueError):save_all_excluded(tmp_path/'bad.json',experiment_id='unit-test',
        candidates=('ETF-X','ETF-Y'),reasons={'ETF-X':[]})


@pytest.mark.parametrize('config',[SwingConfig(trade_risk_yen=1000),SwingConfig(max_holding_days=1),
    SwingConfig(fee_per_side=55),SwingConfig(trade_risk_yen=50,spread_bps=0,slippage_bps=0)])
def test_unregistered_parameter_search_or_combined_sensitivity_rejected(tmp_path,config):
    data=fixture()
    with pytest.raises(ValueError):register(tmp_path,data,cases=[Case('custom','cash',tuple(data['symbols']),config)])
    assert not (tmp_path/'experiment').exists()


def test_candidate_priority_cannot_be_optimized_between_cases(tmp_path):
    data=fixture();priority=tuple(data['symbols'])
    with pytest.raises(ValueError):register(tmp_path,data,budget=2,cases=[
        Case('one','cash',priority),Case('two','hold',tuple(reversed(priority)))])
