"""Offline missing-session inventory. Hashes and snapshot selection are explicit."""
import argparse
import json
from pathlib import Path

from stock_ai.data.coverage_inventory import inventory_coverage
from stock_ai.data.official_inventory import verified_bytes

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('config', 'calendar', 'snapshot-index', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    for name in ('config-sha256', 'calendar-sha256', 'snapshot-index-sha256', 'as-of'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    snapshots = json.loads(verified_bytes(args.snapshot_index, args.snapshot_index_sha256))
    result = inventory_coverage(source_root=ROOT, config_path=args.config,
                                config_sha256=args.config_sha256, calendar_path=args.calendar,
                                calendar_sha256=args.calendar_sha256, snapshots=snapshots,
                                as_of=args.as_of)
    result['snapshot_index_sha256'] = args.snapshot_index_sha256
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({s: {k:i[k] for k in ('expected', 'source_audited', 'missing_count')}
                      for s,i in result['inventory'].items()}))


if __name__ == '__main__':
    main()
