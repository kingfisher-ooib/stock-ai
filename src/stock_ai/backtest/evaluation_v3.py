"""Strict accounting reconciliation and descriptive synthetic v3 statistics."""
from decimal import Decimal
from fractions import Fraction
from math import isfinite, sqrt
from random import Random
from statistics import mean, stdev

from stock_ai.backtest.cash_v3 import _difference, _sum
from stock_ai.backtest.entitlement_v3 import _exact_decimal, _snapshot_hash, value_rights
from stock_ai.backtest.positions_v3 import _check
from stock_ai.data.swing_v3_schema import instant


class AccountingError(ValueError):
    pass


def _require(condition,code):
    if not condition:raise AccountingError(code)


def expectancy_interval(trades,sessions):
    """(exit session, net amount) pairs; all trades of a session move together."""
    sessions=tuple(sessions);trades=tuple(trades)
    if len(set(sessions))!=len(sessions) or list(sessions)!=sorted(sessions):
        raise ValueError('invalid bootstrap sessions')
    if any(day not in sessions or not isinstance(pnl,Decimal) or not pnl.is_finite() for day,pnl in trades):
        raise ValueError('invalid bootstrap trade')
    if len(trades)<30:return dict(interval=None,reason='fewer_than_30_trades',resamples=0)
    if len(sessions)<10:return dict(interval=None,reason='fewer_than_10_sessions',resamples=0)
    grouped=[[pnl for d,pnl in trades if d==day] for day in sessions]
    rng=Random(20261121);samples=[]
    for _ in range(1000):
        days=[]
        while len(days)<len(sessions):
            start=rng.randrange(len(sessions))
            days.extend(grouped[(start+j)%len(sessions)] for j in range(10))
        values=[pnl for group in days[:len(sessions)] for pnl in group]
        if values:samples.append(float(sum(map(Fraction,values))/len(values)))
    samples.sort()
    return dict(interval=[samples[int(.025*(len(samples)-1))],samples[int(.975*(len(samples)-1))]] if samples else None,
                reason=None if samples else 'no_nonempty_resamples',resamples=len(samples))


def _risk(equities,initial):
    previous=initial;peak=initial;dd=0.;returns=[]
    for equity in equities:
        _require(equity>0,'nonpositive_equity')
        returns.append(float(Fraction(equity)/Fraction(previous)-1))
        peak=max(peak,equity);dd=max(dd,float((Fraction(peak)-Fraction(equity))/Fraction(peak)))
        previous=equity
    volatility=stdev(returns) if len(returns)>1 else 0
    annual=(float(Fraction(equities[-1])/Fraction(initial))**(252/len(equities))-1
            if len(equities)>=252 else None)
    sharpe=mean(returns)/volatility*sqrt(252) if volatility else None
    _require(all(isfinite(v) for v in (dd,annual,sharpe) if v is not None),'nonfinite_risk_statistic')
    return dict(max_drawdown=dd,annual_return=annual,sharpe_annualized=sharpe)


