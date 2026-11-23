"""Local immutable synthetic experiment registration and one-attempt execution."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import pydantic

from stock_ai.backtest.evaluation_v3 import AccountingError, evaluate_v3
from stock_ai.backtest.swing import SwingConfig
from stock_ai.backtest.swing_v3 import run_swing_v3
from stock_ai.data.swing_v3_schema import load_snapshot


@dataclass(frozen=True)
class Case:
    case_id: str
    strategy: str
    priority: tuple[str, ...]
    config: SwingConfig = SwingConfig()


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _jsonable(value):
    if is_dataclass(value):return _jsonable(asdict(value))
    if isinstance(value,Decimal):return str(value)
    if isinstance(value,dict):return {k:_jsonable(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [_jsonable(v) for v in value]
    return value


def _write_new(path,value):
    """Atomic, exclusive publication; never replace an existing artifact."""
    path=Path(path)
    fd,name=tempfile.mkstemp(prefix='.pending-',dir=path.parent)
    temporary=Path(name)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(_jsonable(value),stream,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.link(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def _runtime():
    return dict(python=list(sys.version_info[:3]),pydantic=pydantic.__version__)


def _code_hashes():
    root=Path(__file__).resolve().parents[3]
    names=['backtest/experiment_v3.py','backtest/evaluation_v3.py','backtest/swing_v3.py',
           'backtest/terminal_v3.py','backtest/positions_v3.py','backtest/cash_v3.py',
           'backtest/entitlement_v3.py','data/swing_v3_schema.py','backtest/swing.py',
           'features/technical.py']
    paths=[root/'src/stock_ai'/name for name in names]
    paths += [root/name for name in ('pyproject.toml','uv.lock','scripts/run_synthetic_swing_v3.py') if (root/name).is_file()]
    return {str(p.relative_to(root)):_hash(p.read_bytes()) for p in paths}


def _fixed_profiles():
    base=SwingConfig()
    return (base,replace(base,spread_bps=0,slippage_bps=0),
            replace(base,spread_bps=16,slippage_bps=2),
            replace(base,trade_risk_yen=50),replace(base,trade_risk_yen=200))


def create_registration(directory,*,experiment_id,raw,snapshot_sha256,as_of,
                         source_blobs,cases,max_runs):
    snapshot=load_snapshot(raw,sha256=snapshot_sha256,as_of=as_of,source_blobs=source_blobs)
    cases=tuple(cases)
    identifier=lambda value:isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value)
    if (not identifier(experiment_id) or not cases or len(cases)>450
            or type(max_runs) is not int or not 1<=max_runs<=len(cases)):
        raise ValueError('invalid fixed experiment budget')
    ids=set();plans=set()
    for c in cases:
        if (not isinstance(c,Case) or not identifier(c.case_id) or c.case_id in ids
                or c.strategy not in ('cash','hold','A','B','C')
                or len(c.priority)!=len(set(c.priority)) or set(c.priority)!=set(snapshot.symbols)
                or not isinstance(c.config,SwingConfig)
                or any(type(v) is bool for v in asdict(c.config).values())
                or c.config not in _fixed_profiles()
                or c.priority!=cases[0].priority):
            raise ValueError('invalid fixed experiment case')
        ids.add(c.case_id)
        plan=asdict(c);plan.pop('case_id')
        signature=json.dumps(plan,sort_keys=True,allow_nan=False)
        if signature in plans:raise ValueError('duplicate parameter set under different case IDs')
        plans.add(signature)
    root=Path(directory);root.mkdir(exist_ok=False)
    (root/'attempts').mkdir();(root/'outcomes').mkdir()
    with (root/'input.json').open('xb') as f:f.write(raw)
    blobs={}
    for i,s in enumerate(sorted(snapshot.sources,key=lambda s:s.source_id)):
        name=f'source-{i:04d}.bin';blob=source_blobs[s.source_id]
        with (root/name).open('xb') as f:f.write(blob)
        blobs[s.source_id]=dict(path=name,sha256=_hash(blob))
    registration=dict(schema='stock-ai-v3-experiment-synthetic-1',experiment_id=experiment_id,
        created_at=datetime.now(timezone.utc).isoformat(),synthetic=True,real_data_enabled=False,
        evidence_label='synthetic_not_market_evidence',snapshot_sha256=snapshot_sha256,
        as_of=as_of,sources=blobs,symbols=snapshot.symbols,
        period=[snapshot.evaluation_start_session,snapshot.evaluation_end_session],
        cases=[asdict(c) for c in cases],max_runs=max_runs,code_sha256=_code_hashes(),runtime=_runtime())
    _write_new(root/'registration.json',registration)
    _write_new(root/'registration-sha256.json',{'sha256':_hash((root/'registration.json').read_bytes())})
    return registration


@contextmanager
def _locked(root):
    with (root/'.lock').open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise ValueError('experiment busy') from exc
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def _file(root,name):
    path=(root/name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('registered file missing or outside experiment directory')
    return path


def execute_registered(directory,*,case_id):
    root=Path(directory)
    with _locked(root):
        raw_registration=(root/'registration.json').read_bytes()
        anchor=json.loads((root/'registration-sha256.json').read_text())
        if _hash(raw_registration)!=anchor['sha256']:raise ValueError('registration SHA-256 mismatch')
        registration=json.loads(raw_registration)
        if (registration.get('schema')!='stock-ai-v3-experiment-synthetic-1'
                or registration.get('synthetic') is not True or registration.get('real_data_enabled') is not False):
            raise ValueError('real or unsupported registration disabled')
        cases=[c for c in registration['cases'] if c['case_id']==case_id]
        if len(cases)!=1:raise ValueError('case was not registered')
        attempt=root/'attempts'/(case_id+'.json')
        if attempt.exists():raise ValueError('case already attempted; no implicit retry')
        consumed=len(list((root/'attempts').glob('*.json')))
        if consumed>=registration['max_runs']:raise ValueError('fixed run budget exhausted')
        _write_new(attempt,dict(case_id=case_id,status='STARTED',sequence=consumed+1,
            started_at=datetime.now(timezone.utc).isoformat(),registration_sha256=anchor['sha256']))
        stage='preflight';result=None;evaluation=None;failure_reason='registered_code_or_runtime_changed'
        try:
            if _code_hashes()!=registration['code_sha256'] or _runtime()!=registration['runtime']:
                raise ValueError('registered code or runtime changed')
            failure_reason='registered_source_files_invalid'
            blobs={identifier:_file(root,s['path']).read_bytes() for identifier,s in registration['sources'].items()}
            if any(_hash(blobs[identifier])!=s['sha256'] for identifier,s in registration['sources'].items()):
                raise ValueError('source SHA-256 mismatch')
            failure_reason='registered_snapshot_invalid'
            snapshot=load_snapshot(_file(root,'input.json').read_bytes(),
                sha256=registration['snapshot_sha256'],as_of=registration['as_of'],source_blobs=blobs)
            c=cases[0];cfg=SwingConfig(**c['config']);stage='simulation';failure_reason='v3_simulation_failed'
            result=run_swing_v3(snapshot,as_of=registration['as_of'],source_blobs=blobs,
                                strategy=c['strategy'],priority=c['priority'],config=cfg)
            stage='evaluation';failure_reason='v3_evaluation_failed'
            evaluation=evaluate_v3(snapshot,result,as_of=registration['as_of'])
            outcome=dict(status='COMPLETED' if result['complete'] else 'STOPPED',result=result,evaluation=evaluation)
        except Exception as exc:
            # Do not echo source contents, credentials or arbitrary exception payloads.
            outcome=dict(status='FAILED',stage=stage,error_type=type(exc).__name__,
                         reason=str(exc) if isinstance(exc,AccountingError) else failure_reason,
                         result=result,evaluation=None)
        outcome.update(case_id=case_id,registration_sha256=anchor['sha256'],
            finished_at=datetime.now(timezone.utc).isoformat(),synthetic=True,qualified_for_real_data=False)
        _write_new(root/'outcomes'/(case_id+'.json'),outcome)
        return _jsonable(outcome)


def save_all_excluded(path,*,experiment_id,candidates,reasons):
    """Preserve externally determined exclusions without creating PnL or a run."""
    candidates=tuple(candidates)
    if (not experiment_id or not candidates or len(candidates)!=len(set(candidates))
            or set(reasons)!=set(candidates)
            or any(not values or isinstance(values,str) or any(not isinstance(r,str) or not r.strip() for r in values)
                   for values in reasons.values())):
        raise ValueError('complete nonempty candidate exclusion reasons required')
    report=dict(status='ALL_EXCLUDED',experiment_id=experiment_id,candidates=candidates,
                reasons=reasons,metrics=None,run_count=0,qualified_for_real_data=False,
                note='Reasons supplied by preflight; this record does not certify source evidence.')
    _write_new(Path(path),report)
    return report
