from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json

import pytest

from stock_ai.data.swing_v3_schema import decision_view, load_snapshot


BLOB = b'explicit synthetic source fixture; not market data'
AS_OF = '2025-12-31T23:59:59+00:00'


def fixture():
    sessions = []
    current = date(2025, 1, 6)
    while len(sessions) < 70:
        if current.weekday() < 5:
            sessions.append(current.isoformat())
        current += timedelta(days=1)
    source = dict(source_id='s', origin='synthetic', locator='synthetic fixture',
                  sha256=hashlib.sha256(BLOB).hexdigest(),
                  retrieved_at='2025-05-01T00:00:00Z', document_date='2025-01-01',
                  available_at='2025-01-01T00:00:00Z', availability_basis='synthetic')
    common = dict(source_id='s', available_at='2025-01-01T00:00:00Z')
    bars = [dict(symbol=symbol, session_date=d, unit_basis_id=symbol+'-old',
                 open='100', high='102', low='99', close='101', volume=100,
                 source_id='s', available_at=d+'T07:00:00Z')
            for symbol in ['ETF-X', 'ETF-Y'] for d in sessions]
    return dict(schema_version='stock-ai-swing-v3-synthetic-1', synthetic=True,
                calendar_source_id='s', sessions=sessions, symbols=['ETF-X', 'ETF-Y'],
                evaluation_start_session=sessions[60], evaluation_end_session=sessions[-1],
                sources=[source], unit_bases=[dict(basis_id=s+'-old', symbol=s,
                    effective_session=sessions[0], **common) for s in ['ETF-X', 'ETF-Y']],
                bars=bars, lots=[dict(symbol=s, effective_session=sessions[0], size=1,
                                     **common) for s in ['ETF-X', 'ETF-Y']],
                splits=[], entitlements=[], amount_revisions=[], cash_evidence=[],
                execution_rules=[dict(symbol=s, start_session=sessions[60], end_session=sessions[-1],
                    tick_yen='1', fee_per_side='0', spread_bps='6', slippage_bps='2',
                    assumption_id='synthetic-only', **common) for s in ['ETF-X', 'ETF-Y']])


def load(data, *, as_of=AS_OF, source_blobs=None):
    raw = json.dumps(data).encode()
    return load_snapshot(raw, sha256=hashlib.sha256(raw).hexdigest(), as_of=as_of,
                         source_blobs={'s': BLOB} if source_blobs is None else source_blobs)


def with_events():
    data = fixture()
    days = data['sessions']
    common = dict(source_id='s', available_at=days[59]+'T07:00:00Z')
    data['unit_bases'].append(dict(basis_id='ETF-X-new', symbol='ETF-X',
                                    effective_session=days[61], **common))
    data['splits'] = [dict(event_id='split', symbol='ETF-X', ratio_new_per_old='10',
        market_switch_date=days[61], legal_effective_date=days[63], split_record_date=days[62],
        from_basis_id='ETF-X-old', to_basis_id='ETF-X-new', **common)]
    for b in data['bars']:
        if b['symbol']=='ETF-X' and b['session_date'] >= days[61]:
            b['unit_basis_id']='ETF-X-new'
            b.update(open='10', high='10.2', low='9.9', close='10.1')
    data['entitlements'] = [dict(event_id='div', symbol='ETF-X', last_cum_session=days[60],
        ex_session=days[61], distribution_record_date=days[62],
        quote_unit_basis_id='ETF-X-old', date_evidence='direct', **common)]
    data['amount_revisions'] = [dict(revision_id='estimate', event_id='div',
        supersedes_revision_id=None, quoted_amount='7', quoted_units=1,
        quote_unit_basis_id='ETF-X-old', status='estimate', **common),
        dict(revision_id='final', event_id='div', supersedes_revision_id='estimate',
        quoted_amount='8', quoted_units=1, quote_unit_basis_id='ETF-X-old', status='final',
        source_id='s', available_at=days[64]+'T07:00:00Z')]
    data['cash_evidence'] = [dict(event_id='div', scheduled_payment_date=days[68],
        cash_available_at=None, status='schedule_only', amount='8',
        source_id='s', available_at=days[64]+'T07:00:00Z')]
    return data