def evaluate_v3(snapshot,result,*,as_of):
    _require(result.get('synthetic') is True and result.get('qualified_for_real_data') is False,
             'synthetic_result_required')
    if not result.get('complete'):
        return dict(status='NOT_EVALUATED',reason=result.get('halt_reason') or result.get('status'),
                    metrics=None,qualified_for_real_data=False,statistical_edge_confirmed=False,adopted=False)
    _require(result.get('status')=='COMPLETED_SYNTHETIC','unexpected_completed_status')
    state=result['portfolio'];rights=result['rights'];curve=result['curve'];restated=result['restated_curve']
    _check(snapshot,state,state.cash.as_of)
    _require(state.cash.snapshot_sha256==rights.snapshot_sha256==_snapshot_hash(snapshot),'snapshot_mismatch')
    _require(not state.positions and not state.exits and not any(r.status=='pending' for r in state.cash.reservations),
             'nonterminal_portfolio')
    sessions=tuple(d for d in snapshot.sessions if snapshot.evaluation_start_session<=d<=snapshot.evaluation_end_session)
    _require(tuple(p['session'] for p in curve)==sessions and tuple(p['session'] for p in restated)==sessions,
             'incomplete_curves')
    initial=Decimal(str(result['config']['initial_cash']))
    _require(initial==state.cash.initial_cash,'initial_cash_mismatch')
    entries={p.position_id:p for p in state.entries};trades={t.position_id:t for t in state.trades}
    _require(len(entries)==len(state.entries) and len(trades)==len(state.trades) and entries.keys()==trades.keys(),
             'entry_trade_ownership_mismatch')
    orders={r.request.order_id:r for r in state.cash.reservations}
    filled={k for k,r in orders.items() if r.status=='filled'}
    _require(filled==entries.keys(),'filled_orders_mismatch')
    impact=(Fraction(Decimal(str(result['config']['spread_bps'])))/2
            +Fraction(Decimal(str(result['config']['slippage_bps']))))/10000
    fee=Decimal(str(result['config']['fee_per_side']));fee_cost=Decimal('0');impact_cost=Decimal('0')
    for identifier,entry in entries.items():
        order=orders[identifier];trade=trades[identifier]
        _require(trade.symbol==entry.symbol and trade.entry_session==entry.entry_session
                 and trade.holding_sessions==snapshot.sessions.index(trade.exit_session)-snapshot.sessions.index(entry.entry_session),
                 'trade_dates_or_holding_mismatch')
        _require(order.target_session==entry.entry_session,'entry_target_mismatch')
        if trade.reason=='period_end':
            _require(trade.exit_session==snapshot.evaluation_end_session
                     and trade.decision_at==result['terminal_policy']['registered_at'],'terminal_policy_mismatch')
        else:
            previous=snapshot.sessions[snapshot.sessions.index(trade.exit_session)-1]
            _require(instant(trade.decision_at)==instant(previous+'T07:00:00Z'),'exit_not_preordered')
        bar=next(b for b in snapshot.bars if b.symbol==entry.symbol and b.session_date==entry.entry_session)
        raw=Fraction(Decimal(bar.open));price=raw*(1+impact)
        _require(entry.quantity==order.request.quantity and entry.unit_basis_id==bar.unit_basis_id,
                 'entry_units_mismatch')
        _require(instant(order.decision_at)<instant(entry.entry_session+'T00:00:00Z'),'entry_not_preordered')
        _require(order.request.fee==fee and Fraction(order.request.impact_bps)/10000==impact,'entry_cost_contract_mismatch')
        _require(entry.total_cost_basis==_exact_decimal(price*entry.quantity+Fraction(fee)),'entry_basis_mismatch')
        quantity=Fraction(entry.quantity);basis=entry.unit_basis_id
        for s in sorted(snapshot.splits,key=lambda s:s.market_switch_date):
            if s.symbol==entry.symbol and entry.entry_session<s.market_switch_date<=trade.exit_session:
                _require(s.from_basis_id==basis,'exit_split_chain_mismatch')
                quantity*=Fraction(Decimal(s.ratio_new_per_old));basis=s.to_basis_id
        exit_bar=next(b for b in snapshot.bars if b.symbol==entry.symbol and b.session_date==trade.exit_session)
        exit_raw=Fraction(Decimal(exit_bar.close if trade.reason=='period_end' else exit_bar.open))
        exit_price=exit_raw*(1-impact)
        _require(quantity.denominator==1 and trade.quantity==quantity.numerator and basis==exit_bar.unit_basis_id,
                 'exit_units_mismatch')
        _require(trade.exit_fee==fee and trade.exit_price==_exact_decimal(exit_price),'exit_cost_contract_mismatch')
        _require(trade.net_proceeds==_exact_decimal(exit_price*trade.quantity-Fraction(fee)),'exit_proceeds_mismatch')
        _require(trade.total_cost_basis==entry.total_cost_basis and trade.price_pnl==_difference(trade.net_proceeds,entry.total_cost_basis),
                 'trade_price_pnl_mismatch')
        fee_cost=_sum((fee_cost,order.request.fee,trade.exit_fee))
        impact_cost=_sum((impact_cost,_exact_decimal(raw*entry.quantity*impact+exit_raw*trade.quantity*impact)))
    final=value_rights(snapshot,rights,as_of=as_of,mode='restated')
    _require(final.total is not None,'final_entitlement_unknown')
    amounts={(l.event_id,l.position_id):l.amount for l in final.lines}
    _require(all(l.position_id in entries for l in final.lines),'income_without_owned_trade')
    decisions={instant(f.as_of):f for f in rights.decisions}
    for point,rpoint in zip(curve,restated):
        day=point['session'];closing=instant(day+'T07:00:00Z')
        paid=_sum(p.amount for p in state.cash.payments if instant(p.recorded_at)<=closing)
        computed_cash=_exact_decimal(Fraction(initial)
            -sum((Fraction(p.total_cost_basis) for p in state.entries if p.entry_session<=day),Fraction(0))
            +sum((Fraction(t.net_proceeds) for t in state.trades if t.exit_session<=day),Fraction(0))+Fraction(paid))
        exposure=Fraction(0);position_count=0
        for identifier,entry in entries.items():
            if entry.entry_session<=day<trades[identifier].exit_session:
                quantity=Fraction(entry.quantity)
                for s in snapshot.splits:
                    if s.symbol==entry.symbol and entry.entry_session<s.market_switch_date<=day:
                        quantity*=Fraction(Decimal(s.ratio_new_per_old))
                bar=next(b for b in snapshot.bars if b.symbol==entry.symbol and b.session_date==day)
                exposure+=quantity*Fraction(Decimal(bar.close));position_count+=1
        _require(point['cash']==computed_cash and point['exposure']==_exact_decimal(exposure)
                 and point['positions']==position_count,'daily_cash_or_exposure_mismatch')
        _require(closing in decisions,'missing_decision_frame')
        d=decisions[closing];_require(d.total is not None,'unknown_completed_decision')
        unpaid=_difference(d.total,paid)
        _require(unpaid>=0 and point['receivable']==unpaid
                 and point['equity']==_sum((computed_cash,_exact_decimal(exposure),unpaid)),'decision_equity_mismatch')
        captured=[r for r in rights.rights if instant(r.captured_at)<=closing]
        keys={(r.event_id,r.position_id) for r in captured}
        _require(keys=={(l.event_id,l.position_id) for l in d.lines},'decision_entitlement_scope_mismatch')
        gross=_sum(amounts[key] for key in keys)
        for key in keys:
            received=_sum(p.amount for p in state.cash.payments if (p.event_id,p.position_id)==key and instant(p.recorded_at)<=closing)
            _require(received<=amounts[key],'payment_exceeds_final_entitlement')
        _require(rpoint.get('restated') is True and rpoint['equity']==_sum((computed_cash,_exact_decimal(exposure),_difference(gross,paid))),
                 'restated_equity_mismatch')
    income={identifier:_sum(l.amount for l in final.lines if l.position_id==identifier) for identifier in entries}
    net={identifier:_sum((t.price_pnl,income[identifier])) for identifier,t in trades.items()}
    net_pnl=_difference(restated[-1]['equity'],initial)
    _require(net_pnl==_sum(net.values()),'final_asset_vs_trade_pnl_mismatch')
    _require(state.cash.purchase_debits==_sum(p.total_cost_basis for p in entries.values())
             and state.cash.sale_credits==_sum(t.net_proceeds for t in trades.values()),'cash_totals_mismatch')
    _require(state.cash.distribution_credits==_sum(p.amount for p in state.cash.payments),'payment_totals_mismatch')
    values=list(net.values());wins=[v for v in values if v>0];losses=[v for v in values if v<0]
    d_risk=_risk([p['equity'] for p in curve],initial);r_risk=_risk([p['equity'] for p in restated],initial)
    ci=expectancy_interval([(trades[k].exit_session,v) for k,v in net.items()],sessions)
    average=lambda xs:float(sum(map(Fraction,xs))/len(xs)) if xs else None
    metrics=dict(net_pnl_yen=net_pnl,total_return=float(Fraction(net_pnl)/Fraction(initial)),
        decision_net_pnl_yen=_difference(curve[-1]['equity'],initial),annual_return=r_risk['annual_return'],
        max_drawdown=d_risk['max_drawdown'],max_drawdown_basis='decision',max_drawdown_restated=r_risk['max_drawdown'],
        sharpe_annualized=d_risk['sharpe_annualized'],sharpe_restated=r_risk['sharpe_annualized'],
        profit_factor=float(sum(map(Fraction,wins))/-sum(map(Fraction,losses))) if losses else None,
        win_rate=len(wins)/len(values) if values else None,average_win=average(wins),average_loss=average(losses),
        expectancy_yen=average(values),expectancy_95pct=ci['interval'],trade_count=len(values),
        average_holding_days=mean(t.holding_sessions for t in trades.values()) if trades else None,
        capital_utilization=mean(float(Fraction(p['exposure'])/Fraction(p['equity'])) for p in curve),
        total_cost_yen=_sum((fee_cost,impact_cost)),fee_cost_yen=fee_cost,impact_cost_yen=impact_cost,
        worst_trade_yen=min(values) if values else None,
        risk_budget_exceedances=sum(v < -Decimal(str(result['config']['trade_risk_yen'])) for v in values))
    reasons={}
    if not values:
        for key in ('win_rate','expectancy_yen','average_holding_days','worst_trade_yen'):reasons[key]='no_trades'
    if not wins:reasons['average_win']='no_winning_trades'
    if not losses:reasons.update(average_loss='no_losing_trades',profit_factor='no_losing_trades')
    if ci['reason']:reasons['expectancy_95pct']=ci['reason']
    if metrics['annual_return'] is None:reasons['annual_return']='fewer_than_252_sessions'
    if metrics['sharpe_annualized'] is None:reasons['sharpe_annualized']='zero_return_variance'
    if metrics['sharpe_restated'] is None:reasons['sharpe_restated']='zero_return_variance'
    _require(all(isfinite(v) for v in metrics.values() if isinstance(v,float)),'nonfinite_summary')
    return dict(status='EVALUATED_SYNTHETIC',metrics=metrics,unavailable_reasons=reasons,
                reconciliation='passed',trade_net_pnl=net,bootstrap=ci,
                assumptions={'tax':'pre_tax','risk_free_rate':0,'annualization_sessions':252,
                             'ci_block_sessions':10,'ci_repetitions':1000,'ci_seed':20261121},
                qualified_for_real_data=False,statistical_edge_confirmed=False,adopted=False,
                evidence_label='synthetic_not_market_evidence')
