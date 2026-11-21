import hashlib
from pathlib import Path

from openpyxl import Workbook
import pytest

from stock_ai.data.official_inventory import calendar_from_jpx_html, read_monthly_evidence, read_quote_evidence, verified_bytes


def book(tmp_path,rows):
    path=tmp_path/'source.xlsx'
    b=Workbook()
    for row in rows:
        b.active.append(row)
    b.save(path)
    return path


def monthly(symbol='1475'):
    row=[None]*25
    row[0]='2024/08'
    row[1]=symbol
    row[2]='synthetic ETF'
    row[9]=10
    for i,v in {10:100,11:1,12:110,13:2,14:90,15:3,16:105,17:30,19:1000,20:100,23:21}.items():
        row[i]=v
    return row


def test_multiple_symbols_and_split_segments_preserved(tmp_path):
    a,b=monthly(),monthly()
    a[17]=7
    b[11]=8
    p=book(tmp_path,[a,b,monthly('1306')])
    rows=read_monthly_evidence(p,('1475','1306'))
    assert len(rows)==3
    assert rows[0]['close']==105  # no implicit 10:1 normalization
    assert rows[0]['non_tostnet_volume']==900
    assert rows[1]['first_date']=='2024-08-08'
    assert all('not effective-date' in r['unit_warning'] for r in rows)


@pytest.mark.parametrize('field,value',[(20,1001),(14,200),(11,31)])
def test_invalid_monthly_evidence_rejected(tmp_path,field,value):
    row=monthly()
    row[field]=value
    with pytest.raises(ValueError):
        read_monthly_evidence(book(tmp_path,[row]),('1475',))


def test_missing_symbol_rejected(tmp_path):
    with pytest.raises(ValueError,match='missing symbols'):
        read_monthly_evidence(book(tmp_path,[monthly()]),('1475','1306'))


def test_hash_guard_prevents_mutated_original(tmp_path):
    p=tmp_path/'raw'
    p.write_bytes(b'original')
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    assert verified_bytes(p,sha)==b'original'
    p.write_bytes(b'changed')
    with pytest.raises(ValueError,match='SHA'):
        verified_bytes(p,sha)


def test_quote_statistics_missing_or_duplicate_refused(tmp_path):
    row=[None]*15
    row[1]='1475'
    for k in (5,7,11,14): row[k]=1
    assert read_quote_evidence(book(tmp_path,[row]),('1475',))[0]['spread_mean_bps']==1
    with pytest.raises(ValueError,match='missing or duplicate'):
        read_quote_evidence(book(tmp_path,[row,row]),('1475',))


def html():
    return '<h3 class="subhead-title"><span>2026年</span></h3><table>'+''.join(
        '<tr><td>'+d+'（木）</td><td>休日</td></tr>' for d in ('2026/01/01','2026/01/02','2026/01/12','2026/12/31'))+'</table>'


def test_calendar_excludes_published_holidays_and_weekends():
    result=calendar_from_jpx_html(html(),2026,'2026-01-01','2026-01-13')
    assert result['sessions']==['2026-01-05','2026-01-06','2026-01-07','2026-01-08','2026-01-09','2026-01-13']


def test_calendar_never_invents_unpublished_year():
    with pytest.raises(ValueError,match='absent'):
        calendar_from_jpx_html(html(),2024,'2024-01-01','2024-01-31')


def test_truncated_official_calendar_rejected():
    with pytest.raises(ValueError,match='incomplete'):
        calendar_from_jpx_html(html().replace('2026/12/31',''),2026,'2026-01-01','2026-01-31')


def test_nav_csv_cannot_be_mistaken_for_tradable_raw_ohlcv():
    from stock_ai.data.official_inventory import read_nomura_nav_history
    raw=('1306,fund,,split-adjusted\nDate,x,x,Net Asset Value (per Share),ETF Dividend (per Share)\n20240104,0,0,200,0\n20240710,0,0,210,5.79\n').encode('cp932')
    result=read_nomura_nav_history(raw,'1306')
    assert result['qualified_for_daily_backtest'] is False
    assert result['ex_dates_verified'] is False and result['pay_dates_verified'] is False
    assert result['distribution_records'][0]['adjusted_distribution']==5.79
    assert 'not_exchange_OHLCV' in result['price_basis']


def test_nav_csv_rejects_wrong_fund_and_duplicate_dates():
    from stock_ai.data.official_inventory import read_nomura_nav_history
    raw=('1306,fund,,adjusted\nDate,x,x,Net Asset Value (per Share),ETF Dividend (per Share)\n20240104,0,0,200,0\n20240104,0,0,210,0\n').encode('cp932')
    with pytest.raises(ValueError,match='identity'):
        read_nomura_nav_history(raw,'1321')
    with pytest.raises(ValueError,match='duplicate'):
        read_nomura_nav_history(raw,'1306')
