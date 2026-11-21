"""Audit all dates in the legacy 1475 snapshot; no price repair or PnL."""
import argparse
import csv
import json
from pathlib import Path

from stock_ai.data.market_calendar import spot_sessions
from stock_ai.data.official_inventory import verified_bytes

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--holiday-directory',type=Path,required=True)
    p.add_argument('--rules-directory',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():
        raise FileExistsError(a.output)
    hm=json.loads((a.holiday_directory/'cabinet-holidays.meta.json').read_text())
    holidays=verified_bytes(a.holiday_directory/'cabinet-holidays.csv',hm['sha256'])
    rm=json.loads((a.rules_directory/'jpx-session-rules.meta.json').read_text())
    rules=verified_bytes(a.rules_directory/'jpx-session-rules.html',rm['sha256']).decode()
    if not all(t in rules for t in ('年始3日間及び12月31日','土曜日','日曜日')):
        raise ValueError('expected JPX rule text absent')
    m=json.loads((ROOT/'data/results/cleaning-manifest-2026-11-15.json').read_text())
    path=ROOT/'data/processed/1475-daily-split-normalized-2024-2026.csv'
    raw=verified_bytes(path,m['output_sha256'])
    rows=list(csv.DictReader(raw.decode().splitlines()))
    dates=[r['date'] for r in rows]
    expected=spot_sessions(holidays,start=dates[0],end=dates[-1])
    actual=set(dates)
    annual={str(y):dict(expected=sum(d.startswith(str(y)) for d in expected),observed=sum(d.startswith(str(y)) for d in dates)) for y in (2024,2025,2026)}
    report=dict(role='full_period_calendar_audit_no_price_verification_no_pnl',symbol='1475',
                period=[dates[0],dates[-1]],sources=[hm,rm],daily_csv_sha256=m['output_sha256'],
                annual=annual,sessions=expected,expected_count=len(expected),observed_count=len(dates),
                missing=sorted(set(expected)-actual),unexpected=sorted(actual-set(expected)),
                duplicates=len(dates)-len(actual),limitations=['Does not verify OHLCV, corporate actions, distributions or fills',
                'Rules reconstructed retrospectively, not a captured historical calendar feed',
                'Instrument-specific trading halts and exceptional closures require separate checks'])
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
        f.write('\n')
    print(json.dumps({k:report[k] for k in ('annual','expected_count','observed_count','missing','unexpected','duplicates')}))


if __name__=='__main__':
    main()
