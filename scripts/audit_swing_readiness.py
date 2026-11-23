"""Offline source-backed re-audit of a pinned blocked readiness report. No PnL."""
import argparse
import json
from pathlib import Path

from stock_ai.data.readiness_audit import audit_readiness

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('readiness', 'coverage', 'config', 'calendar', 'snapshot-index', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--readiness-sha256', required=True)
    parser.add_argument('--as-of', required=True)
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError('output path outside repository')
    if output.exists():
        raise FileExistsError('output already exists; select a new version')
    result = audit_readiness(
        source_root=ROOT, readiness_path=args.readiness,
        readiness_sha256=args.readiness_sha256, coverage_path=args.coverage,
        config_path=args.config, calendar_path=args.calendar,
        snapshot_index_path=args.snapshot_index, as_of=args.as_of)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps(dict(checked_evidence_count=result['checked_evidence_count'],
                          qualified_for_real_data=False, pnl_runs_this_audit=0)))


if __name__ == '__main__':
    main()
