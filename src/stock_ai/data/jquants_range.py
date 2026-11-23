"""Offline raw OHLCV range/page audit; no trading or qualification flags inferred."""
from datetime import date, datetime, time, timezone
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from stock_ai.data.jquants_audit import _number, _object, _prices
from stock_ai.data.multi_etf import timestamp
from stock_ai.data.official_inventory import CANDIDATES, verified_bytes


def audit_jquants_range(directory, *, manifest_sha256, sessions, as_of):
    root = Path(directory).resolve()
    m = json.loads(verified_bytes(root/'manifest.json', manifest_sha256), object_pairs_hook=_object)
    if m.get('role') == 'single_day_source_crosscheck_not_backtest':
        start = end = m['date']  # Backward-compatible read of existing raw originals.
        query_base = {'date': [start]}
    elif m.get('role') == 'jquants_range_snapshot_v1':
        start, end = m['period']
        query_base = {'from': [start], 'to': [end]}
    else:
        raise ValueError('unsupported acquisition manifest')
    if start > end or any(date.fromisoformat(d).isoformat() != d for d in (start,end)):
        raise ValueError('invalid requested period')
    if not sessions or sessions != sorted(set(sessions)):
        raise ValueError('sorted unique calendar required')
    for day in sessions:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError('canonical calendar date required')
    expected = [d for d in sessions if start <= d <= end]
    if not expected:
        raise ValueError('requested period has no expected sessions')
    boundary = timestamp(as_of)
    requests = m['requests']
    if not isinstance(requests, list) or {r['symbol'] for r in requests} != set(CANDIDATES):
        raise ValueError('requests for all five fixed candidates required')
    output, inventory, files = [], {}, set()
    for symbol in CANDIDATES:
        pages = [r for r in requests if r['symbol'] == symbol]
        token, used_tokens, dates = None, set(), set()
        valid, no_trade = [], []
        for number, req in enumerate(pages):
            if number and token is None:
                raise ValueError('extra page after terminal response')
            query = {**query_base, 'code': [symbol+'0']}
            if token is not None:
                query['pagination_key'] = [token]
            url = urlsplit(req['url'])
            if (url.scheme != 'https' or url.netloc != 'api.jquants.com'
                    or url.path != '/v2/equities/bars/daily' or url.fragment
                    or parse_qs(url.query, keep_blank_values=True) != query):
                raise ValueError('source URL or pagination chain mismatch')
            observed, started = timestamp(req['observed_at']), timestamp(req['requested_at'])
            if req['http_status'] != 200 or not started <= observed <= boundary:
                raise ValueError('unsuccessful or not-yet-observed response')
            name = req['file']
            if (not isinstance(name,str) or Path(name).name != name or name in files
                    or (root/name).resolve().parent != root):
                raise ValueError('duplicate or escaping original path')
            files.add(name)
            raw = verified_bytes(root/name, req['sha256'])
            if len(raw) != req['bytes']:
                raise ValueError('original size mismatch')
            payload = json.loads(raw, object_pairs_hook=_object)
            if not isinstance(payload.get('data'),list):
                raise ValueError('daily data array required')
            for bar in payload['data']:
                day = bar['Date']
                if bar['Code'] != symbol+'0' or day not in expected:
                    raise ValueError('record code/date outside expected calendar')
                if day in dates:
                    raise ValueError('duplicate daily record across pages')
                dates.add(day)
                cutoff = datetime.combine(date.fromisoformat(day), time(7), timezone.utc)
                if started < cutoff:
                    raise ValueError('response requested before daily bar was available')
                fields = ('O','H','L','C','Vo','Va')
                if any(k not in bar for k in fields):
                    raise ValueError('required unadjusted field absent')
                if all(bar[k] is None for k in fields):
                    # Provider's no-trade record is not a price candle or proof of a halt.
                    no_trade.append(day)
                    output.append(dict(symbol=symbol,date=day,status='provider_reported_no_trade',
                                       source_sha256=req['sha256'],observed_at=observed.isoformat()))
                    continue
                prices = _prices([bar[k] for k in fields[:4]])
                volume, turnover = _number(bar['Vo']), _number(bar['Va'])
                if volume <= 0 or volume != volume.to_integral_value() or turnover <= 0:
                    raise ValueError('invalid unadjusted volume or turnover')
                valid.append(day)
                output.append(dict(symbol=symbol,date=day,status='raw_ohlcv_available',
                                   ohlc=dict(zip(('open','high','low','close'),map(float,prices))),
                                   volume=int(volume), volume_unit='units', price_basis='raw',
                                   turnover_yen=float(turnover), source_sha256=req['sha256'],
                                   observed_at=observed.isoformat(), ohlc_independently_crosschecked=False))
            token = payload.get('pagination_key')
            if token is not None:
                if not isinstance(token,str) or not token or token in used_tokens:
                    raise ValueError('invalid or cyclic pagination key')
                used_tokens.add(token)
        if token is not None:
            raise ValueError('incomplete pagination chain')
        inventory[symbol] = dict(expected=len(expected), raw_ohlcv_sessions=sorted(valid),
                                 no_trade_sessions=sorted(no_trade),
                                 missing_sessions=[d for d in expected if d not in dates])
    return dict(role='raw_range_source_audit_not_backtest_input',period=[start,end],
                manifest_sha256=manifest_sha256,as_of=boundary.isoformat(),inventory=inventory,
                rows=sorted(output,key=lambda r:(r['symbol'],r['date'])),
                qualified_for_backtest=False, pnl_runs=0,
                unresolved=['independent price checks', 'no-trade reason and trading halts',
                            'corporate actions and lot history', 'distributions and costs',
                            'historical publication timestamps'])
