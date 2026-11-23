"""Synthetic-only I5 orchestration. No real-data permission or performance search."""
from dataclasses import asdict, replace
from decimal import Decimal
from fractions import Fraction
from math import isfinite

from stock_ai.backtest.cash_v3 import (
    BuyRequest, _difference, _sum, available_cash, cash_balance,
    outstanding_receivable, receive_distributions,
)
from stock_ai.backtest.entitlement_v3 import (
    _exact_decimal, capture_rights, new_book, record_decision, value_rights,
)
from stock_ai.backtest.positions_v3 import (
    apply_market_splits, capture_portfolio_rights, execute_buy, execute_sell,
    freeze_portfolio_buys, mark_close, new_portfolio, plan_exit,
)
from stock_ai.backtest.swing import SwingConfig, signal
from stock_ai.backtest.terminal_v3 import TerminalPolicy, execute_final_open, liquidate_terminal
from stock_ai.data.swing_v3_schema import Snapshot, instant, validate_snapshot


def _decimal(value):
    return Decimal(str(value))


def run_swing_v3(snapshot, *, as_of, source_blobs, strategy, priority, config=None):
    # Revalidate models to avoid implicit promotion of legacy/dict inputs.
    if not isinstance(snapshot,Snapshot) or snapshot.synthetic is not True:
        raise ValueError('v3 requires a synthetic v3 snapshot')
    snapshot=Snapshot.model_validate_json(snapshot.model_dump_json())
    validate_snapshot(snapshot,as_of=as_of,source_blobs=source_blobs)
    cfg=config or SwingConfig();priority=tuple(priority)
    if strategy not in ('cash','hold','A','B','C') or len(priority)!=len(set(priority)) or set(priority)!=set(snapshot.symbols):
        raise ValueError('invalid strategy or explicit priority')
    days=snapshot.sessions;start=snapshot.evaluation_start_session;end=snapshot.evaluation_end_session
    if days[-1]!=end:
        raise ValueError('prototype requires calendar ending at evaluation end')
    first=days.index(start);initial_at=days[first-1]+'T07:00:00Z'
    initial=_decimal(cfg.initial_cash);risk=_decimal(cfg.trade_risk_yen)
    ratio=_decimal(cfg.max_position_ratio);impact_bps=_decimal(cfg.spread_bps)/2+_decimal(cfg.slippage_bps)
    fee=_decimal(cfg.fee_per_side);impact=Fraction(impact_bps)/10000
    for rule in snapshot.execution_rules:
        if (Decimal(rule.fee_per_side)!=fee or Decimal(rule.spread_bps)!=_decimal(cfg.spread_bps)
                or Decimal(rule.slippage_bps)!=_decimal(cfg.slippage_bps)):
            raise ValueError('configuration and synthetic execution cost assumptions disagree')
    policy=TerminalPolicy(end,initial_at,impact_bps,fee)
    portfolio=new_portfolio(snapshot,as_of=initial_at,initial_cash=initial)
    rights=new_book(snapshot)
    for session in sorted({e.ex_session for e in snapshot.entitlements if e.ex_session<start}):
        rights=capture_rights(snapshot,rights,ex_session=session,holdings=())
    rights=record_decision(snapshot,rights,decision_at=initial_at)
    curve=[];frames=[];stages=[];rejections=[];stops={};previous=initial

    def history(symbol,day):
        cutoff=instant(day+'T07:00:00Z')
        bars=sorted((b for b in snapshot.bars if b.symbol==symbol and b.session_date<=day),key=lambda b:b.session_date)
        if len(bars)<60 or any(instant(b.available_at)>cutoff for b in bars):
            raise ValueError('decision history unavailable at cutoff')
        result=[dict(bar_date=b.session_date,**{k:float(getattr(b,k)) for k in ('open','high','low','close','volume')}) for b in bars]
        for s in snapshot.splits:
            if s.symbol==symbol and s.market_switch_date<=day:
                if instant(s.available_at)>cutoff:
                    raise ValueError('split history not known at cutoff')
                for b in result:
                    if b['bar_date']<s.market_switch_date:
                        for k in ('open','high','low','close'):b[k]/=float(s.ratio_new_per_old)
                        b['volume']*=float(s.ratio_new_per_old)
        return result

    def build_buys(state,day,target,equity,hold=False):
        remaining=available_cash(snapshot,state.cash,as_of=day+'T07:00:00Z')
        requests=[]
        candidates=priority[:cfg.max_positions] if hold else priority
        for symbol in candidates:
            if len(state.positions)+len(requests)>=cfg.max_positions:break
            if any(p.symbol==symbol for p in state.positions):continue
            rule=next(r for r in snapshot.execution_rules if r.symbol==symbol and r.start_session<=target<=r.end_session)
            cutoff=instant(day+'T07:00:00Z')
            if instant(rule.available_at)>cutoff:raise ValueError('execution assumption not known before order')
            active_lots=sorted((r for r in snapshot.lots if r.symbol==symbol and r.effective_session<=day),key=lambda r:r.effective_session)
            lot=active_lots[-1]
            if instant(lot.available_at)>cutoff:raise ValueError('order lot unknown')
            known_actions=(any(s.symbol==symbol and s.market_switch_date==target and instant(s.available_at)<=cutoff for s in snapshot.splits)
                           or any(e.symbol==symbol and e.ex_session==target and instant(e.available_at)<=cutoff for e in snapshot.entitlements)
                           or any(r.symbol==symbol and r.effective_session==target and instant(r.available_at)<=cutoff for r in snapshot.lots))
            if known_actions:
                rejections.append(dict(session=day,symbol=symbol,reason='known_next_session_action'));continue
            h=history(symbol,day);close=_decimal(h[-1]['close'])
            if hold:active,stop=True,close  # Nonoperative reference: hold never uses stop.
            else:
                active,stop,_=signal(h,strategy)
                if not isfinite(stop):raise ValueError('nonfinite signal stop')
                stop=_decimal(stop)
            if not active or stop<=0:continue
            tick=Fraction(Decimal(rule.tick_yen));ticks=(Fraction(close)*Fraction(101,100))//tick
            limit=_exact_decimal(tick*ticks)
            if limit<=0:continue
            entry=Fraction(limit)*(1+impact)
            allocation=Fraction(equity)*min(Fraction(ratio),Fraction(1,len(priority))) if hold else Fraction(equity)*Fraction(ratio)
            bounds=[(allocation-Fraction(fee))/entry,(Fraction(remaining)-Fraction(fee))/entry]
            if not hold:
                unit_risk=entry-Fraction(stop)*(1-impact)
                if unit_risk<=0:continue
                bounds.append((Fraction(risk)-2*Fraction(fee))/unit_risk)
            quantity=(min(bounds)//lot.size)*lot.size
            if quantity<=0:
                rejections.append(dict(session=day,symbol=symbol,reason='minimum_lot_or_budget'));continue
            identifier=f'{target}:{symbol}'
            request=BuyRequest(identifier,symbol,int(quantity),lot.size,limit,impact_bps,fee)
            requests.append(request);stops[identifier]=stop
            remaining=_exact_decimal(Fraction(remaining)-(entry*quantity+Fraction(fee)))
        return freeze_portfolio_buys(snapshot,state,decision_at=day+'T07:00:00Z',target_session=target,requests=requests)

    def output(status,reason=None):
        return dict(status=status,halt_reason=reason,synthetic=True,qualified_for_real_data=False,
                    strategy=strategy,config=asdict(cfg),priority=priority,terminal_policy=asdict(policy),
                    curve=tuple(curve),restated_curve=None,portfolio=portfolio,rights=rights,
                    stages=tuple(stages),rejections=tuple(rejections),complete=False)

    if strategy=='hold':portfolio=build_buys(portfolio,days[first-1],start,initial,hold=True)
    for index in range(first,len(days)):
        day=days[index];opening=day+'T00:00:00Z';closing=day+'T07:00:00Z'
        if any(e.ex_session==day for e in snapshot.entitlements):
            rights=capture_portfolio_rights(snapshot,portfolio,rights,ex_session=day)
        stages.append((day,'rights_before_split'))
        portfolio=apply_market_splits(snapshot,portfolio,session=day)
        stages.append((day,'market_splits'))
        cash=receive_distributions(snapshot,rights,portfolio.cash,as_of=opening)
        portfolio=replace(portfolio,cash=cash)
        if outstanding_receivable(snapshot,rights,cash,as_of=opening) is None:
            return output('HALT_UNRESOLVED_VALUATION','opening_entitlement_unknown')
        stages.append((day,'cash_before_frozen_fills'))
        for instruction in tuple(portfolio.exits):
            portfolio=(execute_final_open(snapshot,portfolio,sell_id=instruction.sell_id,policy=policy)
                       if day==end else execute_sell(snapshot,portfolio,sell_id=instruction.sell_id,at=opening))
        stages.append((day,'prior_close_sells'))
        for order in tuple(portfolio.cash.reservations):
            if order.status=='pending':
                portfolio=execute_buy(snapshot,portfolio,order_id=order.request.order_id,at=opening,stop=stops[order.request.order_id])
        stages.append((day,'frozen_buys'))
        portfolio=replace(portfolio,cash=receive_distributions(snapshot,rights,portfolio.cash,as_of=closing))
        portfolio=mark_close(snapshot,portfolio,session=day)
        if day==end:
            portfolio=liquidate_terminal(snapshot,portfolio,policy).portfolio
            stages.append((day,'predeclared_terminal_close'))
        exposure=Decimal('0')
        for p in portfolio.positions:
            bar=next(b for b in snapshot.bars if b.symbol==p.symbol and b.session_date==day)
            if instant(bar.available_at)>instant(closing):raise ValueError('close not known at valuation')
            exposure=_sum((exposure,_exact_decimal(Fraction(p.quantity)*Fraction(Decimal(bar.close)))))
        rights=record_decision(snapshot,rights,decision_at=closing)
        unpaid=outstanding_receivable(snapshot,rights,portfolio.cash,as_of=closing)
        if unpaid is None:return output('HALT_UNRESOLVED_VALUATION','closing_entitlement_unknown')
        cash_total=cash_balance(snapshot,portfolio.cash,as_of=closing);equity=_sum((cash_total,exposure,unpaid))
        curve.append(dict(session=day,cash=cash_total,exposure=exposure,receivable=unpaid,equity=equity,positions=len(portfolio.positions)))
        frames.append((portfolio,rights))
        stages.append((day,'decision_close'))
        daily_loss=(strategy in ('A','B','C') and Fraction(equity)-Fraction(previous)<=-Fraction(previous)*Fraction(_decimal(cfg.max_daily_loss_ratio)))
        previous=equity
        if day==end:continue
        if strategy not in ('cash','hold'):
            for p in portfolio.positions:
                h=history(p.symbol,day);_,_,sma=signal(h,strategy)
                if (daily_loss or _decimal(h[-1]['close'])<=p.stop or h[-1]['close']<=sma
                        or index-days.index(p.entry_session)+1>=cfg.max_holding_days):
                    portfolio=plan_exit(snapshot,portfolio,sell_id=f'exit:{day}:{p.position_id}',position_id=p.position_id,
                        decision_at=closing,target_session=days[index+1],impact_bps=impact_bps,fee=fee,
                        reason='daily_loss_prior_close' if daily_loss else 'prior_close_exit')
            if not daily_loss:portfolio=build_buys(portfolio,day,days[index+1],equity)
    final=value_rights(snapshot,rights,as_of=as_of,mode='restated')
    amounts={(l.event_id,l.position_id):l.amount for l in final.lines}
    restated=[]
    for point,(state,history_rights) in zip(curve,frames):
        values=[amounts[(r.event_id,r.position_id)] for r in history_rights.rights]
        if any(v is None for v in values):return output('HALT_INCOMPLETE_FINAL_AMOUNTS','restatement_not_final')
        gross=_sum(values);paid=_sum(p.amount for p in state.cash.payments)
        payment_keys={(p.event_id,p.position_id) for p in state.cash.payments}
        overpaid=any(amounts[key]<_sum(p.amount for p in state.cash.payments
                      if (p.event_id,p.position_id)==key) for key in payment_keys)
        if overpaid:return output('HALT_REPAYMENT_UNSUPPORTED','final_amount_below_cash_received')
        restated.append(dict(session=point['session'],equity=_sum((point['cash'],point['exposure'],_difference(gross,paid))),restated=True))
    result=output('COMPLETED_SYNTHETIC')
    result.update(complete=True,restated_curve=tuple(restated))
    return result
