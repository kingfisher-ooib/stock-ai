import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from test_swing_v3_schema import AS_OF,BLOB,fixture


def cli():
    spec=importlib.util.spec_from_file_location('synthetic_v3_cli',Path(__file__).parents[1]/'scripts/run_synthetic_swing_v3.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.main


def arguments(tmp_path,*,real=False):
    data=fixture();data['synthetic']=not real;raw=json.dumps(data).encode()
    (tmp_path/'input.json').write_bytes(raw);(tmp_path/'source.bin').write_bytes(BLOB)
    (tmp_path/'cases.json').write_text(json.dumps([dict(case_id='cash',strategy='cash',priority=data['symbols'],config={})]))
    return ['register','--input',str(tmp_path/'input.json'),'--sha256',hashlib.sha256(raw).hexdigest(),
        '--as-of',AS_OF,'--source','s='+str(tmp_path/'source.bin'),'--cases',str(tmp_path/'cases.json'),
        '--directory',str(tmp_path/'experiment'),'--experiment-id','cli-unit','--max-runs','1']


def test_cli_requires_registration_and_persists_result(tmp_path,capsys):
    main=cli();args=arguments(tmp_path)
    assert main(args)==0
    assert main(['execute','--directory',str(tmp_path/'experiment'),'--case','cash'])==0
    assert (tmp_path/'experiment/outcomes/cash.json').is_file()
    assert 'COMPLETED' in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        main(['execute','--directory',str(tmp_path/'experiment'),'--case','cash'])
    assert error.value.code==2


def test_cli_real_input_is_rejected_without_registration(tmp_path):
    with pytest.raises(SystemExit) as error:cli()(arguments(tmp_path,real=True))
    assert error.value.code==2 and not (tmp_path/'experiment').exists()


def test_cli_failed_execution_returns_nonzero(tmp_path):
    main=cli();assert main(arguments(tmp_path))==0
    (tmp_path/'experiment/source-0000.bin').write_bytes(b'changed synthetic data')
    assert main(['execute','--directory',str(tmp_path/'experiment'),'--case','cash'])==1