def test_two_symbol_complete_snapshot_is_immutable_and_not_execution_permission():
    data = fixture(); before = deepcopy(data)
    snapshot = load(data)
    assert not snapshot.qualified_for_real_data
    assert isinstance(snapshot.bars, tuple) and data == before
    with pytest.raises(ValueError):
        snapshot.bars[0].close = '1000'
    assert snapshot == load(data)


def test_same_day_split_and_distribution_and_late_final_are_preserved_not_leaked():
    data = with_events(); snapshot = load(data)
    view = decision_view(snapshot, decision_at=data['sessions'][60]+'T07:00:00Z')
    assert [r.revision_id for r in view['amount_revisions']] == ['estimate']
    assert not view['cash_evidence']
    assert len(snapshot.amount_revisions) == 2
    assert all(b.session_date <= data['sessions'][60] for b in view['bars'])
    assert len(view['splits']) == 1  # Announcement known, not applied to prices here.
    assert view['bars'][0].unit_basis_id == 'ETF-X-old'


@pytest.mark.parametrize('field,value', [('synthetic', False), ('synthetic', 1),
    ('schema_version','old'), ('unknown_field',True)])
def test_old_or_real_schema_not_automatically_promoted(field,value):
    data=fixture();data[field]=value
    with pytest.raises(ValueError):load(data)


@pytest.mark.parametrize('mutation', ['missing','duplicate','invalid_ohlc','float_price',
    'nan_price','zero_volume','boolean_volume','unknown_basis','other_symbol_basis',
    'future_close_availability'])
def test_bad_prices_and_units_rejected(mutation):
    data=fixture();b=data['bars'][0]
    if mutation=='missing':data['bars'].pop()
    elif mutation=='duplicate':data['bars'].append(deepcopy(b))
    elif mutation=='invalid_ohlc':b['high']='98'
    elif mutation=='float_price':b['close']=101.0
    elif mutation=='nan_price':b['close']='NaN'
    elif mutation=='zero_volume':b['volume']=0
    elif mutation=='boolean_volume':b['volume']=True
    elif mutation=='unknown_basis':b['unit_basis_id']='unknown'
    elif mutation=='other_symbol_basis':b['unit_basis_id']='ETF-Y-old'
    else:b['available_at']=b['session_date']+'T06:59:59Z'
    with pytest.raises(ValueError):load(data)


@pytest.mark.parametrize('mutation', ['duplicate_session','no_warmup','bad_source',
    'calendar_source','timezone','late_record','late_source','real_source','unknown_source',
    'initial_lot','boolean_lot','rule_gap','rule_overlap','basis_gap'])
def test_missing_history_sources_or_execution_contract_rejected(mutation):
    data=fixture()
    if mutation=='duplicate_session':data['sessions'].append(data['sessions'][-1])
    elif mutation=='no_warmup':data['evaluation_start_session']=data['sessions'][59]
    elif mutation=='bad_source':data['sources'][0]['sha256']='0'*64
    elif mutation=='calendar_source':data['calendar_source_id']='unknown'
    elif mutation=='timezone':data['sources'][0]['available_at']='2025-01-01T00:00:00'
    elif mutation=='late_record':data['lots'][0]['available_at']='2026-01-01T00:00:00Z'
    elif mutation=='late_source':data['sources'][0]['retrieved_at']='2026-01-01T00:00:00Z'
    elif mutation=='real_source':data['sources'][0]['origin']='official'
    elif mutation=='unknown_source':data['bars'][0]['source_id']='unknown'
    elif mutation=='initial_lot':data['lots'].pop()
    elif mutation=='boolean_lot':data['lots'][0]['size']=True
    elif mutation=='rule_gap':data['execution_rules'].pop()
    elif mutation=='rule_overlap':data['execution_rules'].append(deepcopy(data['execution_rules'][0]))
    else:data['unit_bases'][0]['effective_session']=data['sessions'][1]
    with pytest.raises(ValueError):load(data)


