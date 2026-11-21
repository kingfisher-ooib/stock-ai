"""Compare actual saved daily dates against an independently published JPX year."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from stock_ai.data.official_inventory import calendar_from_jpx_html, verified_bytes

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-directory',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    meta=json.loads((args.source_directory/'jpx-calendar.meta.json').read_text())
    raw=verified_bytes(args.source_directory/'jpx-calendar.html',meta['sha256'])
    calendar=calendar_from_jpx_html(raw.decode(),2026,'2026-01-01','2026-11-13')
    csv_path=ROOT/'data/processed/1475-daily-split-normalized-2024-2026.csv'
    manifest=json.loads((ROOT/'data/results/cleaning-manifest-2026-11-15.json').read_text())
    verified_bytes(csv_path,manifest['output_sha256'])
    with csv_path.open() as f:
        actual=[r['date'] for r in csv.DictReader(f) if '2026-01-01'<=r['date']<='2026-11-13']
    expected=calendar['sessions']
    report=dict(role='calendar_audit_no_ohlcv_verification_no_pnl',symbol='1475',
                source=meta,period=['2026-01-01','2026-11-13'],**calendar,
                daily_csv_sha256=manifest['output_sha256'],observed_count=len(actual),
                missing=sorted(set(expected)-set(actual)),unexpected=sorted(set(actual)-set(expected)),
                duplicate_count=len(actual)-len(set(actual)),
                limitations=['Only 2026 audited; 2024/2025 official closure tables not yet acquired',
                            'Calendar match does not verify OHLCV or distributions'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
        f.write('\n')
    print(json.dumps({k:report[k] for k in ('observed_count','missing','unexpected','duplicate_count')}))


if __name__=='__main__':
    main()
