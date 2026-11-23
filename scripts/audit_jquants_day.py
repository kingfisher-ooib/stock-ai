"""Recheck a local single-day J-Quants snapshot; no API key or network needed."""
import argparse
import json
from pathlib import Path

from stock_ai.data.jquants_audit import audit_jquants_day


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--price-evidence', type=Path, required=True)
    parser.add_argument('--price-evidence-sha256', required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit_jquants_day(args.directory, manifest_sha256=args.manifest_sha256,
                              price_evidence=args.price_evidence,
                              evidence_sha256=args.price_evidence_sha256, as_of=args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'audited_symbols': len(result['rows']), 'qualified_for_backtest': False}))


if __name__ == '__main__':
    main()
