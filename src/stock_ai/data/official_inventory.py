"""Extract contemporaneous monthly evidence, never infer daily fills or calendars."""
from datetime import date
import hashlib
from math import isfinite
from pathlib import Path

from openpyxl import load_workbook

CANDIDATES=('1475','1306','1321','1346','2558')


def verified_bytes(path, expected):
    raw=Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError(f'source SHA-256 mismatch: {path}')
    return raw


def read_monthly_evidence(path, symbols=CANDIDATES):
    book=load_workbook(path,read_only=True,data_only=True)
    result=[]
    try:
        for row in book.active.iter_rows(values_only=True):
            if len(row)<24 or str(row[1]).strip() not in symbols:
                continue
            symbol=str(row[1]).strip()
            year,month=map(int,str(row[0]).split('/'))
            first=date(year,month,int(row[11])).isoformat()
            last=date(year,month,int(row[17])).isoformat()
            prices=[float(row[k]) for k in (10,12,14,16)]
            o,h,l,c=prices
            total,tostnet=int(row[19]),int(row[20] or 0)
            if not all(isfinite(v) for v in prices) or not 0<l<=min(o,c)<=max(o,c)<=h or first>last or not 0<=tostnet<=total:
                raise ValueError('invalid monthly segment')
            result.append(dict(symbol=symbol,year_month=f'{year:04d}{month:02d}',
                               name=row[2],first_date=first,last_date=last,
                               open=o,high=h,low=l,close=c,total_volume=total,
                               tostnet_volume=tostnet,non_tostnet_volume=total-tostnet,
                               days_traded=int(row[23]),published_monthly_unit=row[9],
                               corporate_action_note=row[4],
                               unit_warning='Month-level field; not effective-date lot history'))
    finally:
        book.close()
    absent=set(symbols)-{r['symbol'] for r in result}
    if absent:
        raise ValueError(f'missing symbols: {sorted(absent)}')
    return result


def read_quote_evidence(path, symbols=CANDIDATES):
    book=load_workbook(path,read_only=True,data_only=True)
    result=[]
    try:
        for row in book.active.iter_rows(values_only=True):
            if len(row)<15 or str(row[1]).strip() not in symbols:
                continue
            values=[float(row[k]) for k in (5,7,11,14)]
            if not all(isfinite(v) and v>=0 for v in values):
                raise ValueError('invalid monthly quote statistics')
            result.append(dict(symbol=str(row[1]).strip(),volume_mean=values[0],
                               close_mean=values[1],spread_mean_bps=values[2],
                               spread_mean_yen=values[3]))
    finally:
        book.close()
    if set(symbols)!={r['symbol'] for r in result} or len(result)!=len(symbols):
        raise ValueError('missing or duplicate quote symbol')
    return result


def calendar_from_jpx_html(html, year, start, end):
    """Use the selected year's published closure table plus weekend closure rule."""
    import re
    from datetime import timedelta
    match=re.search(r'<h3\b[^>]*>\s*<span>\s*'+str(year)+r'年\s*</span>\s*</h3>.*?<table\b[^>]*>(.*?)</table>',html,re.S)
    if not match:
        raise ValueError('requested year absent from official calendar page')
    days=re.findall(r'>(\d{4}/\d{2}/\d{2})[（(]',match.group(1))
    if len(days)!=len(set(days)) or not days or any(not d.startswith(str(year)+'/') for d in days):
        raise ValueError('invalid holiday table')
    holidays={date.fromisoformat(d.replace('/','-')) for d in days}
    if date(year,1,1) not in holidays or date(year,12,31) not in holidays:
        raise ValueError('incomplete holiday table')
    first,last=date.fromisoformat(start),date.fromisoformat(end)
    if first.year!=year or last.year!=year or first>last:
        raise ValueError('calendar range must lie in selected year')
    sessions=[]
    day=first
    while day<=last:
        if day.weekday()<5 and day not in holidays:
            sessions.append(day.isoformat())
        day+=timedelta(days=1)
    return dict(year=year,holidays=sorted(d.isoformat() for d in holidays),sessions=sessions)


def read_nomura_nav_history(raw, symbol):
    """Keep adjusted NAV/distribution records distinct from raw exchange OHLCV."""
    import csv
    from io import StringIO
    lines=list(csv.reader(StringIO(raw.decode('cp932'))))
    if not lines or lines[0][0]!=symbol:
        raise ValueError('fund identity mismatch')
    headers=[j for j,r in enumerate(lines) if r and r[0]=='Date']
    if len(headers)!=1:
        raise ValueError('missing/duplicate English header')
    header=lines[headers[0]]
    if header[3:5]!=['Net Asset Value (per Share)','ETF Dividend (per Share)']:
        raise ValueError('unexpected NAV schema')
    rows=[]
    for r in lines[headers[0]+1:]:
        if not r or not r[0]:
            continue
        if len(r)<5 or len(r[0])!=8:
            raise ValueError('invalid NAV row')
        d=date(int(r[0][:4]),int(r[0][4:6]),int(r[0][6:8])).isoformat()
        nav,distribution=float(r[3]),float(r[4])
        if not isfinite(nav) or not isfinite(distribution) or nav<=0 or distribution<0:
            raise ValueError('invalid NAV/distribution')
        rows.append(dict(date=d,adjusted_nav=nav,adjusted_distribution=distribution))
    if not rows or [r['date'] for r in rows]!=sorted(set(r['date'] for r in rows)):
        raise ValueError('empty, duplicate or unordered NAV history')
    return dict(symbol=symbol,price_basis='issuer_split_adjusted_NAV_not_exchange_OHLCV',
                adjustment_notice=lines[0][3],row_count=len(rows),period=[rows[0]['date'],rows[-1]['date']],
                distribution_records=[r for r in rows if r['adjusted_distribution']>0],
                qualified_for_daily_backtest=False,ex_dates_verified=False,pay_dates_verified=False)
