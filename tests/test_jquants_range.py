"""Generated range/page responses; these fixtures are not market observations."""
import hashlib
import json

import pytest

from stock_ai.data.jquants_range import audit_jquants_range
from stock_ai.data.official_inventory import CANDIDATES

SESSIONS = ['2025-10-20','2025-10-21','2025-10-22']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bar(symbol, day):
    return dict(Code=symbol+'0',Date=day,O=100,H=110,L=90,C=105,Vo=1000,Va=100000,
                AdjO=10,AdjH=11,AdjL=9,AdjC=10.5,AdjVo=10000)


@pytest.fixture
def snapshot(tmp_path):
    requests = []
    for symbol in CANDIDATES:
        path = tmp_path/(symbol+'.json')
        path.write_text(json.dumps({'data':[bar(symbol,SESSIONS[0]),bar(symbol,SESSIONS[2])]}))
        requests.append(dict(symbol=symbol,file=path.name,sha256=sha(path),bytes=path.stat().st_size,
                             url='https://api.jquants.com/v2/equities/bars/daily?code='+symbol+'0&from=2025-10-20&to=2025-10-22',
                             requested_at='2026-11-21T10:00:00+00:00',observed_at='2026-11-21T10:00:01+00:00',http_status=200))
    (tmp_path/'manifest.json').write_text(json.dumps(dict(role='jquants_range_snapshot_v1',
                                                        period=[SESSIONS[0],SESSIONS[-1]],requests=requests)))
    return tmp_path


def audit(root, **overrides):
    args = dict(manifest_sha256=sha(root/'manifest.json'), sessions=SESSIONS,
                as_of='2026-11-21T11:00:00+00:00')
    args.update(overrides)
    return audit_jquants_range(root,**args)


def edit_manifest(root, change):
    path = root/'manifest.json'
    m = json.loads(path.read_text())
    change(m)
    path.write_text(json.dumps(m))


def edit_payload(root, change):
    path = root/'1475.json'
    p = json.loads(path.read_text())
    change(p)
    path.write_text(json.dumps(p))
    edit_manifest(root,lambda m:m['requests'][0].update(sha256=sha(path),bytes=path.stat().st_size))


def paginate(root):
    edit_payload(root, lambda p:p.update(data=p['data'][:1],pagination_key='cursor1'))
    path = root/'1475-page2.json'
    path.write_text(json.dumps({'data':[bar('1475',SESSIONS[2])]}))
    def add(m):
        req = dict(m['requests'][0],file=path.name,sha256=sha(path),bytes=path.stat().st_size)
        req['url'] += '&pagination_key=cursor1'
        m['requests'].append(req)
    edit_manifest(root,add)
    return path


def test_multiday_reproducible_and_missing_day_is_not_removed(snapshot):
    before = {p.name:p.read_bytes() for p in snapshot.iterdir()}
    result = audit(snapshot)
    assert result == audit(snapshot)
    assert result['qualified_for_backtest'] is False and result['pnl_runs'] == 0
    assert all(r['ohlc']['open'] == 100 and r['volume'] == 1000 for r in result['rows'])
    assert all(i['expected'] == 3 and i['missing_sessions'] == [SESSIONS[1]]
               for i in result['inventory'].values())
    assert {p.name:p.read_bytes() for p in snapshot.iterdir()} == before


def test_valid_pagination_chain(snapshot):
    expected = audit(snapshot)['inventory']
    paginate(snapshot)
    assert audit(snapshot)['inventory'] == expected


def test_incomplete_pagination_rejected(snapshot):
    edit_payload(snapshot,lambda p:p.update(pagination_key='cursor1'))
    with pytest.raises(ValueError,match='incomplete'):
        audit(snapshot)


def test_wrong_page_cursor_rejected(snapshot):
    paginate(snapshot)
    edit_manifest(snapshot,lambda m:m['requests'][-1].update(url=m['requests'][-1]['url'].replace('cursor1','other')))
    with pytest.raises(ValueError,match='chain mismatch'):
        audit(snapshot)


