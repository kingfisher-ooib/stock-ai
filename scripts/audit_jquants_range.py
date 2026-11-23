"""Audit locally saved J-Quants daily ranges/pages. No credentials or network."""
import argparse
import json
from pathlib import Path

from stock_ai.data.jquants_range import audit_jquants_range
from stock_ai.data.multi_etf import timestamp
from stock_ai.data.official_inventory import verified_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('directory','calendar','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    for name in ('manifest-sha256','calendar-sha256','as-of'):
        parser.add_argument('--'+name,required=True)
    args = parser.parse_args()
    calendar = json.loads(verified_bytes(args.calendar,args.calendar_sha256))
    if any(timestamp(s['retrieved_at_utc']) > timestamp(args.as_of) for s in calendar['sources']):
        raise ValueError('calendar not yet observed')
    result = audit_jquants_range(args.directory,manifest_sha256=args.manifest_sha256,
                                sessions=calendar['sessions'],as_of=args.as_of)
    result['calendar_sha256'] = args.calendar_sha256
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(result,handle,ensure_ascii=False,indent=2,allow_nan=False)
        handle.write('\n')
    print(json.dumps(result['inventory']))


if __name__ == '__main__':
    main()
