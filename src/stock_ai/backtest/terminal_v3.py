"""Predeclared synthetic final-close liquidation, separate from frozen I3/I4."""
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction

from stock_ai.backtest.cash_v3 import CashLot, _amount, _difference, _sum
from stock_ai.backtest.entitlement_v3 import _exact_decimal
from stock_ai.backtest.positions_v3 import ClosedTrade, Portfolio, _check, _splits_current
from stock_ai.data.swing_v3_schema import instant


@dataclass(frozen=True)
class TerminalPolicy:
    end_session: str
    registered_at: str
    impact_bps: Decimal
    fee: Decimal


@dataclass(frozen=True)
class TerminalResult:
    portfolio: Portfolio
    terminal: bool = True


def _policy_check(snapshot,policy):
    _amount(policy.impact_bps);_amount(policy.fee)
    start=snapshot.evaluation_start_session
    previous=snapshot.sessions[snapshot.sessions.index(start)-1]
    if (policy.end_session!=snapshot.evaluation_end_session or policy.impact_bps>=10000
            or instant(policy.registered_at)>instant(previous+'T07:00:00Z')):
        raise ValueError('invalid predeclared terminal liquidation')


def execute_final_open(snapshot,state,*,sell_id,policy):
    """Honor a prior-close sell on the last open without inventing a next day.

    Its cash is for terminal valuation and cannot fund already frozen buys.
    """
    _policy_check(snapshot,policy)
    end=policy.end_session;at=end+'T00:00:00Z'
    _check(snapshot,state,at);_splits_current(snapshot,state,end)
    instructions=[e for e in state.exits if e.sell_id==sell_id]
    if end!=snapshot.evaluation_end_session or len(instructions)!=1:
        raise ValueError('invalid final opening instruction')
    e=instructions[0]
    if e.target_session!=end or instant(e.decision_at)>=instant(at):
        raise ValueError('final opening sale was not preordered')
    p=next(p for p in state.positions if p.position_id==e.position_id)
    rule=max((r for r in snapshot.lots if r.symbol==p.symbol and r.effective_session<=end),
             key=lambda r:r.effective_session)
    bar=next(b for b in snapshot.bars if b.symbol==p.symbol and b.session_date==end)
    if instant(rule.available_at)>instant(at) or p.quantity%rule.size or bar.unit_basis_id!=p.unit_basis_id:
        raise ValueError('final opening position not executable in synthetic model')
    price=_exact_decimal(Fraction(Decimal(bar.open))*(1-Fraction(e.impact_bps)/10000))
    proceeds=_exact_decimal(Fraction(price)*p.quantity-Fraction(e.fee));_amount(proceeds,positive=True)
    identifier='sale:'+sell_id
    if identifier in state.cash.receipts:raise ValueError('duplicate final opening sale')
    cash=replace(state.cash,as_of=at,
        lots=state.cash.lots+(CashLot(identifier,proceeds,end+'T07:00:00Z',at,'final_open_valuation_only'),),
        receipts=state.cash.receipts+(identifier,),sale_credits=_sum((state.cash.sale_credits,proceeds)))
    trade=ClosedTrade(sell_id,p.position_id,p.symbol,p.quantity,p.entry_session,end,p.total_cost_basis,
        proceeds,_difference(proceeds,p.total_cost_basis),snapshot.sessions.index(end)-snapshot.sessions.index(p.entry_session),
        price,e.fee,e.decision_at,e.reason)
    result=replace(state,cash=cash,positions=tuple(x for x in state.positions if x.position_id!=p.position_id),
        exits=tuple(x for x in state.exits if x.sell_id!=sell_id),trades=state.trades+(trade,))
    _check(snapshot,result,at)
    return result


def liquidate_terminal(snapshot, state, policy):
    _policy_check(snapshot,policy)
    end=policy.end_session;at=end+'T07:00:00Z'
    _check(snapshot,state,at);_splits_current(snapshot,state,end)
    if state.exits or any(r.status=='pending' for r in state.cash.reservations):
        raise ValueError('invalid predeclared terminal liquidation')
    cash=state.cash;trades=list(state.trades)
    for p in state.positions:
        rule=max((r for r in snapshot.lots if r.symbol==p.symbol and r.effective_session<=end),
                 key=lambda r:r.effective_session)
        bar=next(b for b in snapshot.bars if b.symbol==p.symbol and b.session_date==end)
        if (instant(rule.available_at)>instant(at) or p.quantity%rule.size
                or bar.unit_basis_id!=p.unit_basis_id or instant(bar.available_at)>instant(at)):
            raise ValueError('terminal position or close data not executable in synthetic model')
        price=_exact_decimal(Fraction(Decimal(bar.close))*(1-Fraction(policy.impact_bps)/10000))
        proceeds=_exact_decimal(Fraction(price)*p.quantity-Fraction(policy.fee));_amount(proceeds,positive=True)
        identifier='sale:terminal:'+p.position_id
        if identifier in cash.receipts:
            raise ValueError('duplicate terminal receipt')
        # End-of-run valuation cash only, not a broker cash-availability claim.
        lot=CashLot(identifier,proceeds,at,at,'terminal_valuation_only')
        cash=replace(cash,as_of=at,lots=cash.lots+(lot,),receipts=cash.receipts+(identifier,),
                     sale_credits=_sum((cash.sale_credits,proceeds)))
        trades.append(ClosedTrade('terminal:'+p.position_id,p.position_id,p.symbol,p.quantity,
            p.entry_session,end,p.total_cost_basis,proceeds,_difference(proceeds,p.total_cost_basis),
            snapshot.sessions.index(end)-snapshot.sessions.index(p.entry_session),price,policy.fee,
            policy.registered_at,'period_end'))
    result=replace(state,cash=replace(cash,as_of=at),positions=(),trades=tuple(trades))
    _check(snapshot,result,at)
    return TerminalResult(result)