@pytest.mark.parametrize('problem', ['duplicate','cycle'])
def test_duplicate_or_cyclic_page_rejected(snapshot, problem):
    path = paginate(snapshot)
    data = {'data':[bar('1475',SESSIONS[0] if problem=='duplicate' else SESSIONS[2])]}
    if problem == 'cycle':
        data['pagination_key'] = 'cursor1'
    path.write_text(json.dumps(data))
    edit_manifest(snapshot,lambda m:m['requests'][-1].update(sha256=sha(path),bytes=path.stat().st_size))
    with pytest.raises(ValueError,match='duplicate|cyclic'):
        audit(snapshot)


def test_provider_all_null_is_separate_from_missing_or_tradable_candle(snapshot):
    def no_trade(p):
        p['data'][0].update({k:None for k in ('O','H','L','C','Vo','Va')})
    edit_payload(snapshot,no_trade)
    result = audit(snapshot)
    inv = result['inventory']['1475']
    assert inv['no_trade_sessions'] == [SESSIONS[0]]
    assert inv['missing_sessions'] == [SESSIONS[1]]
    assert inv['raw_ohlcv_sessions'] == [SESSIONS[2]]
    row = next(r for r in result['rows'] if r['symbol']=='1475' and r['date']==SESSIONS[0])
    assert 'ohlc' not in row and 'volume' not in row


@pytest.mark.parametrize('field,value', [('O',None),('Vo',None),('Va',None),('Vo',0),
                                        ('Vo',True),('Vo',1.5),('H',80),('C',float('nan'))])
def test_partial_null_and_invalid_prices_or_volume_rejected(snapshot,field,value):
    edit_payload(snapshot,lambda p:p['data'][0].update({field:value}))
    with pytest.raises(ValueError):
        audit(snapshot)


@pytest.mark.parametrize('field,value', [('Code','13060'),('Date','2025-10-23')])
def test_unexpected_code_or_day_rejected(snapshot,field,value):
    edit_payload(snapshot,lambda p:p['data'][0].update({field:value}))
    with pytest.raises(ValueError,match='code/date'):
        audit(snapshot)


def test_adjusted_only_data_cannot_replace_raw(snapshot):
    edit_payload(snapshot,lambda p:p['data'][0].pop('O'))
    with pytest.raises(ValueError,match='unadjusted field absent'):
        audit(snapshot)


def test_modified_original_rejected(snapshot):
    (snapshot/'1475.json').write_text('{}')
    with pytest.raises(ValueError,match='SHA'):
        audit(snapshot)


def test_future_observation_rejected(snapshot):
    with pytest.raises(ValueError,match='not-yet-observed'):
        audit(snapshot,as_of='2026-11-21T09:00:00+00:00')


def test_duplicate_calendar_refused(snapshot):
    with pytest.raises(ValueError,match='sorted unique'):
        audit(snapshot,sessions=SESSIONS+SESSIONS[-1:])


def test_missing_candidate_refused(snapshot):
    edit_manifest(snapshot,lambda m:m['requests'].pop())
    with pytest.raises(ValueError,match='all five'):
        audit(snapshot)


def test_query_cannot_embed_credentials(snapshot):
    edit_manifest(snapshot,lambda m:m['requests'][0].update(url=m['requests'][0]['url']+'&x-api-key=fixture'))
    with pytest.raises(ValueError,match='URL'):
        audit(snapshot)


@pytest.mark.parametrize('change', [
    lambda m:m['requests'][0].update(http_status=403),
    lambda m:m['requests'][0].update(file='../outside.json'),
    lambda m:m['requests'][0].update(bytes=1),
    lambda m:m['requests'][0].update(requested_at='2025-10-19T00:00:00+00:00'),
    lambda m:m['requests'][0].update(url=m['requests'][0]['url'].replace('from=2025-10-20','from=2025-10-19')),
    lambda m:m['requests'].append(m['requests'][0].copy()),
])
def test_response_metadata_or_extra_terminal_page_refused(snapshot,change):
    edit_manifest(snapshot,change)
    with pytest.raises(ValueError):
        audit(snapshot)
