"""Register locally acquired source files without network access or modification."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from stock_ai.data.multi_etf import timestamp


def register_manual_source(source, *, source_url, observed_at, destination, note):
    source, destination=Path(source),Path(destination)
    parsed=urlparse(source_url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('public HTTPS provenance URL required')
    observed=timestamp(observed_at).astimezone(timezone.utc)
    if observed>datetime.now(timezone.utc):
        raise ValueError('observation time cannot be in the future')
    if not note.strip():
        raise ValueError('acquisition note required')
    raw=source.read_bytes()
    if not raw or len(raw)>100_000_000:
        raise ValueError('empty or oversized original')
    suffix=source.suffix.lower()
    if suffix not in ('.pdf','.csv','.json','.xlsx','.html'):
        raise ValueError('unsupported source format')
    if suffix=='.pdf' and not raw.startswith(b'%PDF-'):
        raise ValueError('invalid PDF signature')
    if suffix=='.xlsx' and not raw.startswith(b'PK'):
        raise ValueError('invalid workbook signature')
    if suffix=='.json':
        json.loads(raw)
    digest=hashlib.sha256(raw).hexdigest()
    record=dict(role='manual_source_registration_not_price_verification',
                acquisition_method='user_supplied_local_original',source_url=source_url,
                source_filename=source.name,observed_at_utc=observed.isoformat(),
                registered_at_utc=datetime.now(timezone.utc).isoformat(),
                sha256=digest,bytes=len(raw),note=note.strip(),
                original='original'+suffix,qualified_for_backtest=False,
                required_next_steps=['Verify target date, symbol, page and unit',
                                     'Extract OHLCV and compare independently',
                                     'Check calendar and corporate-action basis'])
    # New directory is the atomic reservation: never replace an existing version.
    destination.mkdir(parents=True,exist_ok=False)
    with (destination/record['original']).open('xb') as f:
        f.write(raw)
    with (destination/'manifest.json').open('x') as f:
        json.dump(record,f,ensure_ascii=False,indent=2,allow_nan=False)
        f.write('\n')
    return record


def verify_registered_source(directory):
    directory=Path(directory)
    record=json.loads((directory/'manifest.json').read_text())
    name=record['original']
    if Path(name).name!=name or not name.startswith('original.'):
        raise ValueError('invalid registered original path')
    raw=(directory/name).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=record['sha256'] or len(raw)!=record['bytes']:
        raise ValueError('registered original SHA-256/size mismatch')
    return record
