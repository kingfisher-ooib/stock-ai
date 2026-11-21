"""Read only existing original workbooks; write a new multi-symbol inventory."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import median

from stock_ai.data.official_inventory import CANDIDATES, read_monthly_evidence, read_quote_evidence, verified_bytes

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    monthly=json.loads((ROOT/'data/results/jpx-monthly-audit-2026-11-15.json').read_text())
    quotes=json.loads((ROOT/'data/results/jpx-etf-quote-audit-2026-11-15.json').read_text())
    segments,stats,sources=[],[],[]
    for record in monthly['source_files']:
        path=ROOT/'data/raw/jpx-monthly'/f"ivt_{record['year_month']}.xlsx"
        verified_bytes(path,record['sha256'])
        extracted=read_monthly_evidence(path)
        if any(r['year_month']!=record['year_month'] for r in extracted):
            raise ValueError('source month mismatch')
        segments.extend(extracted)
        sources.append(dict(kind='monthly',path=str(path.relative_to(ROOT)),**record))
    for record in quotes['monthly_files']:
        path=ROOT/'data/raw/jpx-etf-quotes'/f"{record['year_month']}.xlsx"
        verified_bytes(path,record['sha256'])
        stats.extend(dict(year_month=record['year_month'],**row) for row in read_quote_evidence(path))
        sources.append(dict(kind='quote',path=str(path.relative_to(ROOT)),**{k:record[k] for k in ('year_month','url','sha256','bytes')}))
    summary={}
    for symbol in CANDIDATES:
        rows=[r for r in segments if r['symbol']==symbol]
        spreads=[r['spread_mean_bps'] for r in stats if r['symbol']==symbol]
        summary[symbol]=dict(monthly_segments=len(rows),quote_months=len(spreads),
                             period=[min(r['first_date'] for r in rows),max(r['last_date'] for r in rows)],
                             latest_month_close=rows[-1]['close'],
                             monthly_spread_bps_median=median(spreads),
                             monthly_spread_bps_range=[min(spreads),max(spreads)],
                             qualified_for_daily_backtest=False,
                             remaining=['Daily OHLCV and calendar reconciliation','Effective-date lot/action histories',
                                        'Distribution ex/payment dates','Opening executable costs'])
    report=dict(status='OFFICIAL_MONTHLY_EVIDENCE_ONLY_NO_PNL',audit_read_at_utc=datetime.now(timezone.utc).isoformat(),
                original_retrieval_times='Unknown in legacy manifests; audit time is not source acquisition time',
                source_count=len(sources),summary=summary,sources=sources,monthly_segments=segments,quote_statistics=stats,
                warnings=['Monthly unit field must not be treated as daily lot history',
                          'Monthly equality does not verify daily bars or fill prices',
                          'No calendar inferred from days-traded counts','No profitability calculation performed'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:
        json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
        f.write('\n')
    print(json.dumps(report['summary'],ensure_ascii=False))


if __name__=='__main__':
    main()
