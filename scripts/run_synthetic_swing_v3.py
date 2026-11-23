"""Explicit registration/execution CLI for synthetic v3 only."""
import argparse
import json
from pathlib import Path

from stock_ai.backtest.experiment_v3 import Case, create_registration, execute_registered
from stock_ai.backtest.swing import SwingConfig


def main(argv=None):
    parser=argparse.ArgumentParser(description='合成データ専用。実市場データ・実注文には対応しません。')
    sub=parser.add_subparsers(dest='command',required=True)
    register=sub.add_parser('register')
    for name in ('input','sha256','as-of','cases','directory','experiment-id'):
        register.add_argument('--'+name,required=True)
    register.add_argument('--source',action='append',required=True,help='source_id=/explicit/path')
    register.add_argument('--max-runs',type=int,required=True)
    execute=sub.add_parser('execute')
    execute.add_argument('--directory',required=True);execute.add_argument('--case',required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='register':
            blobs={}
            for value in args.source:
                identifier,path=value.split('=',1)
                if not identifier or identifier in blobs:raise ValueError('duplicate source')
                blobs[identifier]=Path(path).read_bytes()
            declarations=json.loads(Path(args.cases).read_text())
            if not isinstance(declarations,list):raise ValueError('case list required')
            cases=[]
            for c in declarations:
                if not isinstance(c,dict) or set(c)!={'case_id','strategy','priority','config'}:
                    raise ValueError('explicit case contract required')
                if not isinstance(c['priority'],list) or not isinstance(c['config'],dict):
                    raise ValueError('explicit priority/config required')
                cases.append(Case(c['case_id'],c['strategy'],tuple(c['priority']),SwingConfig(**c['config'])))
            create_registration(args.directory,experiment_id=args.experiment_id,
                raw=Path(args.input).read_bytes(),snapshot_sha256=args.sha256,as_of=args.as_of,
                source_blobs=blobs,cases=cases,max_runs=args.max_runs)
            print(json.dumps(dict(status='REGISTERED_SYNTHETIC',directory=args.directory),ensure_ascii=False))
            return 0
        result=execute_registered(args.directory,case_id=args.case)
        print(json.dumps(dict(status=result['status'],case_id=args.case,
                              outcome=str(Path(args.directory)/'outcomes'/(args.case+'.json'))),ensure_ascii=False))
        return 0 if result['status']=='COMPLETED' else 1
    except (ValueError,TypeError,KeyError,OSError) as exc:
        # No source contents or arbitrary validation error payloads on stdout.
        parser.exit(2,f'入力・登録の検査に失敗しました ({type(exc).__name__})。\n')


if __name__=='__main__':
    raise SystemExit(main())
