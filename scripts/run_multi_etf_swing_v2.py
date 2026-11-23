"""Run the one registered synthetic v2 implementation comparison (30 runs)."""
import argparse
from dataclasses import fields
import hashlib
import json
from pathlib import Path

import yaml

from stock_ai.backtest.swing import SwingConfig, summarize_swing
from stock_ai.backtest.swing_v2 import run_swing_v2
from stock_ai.data.synthetic import synthetic_dataset

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output exists; originals must not be overwritten')
    expected = {
        'config/swing_v2.yaml': '4f9aa2f6f1f6c63072c37d90764e319584203b2a8587f5787a4d3425e1d0fefa',
        'docs/multi-etf/plan-v2.md': 'c73274b3a80f2a42e27385db6c7ef559d3f229eee9988d5951830b168bb073c3',
    }
    if any(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() != sha for p, sha in expected.items()):
        raise ValueError('registered config or plan changed; create a new experiment')
    settings = yaml.safe_load((ROOT/'config/swing_v2.yaml').read_text())
    if (settings['experiment_id'] != 'multi-etf-swing-v2-20261122'
            or settings['execution_model'] != 'prior_close_v2'
            or settings['release_status'] != 'synthetic_only'):
        raise ValueError('unregistered v2 experiment')
    cfg = SwingConfig(**{f.name: settings[f.name] for f in fields(SwingConfig)})
    data = synthetic_dataset(symbols=tuple(settings['priority']))
    sources = ['config/swing_v2.yaml', 'docs/multi-etf/plan-v2.md',
               'src/stock_ai/backtest/swing_v2.py', 'src/stock_ai/backtest/swing.py',
               'src/stock_ai/data/multi_etf.py', 'src/stock_ai/data/synthetic.py',
               'src/stock_ai/features/technical.py', 'scripts/run_multi_etf_swing_v2.py']
    report = dict(experiment_id=settings['experiment_id'],
                  status='SYNTHETIC_IMPLEMENTATION_TEST_ONLY', execution_model='prior_close_v2',
                  adopted_strategies=[], qualified_for_real_data=False, untouched_period=None,
                  ai_calls=0, authenticated_api_calls=0, orders_sent=0, results=[],
                  artifact_sha256={p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},
                  input_sha256=hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest())
    universes = {'portfolio': data['instruments'], **{s: {s: i} for s, i in data['instruments'].items()}}
    for universe, instruments in universes.items():
        subset = {**data, 'instruments': instruments}
        for strategy in ('cash', 'hold', 'A', 'B', 'C'):
            simulation = run_swing_v2(subset, strategy=strategy, start=data['calendar'][60],
                                      end=data['calendar'][-1], config=cfg,
                                      priority=[s for s in settings['priority'] if s in instruments])
            report['results'].append(dict(scenario='primary', period='synthetic', universe=universe,
                                          simulation=simulation, metrics=summarize_swing(simulation)))
    report['run_count'] = len(report['results'])
    if report['run_count'] != 30:
        raise ValueError('registered run count differs')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({k: report[k] for k in ('experiment_id', 'status', 'run_count', 'adopted_strategies')}))


if __name__ == '__main__':
    main()
