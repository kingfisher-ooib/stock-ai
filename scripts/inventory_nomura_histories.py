"""Inventory official adjusted NAV/distribution histories without making trading bars."""
import argparse
import json
from pathlib import Path

from stock_ai.data.official_inventory import read_nomura_nav_history, verified_bytes


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-directory',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    funds=[]
    for symbol in ('1306','1321'):
        name=f'nf-{symbol}-history'
        meta=json.loads((args.source_directory/(name+'.meta.json')).read_text())
        raw=verified_bytes(args.source_directory/(name+'.csv'),meta['sha256'])
        funds.append(dict(source=meta,**read_nomura_nav_history(raw,symbol)))
    result=dict(role='official_NAV_and_distribution_evidence_not_OHLCV',funds=funds,
                warning='CSV date is not verified ex-date or payment date; adjusted amounts must not be applied to raw historical holdings')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:
        json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
        f.write('\n')
    print(json.dumps([{k:r[k] for k in ('symbol','period','row_count')} for r in funds]))


if __name__=='__main__':
    main()
