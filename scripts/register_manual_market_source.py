"""Register a manually acquired original. Does not download, trade or repair prices."""
import argparse
import json
from pathlib import Path

from stock_ai.data.manual_sources import register_manual_source, verify_registered_source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--source-url',required=True)
    parser.add_argument('--observed-at',required=True)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--note',required=True)
    args=parser.parse_args()
    register_manual_source(args.input,source_url=args.source_url,observed_at=args.observed_at,
                           destination=args.directory,note=args.note)
    print(json.dumps(verify_registered_source(args.directory),ensure_ascii=False))


if __name__=='__main__':
    main()