@pytest.mark.parametrize('mutation', ['missing_split','ratio_zero','wrong_before',
    'old_bar_unit','candidate_date','wrong_last_cum','event_id_collision',
    'orphan_revision','revision_cycle','revision_branch','wrong_revision_basis',
    'schedule_with_cash','cash_before_ex','duplicate_cash'])
def test_ambiguous_actions_or_payment_assumptions_rejected(mutation):
    data=with_events()
    if mutation=='missing_split':data['splits']=[]
    elif mutation=='ratio_zero':data['splits'][0]['ratio_new_per_old']='0'
    elif mutation=='wrong_before':data['splits'][0]['from_basis_id']='ETF-Y-old'
    elif mutation=='old_bar_unit':data['bars'][61]['unit_basis_id']='ETF-X-old'
    elif mutation=='candidate_date':data['entitlements'][0]['date_evidence']='calendar_candidate'
    elif mutation=='wrong_last_cum':data['entitlements'][0]['last_cum_session']=data['sessions'][59]
    elif mutation=='event_id_collision':data['splits'][0]['event_id']='div'
    elif mutation=='orphan_revision':data['amount_revisions'][0]['event_id']='unknown'
    elif mutation=='revision_cycle':data['amount_revisions'][0]['supersedes_revision_id']='final'
    elif mutation=='revision_branch':
        child=deepcopy(data['amount_revisions'][1]);child['revision_id']='branch';data['amount_revisions'].append(child)
    elif mutation=='wrong_revision_basis':data['amount_revisions'][0]['quote_unit_basis_id']='ETF-Y-old'
    elif mutation=='schedule_with_cash':data['cash_evidence'][0]['cash_available_at']=data['sessions'][68]+'T00:00:00Z'
    elif mutation=='cash_before_ex':data['cash_evidence'][0]['scheduled_payment_date']=data['sessions'][60]
    else:data['cash_evidence'].append(deepcopy(data['cash_evidence'][0]))
    with pytest.raises(ValueError):load(data)


def test_input_bytes_hash_source_bytes_and_duplicate_json_keys_checked():
    data=fixture();raw=json.dumps(data).encode()
    with pytest.raises(ValueError,match='snapshot SHA'):load_snapshot(raw,sha256='0'*64,as_of=AS_OF,source_blobs={'s':BLOB})
    with pytest.raises(ValueError,match='source SHA'):load(data,source_blobs={})
    with pytest.raises(ValueError,match='source SHA'):load(data,source_blobs={'s':BLOB+b'changed'})
    duplicate=b'{"synthetic":true,"synthetic":true}'
    with pytest.raises(ValueError,match='duplicate JSON'):
        load_snapshot(duplicate,sha256=hashlib.sha256(duplicate).hexdigest(),as_of=AS_OF,source_blobs={})


def test_cash_boundary_uses_japan_date_not_utc_date():
    data=with_events();cash=data['cash_evidence'][0]
    ex=date.fromisoformat(data['entitlements'][0]['ex_session'])
    cash.update(status='explicit_research_assumption',
                cash_available_at=(ex-timedelta(days=1)).isoformat()+'T23:30:00Z')
    assert load(data).cash_evidence[0].cash_available_at == cash['cash_available_at']


@pytest.mark.parametrize('mutation', ['future_cash_observed','root_correction','final_downgrade'])
def test_observation_and_revision_status_chronology(mutation):
    data=with_events()
    if mutation=='future_cash_observed':
        data['cash_evidence'][0].update(status='observed',
            cash_available_at=data['sessions'][68]+'T00:00:00Z')
    elif mutation=='root_correction':data['amount_revisions'][0]['status']='correction'
    else:
        data['amount_revisions'][0]['status']='final'
        data['amount_revisions'][1]['status']='estimate'
    with pytest.raises(ValueError):load(data)


@pytest.mark.parametrize('data',[[],None,1])
def test_non_object_json_rejected(data):
    with pytest.raises(ValueError):load(data)
