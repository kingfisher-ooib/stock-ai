"""Bounded registered comparisons; default produces an exclusion report only."""
import argparse
from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path

import yaml

from stock_ai.backtest.swing import SwingConfig, run_swing, summarize_swing
from stock_ai.data.multi_etf import load_dataset, quality_reasons
from stock_ai.data.synthetic import synthetic_dataset

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic',action='store_true')
    parser.add_argument('--input',type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--as-of')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.synthetic and args.input:
        parser.error('choose synthetic or real input')
    raw=(ROOT/'config/swing.yaml').read_bytes()
    settings=yaml.safe_load(raw)
    config=SwingConfig(**{f.name:settings[f.name] for f in fields(SwingConfig)})
    report=dict(experiment_id=settings['experiment_id'],config_sha256=hashlib.sha256(raw).hexdigest(),
                plan_sha256=hashlib.sha256((ROOT/'docs/multi-etf/plan.md').read_bytes()).hexdigest(),
                status='NO_ADOPTED_STRATEGY_DATA_INSUFFICIENT',adopted_strategies=[],
                untouched_period=None,ai_calls=0,results=[],exclusions={})
    data=None
    if args.synthetic:
        data=synthetic_dataset()
        report['status']='SYNTHETIC_IMPLEMENTATION_TEST_ONLY'
        report['input_sha256']=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    elif args.input:
        if not args.sha256 or not args.as_of:
            parser.error('--input requires --sha256 and --as-of')
        data=load_dataset(args.input,sha256=args.sha256,as_of=args.as_of)
        if data.get('synthetic'):
            parser.error('synthetic datasets must use --synthetic')
        report['input_sha256']=args.sha256
        for s in settings['priority']:
            if s not in data['instruments']:
                report['exclusions'][s]=['missing instrument']
            else:
                reasons=quality_reasons(data,data['instruments'][s])
                if reasons:
                    report['exclusions'][s]=reasons
        data['instruments']={s:i for s,i in data['instruments'].items()
                             if s in settings['priority'] and s not in report['exclusions']}
        if not data['instruments']:
            data=None
    else:
        report['exclusions']={s:['No qualified versioned raw OHLCV, calendar, corporate actions, distributions and execution costs']
                              for s in settings['priority']}
    if data:
        if not args.synthetic:
            report['status']='EXPLORATORY_COMPLETE_REQUIRES_UNTOUCHED_PERIOD'
        periods=({'synthetic':(data['calendar'][60],data['calendar'][-1])} if args.synthetic else settings['periods'])
        scenarios={'primary':config,'cost_0bp':replace(config,spread_bps=0,slippage_bps=0),
                   'cost_10bp':replace(config,spread_bps=16,slippage_bps=2),
                   'risk_50yen':replace(config,trade_risk_yen=50),'risk_200yen':replace(config,trade_risk_yen=200)}
        universes={'portfolio':data['instruments'],**{s:{s:i} for s,i in data['instruments'].items()}}
        for name,cfg in scenarios.items():
            for period,(start,end) in periods.items():
                for universe,instruments in universes.items():
                    subset={**data,'instruments':instruments}
                    for strategy in ('cash','hold','A','B','C'):
                        simulation=run_swing(subset,strategy=strategy,start=start,end=end,config=cfg,
                                             priority=[s for s in settings['priority'] if s in instruments])
                        report['results'].append(dict(scenario=name,period=period,universe=universe,
                                                      metrics=summarize_swing(simulation),simulation=simulation))
    report['run_count']=len(report['results'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(report,handle,ensure_ascii=False,indent=2,allow_nan=False)
        handle.write('\n')
    print(json.dumps({k:report[k] for k in ('status','run_count','adopted_strategies','exclusions')},ensure_ascii=False))


if __name__=='__main__':
    main()
