"""Offline single-day provenance audit. Never qualifies data for backtesting."""
from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from stock_ai.data.multi_etf import timestamp
from stock_ai.data.official_inventory import CANDIDATES, verified_bytes


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _number(value):
    if type(value) not in (int, float):
        raise ValueError('numeric OHLCV required; nulls are not filled')
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('finite OHLCV required')
    return result


def _prices(values):
    o, h, l, c = map(_number, values)
    if not 0 < l <= min(o, c) <= max(o, c) <= h:
        raise ValueError('invalid OHLC')
    return o, h, l, c


def audit_jquants_day(directory, *, manifest_sha256, price_evidence,
                      evidence_sha256, as_of):
    """Recompute from hashed originals, not the saved crosscheck's flags/rows.

    Caller supplies trusted hashes and an observation boundary. This audit only
    checks five candidates on one date, not calendars, corporate actions or costs.
    """
    root = Path(directory).resolve()
    manifest_raw = verified_bytes(root / 'manifest.json', manifest_sha256)
    evidence_raw = verified_bytes(price_evidence, evidence_sha256)
    manifest = json.loads(manifest_raw, object_pairs_hook=_object)
    evidence = json.loads(evidence_raw, object_pairs_hook=_object)
    boundary = timestamp(as_of)
    day = date.fromisoformat(manifest['date'])
    if manifest['date'] != day.isoformat():
        raise ValueError('canonical date required')
    if manifest.get('price_audit_sha256') != evidence_sha256:
        raise ValueError('price evidence hash differs from acquisition manifest')
    requests = manifest['requests']
    refs = evidence['rows']
    for rows in (requests, refs):
        if (len(rows) != len(CANDIDATES)
                or {r['symbol'] for r in rows} != set(CANDIDATES)):
            raise ValueError('five unique fixed candidates required')
    references = {r['symbol']: r for r in refs}
    by_symbol = {r['symbol']: r for r in requests}
    output = []
    for symbol in CANDIDATES:
        req, ref = by_symbol[symbol], references[symbol]
        if req['http_status'] != 200:
            raise ValueError('unsuccessful response')
        url = urlsplit(req['url'])
        if (url.scheme != 'https' or url.netloc != 'api.jquants.com'
                or url.path != '/v2/equities/bars/daily' or url.fragment
                or parse_qs(url.query, keep_blank_values=True)
                != {'code': [symbol + '0'], 'date': [day.isoformat()]}):
            raise ValueError('unexpected source URL or query')
        started, observed = timestamp(req['requested_at']), timestamp(req['observed_at'])
        cutoff = datetime.combine(day, time(7), timezone.utc)
        if not cutoff <= started <= observed <= boundary:
            raise ValueError('observation outside requested as-of boundary')
        filename = symbol + '.json'
        if req['file'] != filename or (root / filename).resolve().parent != root:
            raise ValueError('original path must stay inside snapshot')
        raw = verified_bytes(root / filename, req['sha256'])
        if len(raw) != req['bytes']:
            raise ValueError('original size mismatch')
        payload = json.loads(raw, object_pairs_hook=_object)
        if payload.get('pagination_key'):
            raise ValueError('incomplete paginated response')
        records = payload.get('data')
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError('exactly one daily record required')
        bar = records[0]
        if bar.get('Code') != symbol + '0' or bar.get('Date') != day.isoformat():
            raise ValueError('response code/date mismatch')
        # Never fall back to AdjO/AdjH/AdjL/AdjC/AdjVo.
        prices = _prices([bar.get(k) for k in ('O', 'H', 'L', 'C')])
        volume = _number(bar.get('Vo'))
        if volume <= 0 or volume != volume.to_integral_value():
            raise ValueError('positive integral unadjusted volume required')
        if (ref.get('date') != day.isoformat() or ref.get('visually_checked') is not True
                or type(ref.get('pdf_page_one_based')) is not int
                or ref['pdf_page_one_based'] < 1):
            raise ValueError('matching manually checked price evidence required')
        expected = _prices([ref['daily_ohlc'][k] for k in ('open', 'high', 'low', 'close')])
        if prices != expected:
            raise ValueError('unadjusted OHLC differs from JPX price evidence')
        output.append(dict(symbol=symbol, date=day.isoformat(),
                           ohlc=dict(zip(('open', 'high', 'low', 'close'), map(float, prices))),
                           volume=int(volume), volume_unit='units',
                           volume_scope='TSE on-floor only', observed_at=observed.isoformat(),
                           source_url=req['url'], source_sha256=req['sha256'],
                           pdf_page_one_based=ref['pdf_page_one_based'], ohlc_matches_pdf=True))
    return dict(role='offline_single_day_source_audit_not_backtest_input',
                manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
                price_evidence_sha256=hashlib.sha256(evidence_raw).hexdigest(),
                as_of=boundary.isoformat(), rows=output, synthetic=False,
                qualified_for_backtest=False,
                unresolved=['full-period calendar and OHLCV', 'corporate actions and lot history',
                            'distribution history', 'execution costs',
                            'volume crosscheck against a second daily source',
                            'historical publication timestamps'])
