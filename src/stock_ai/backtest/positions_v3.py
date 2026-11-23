"""Synthetic I4 position/cost-basis integration; no venue or strategy runner."""
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction

from stock_ai.backtest.cash_v3 import (
    CashBook, _amount, _check as check_cash, _difference, _jst_day, _sum,
    credit_sale, freeze_buys, new_cash_book, settle_buy,
)
from stock_ai.backtest.entitlement_v3 import (
    Holding, _exact_decimal, capture_rights, value_rights,
)
from stock_ai.data.swing_v3_schema import instant


@dataclass(frozen=True)
class Position:
    position_id: str
    symbol: str
    quantity: int
    unit_basis_id: str
    total_cost_basis: Decimal
    stop: Decimal
    entry_session: str


@dataclass(frozen=True)
class SellInstruction:
    sell_id: str
    position_id: str
    decision_at: str
    target_session: str
    impact_bps: Decimal
    fee: Decimal
    reason: str


@dataclass(frozen=True)
class ClosedTrade:
    sell_id: str
    position_id: str
    symbol: str
    quantity: int
    entry_session: str
    exit_session: str
    total_cost_basis: Decimal
    net_proceeds: Decimal
    price_pnl: Decimal
    holding_sessions: int
    exit_price: Decimal
    exit_fee: Decimal
    decision_at: str
    reason: str


@dataclass(frozen=True)
class Portfolio:
    cash: CashBook
    positions: tuple[Position, ...] = ()
    entries: tuple[Position, ...] = ()
    applied_splits: tuple[str, ...] = ()
    exits: tuple[SellInstruction, ...] = ()
    trades: tuple[ClosedTrade, ...] = ()

    @property
    def qualified_for_real_data(self):
        return False


def _check(snapshot, state, at):
    check_cash(snapshot, state.cash, at)
    if (_sum(p.total_cost_basis for p in state.entries) != state.cash.purchase_debits
            or _sum(t.net_proceeds for t in state.trades) != state.cash.sale_credits):
        raise ValueError('position journal and cash ledger disagree')
    ids = {p.position_id for p in state.entries}
    if (len(ids) != len(state.entries) or len({p.symbol for p in state.positions}) != len(state.positions)
            or len(state.positions) > 3
            or len({t.position_id for t in state.trades}) != len(state.trades)
            or {p.position_id for p in state.positions} & {t.position_id for t in state.trades}
            or ids != {p.position_id for p in state.positions} | {t.position_id for t in state.trades}):
        raise ValueError('invalid position ownership journal')


def new_portfolio(snapshot, *, as_of, initial_cash=Decimal('100000')):
    # Empty initial holdings: past splits do not create positions or income.
    applied = tuple(s.event_id for s in snapshot.splits
                    if instant(s.market_switch_date+'T00:00:00Z') <= instant(as_of))
    return Portfolio(new_cash_book(snapshot, as_of=as_of, initial_cash=initial_cash),
                     applied_splits=applied)


def _splits_current(snapshot, state, session):
    if any(s.market_switch_date <= session and s.event_id not in state.applied_splits
           for s in snapshot.splits):
        raise ValueError('market split must be processed first')


def mark_close(snapshot, state, *, session):
    at = session+'T07:00:00Z'
    _check(snapshot, state, at)
    if session not in snapshot.sessions:
        raise ValueError('unknown close session')
    _splits_current(snapshot, state, session)
    return replace(state, cash=replace(state.cash, as_of=at))


def freeze_portfolio_buys(snapshot, state, *, decision_at, target_session, requests):
    _check(snapshot, state, decision_at)
    _splits_current(snapshot,state,_jst_day(decision_at))
    cash = freeze_buys(snapshot, state.cash, decision_at=decision_at,
                       target_session=target_session, requests=requests,
                       occupied_symbols=tuple(p.symbol for p in state.positions))
    return replace(state, cash=cash)


def capture_portfolio_rights(snapshot, state, book, *, ex_session):
    i = snapshot.sessions.index(ex_session)
    if i == 0:
        raise ValueError('prior session required')
    previous = snapshot.sessions[i-1]
    if instant(state.cash.as_of) != instant(previous+'T07:00:00Z'):
        raise ValueError('prior-close portfolio snapshot required')
    _check(snapshot, state, state.cash.as_of)
    _splits_current(snapshot, state, previous)
    holdings = tuple(Holding(p.position_id,p.symbol,p.quantity,p.unit_basis_id,previous)
                     for p in state.positions)
    return capture_rights(snapshot, book, ex_session=ex_session, holdings=holdings)


def apply_market_splits(snapshot, state, *, session):
    at = session+'T00:00:00Z'
    _check(snapshot, state, at)
    if session not in snapshot.sessions:
        raise ValueError('unknown split session')
    if any(s.market_switch_date < session and s.event_id not in state.applied_splits
           for s in snapshot.splits):
        raise ValueError('earlier market split missing')
    events = [s for s in snapshot.splits if s.market_switch_date == session]
    if any(s.event_id in state.applied_splits or instant(s.available_at) > instant(at)
           for s in events):
        raise ValueError('split already processed or not yet known')
    positions = list(state.positions)
    for event in events:
        target_basis=next(b for b in snapshot.unit_bases if b.basis_id==event.to_basis_id)
        if instant(target_basis.available_at)>instant(at):
            raise ValueError('split target unit basis not yet known')
        for i, p in enumerate(positions):
            if p.symbol != event.symbol:
                continue
            if p.unit_basis_id != event.from_basis_id:
                raise ValueError('position split unit chain mismatch')
            quantity = Fraction(p.quantity)*Fraction(Decimal(event.ratio_new_per_old))
            if quantity.denominator != 1:
                raise ValueError('fractional position unsupported')
            stop = _exact_decimal(Fraction(p.stop)/Fraction(Decimal(event.ratio_new_per_old)))
            positions[i] = replace(p,quantity=int(quantity),stop=stop,unit_basis_id=event.to_basis_id)
    result = replace(state, cash=replace(state.cash,as_of=at),positions=tuple(positions),
                     applied_splits=state.applied_splits+tuple(s.event_id for s in events))
    _check(snapshot,result,at)
    return result


def execute_buy(snapshot, state, *, order_id, at, stop, fill=True):
    _check(snapshot,state,at);_amount(stop,positive=True)
    if type(fill) is not bool:
        raise ValueError('explicit boolean fill assumption required')
    orders = [r for r in state.cash.reservations if r.request.order_id == order_id]
    if len(orders) != 1 or orders[0].status != 'pending':
        raise ValueError('unknown or already processed buy')
    order=orders[0];request=order.request;session=_jst_day(at)
    _splits_current(snapshot,state,session)
    if any(p.symbol==request.symbol for p in state.positions):
        raise ValueError('cannot add to an existing symbol')
    rules=[r for r in snapshot.lots if r.symbol==request.symbol and r.effective_session<=session]
    rule=max(rules,key=lambda r:r.effective_session)
    if instant(rule.available_at)>instant(at):
        raise ValueError('current lot not known')
    corporate_day = (any(s.symbol==request.symbol and s.market_switch_date==session for s in snapshot.splits)
                     or any(e.symbol==request.symbol and e.ex_session==session for e in snapshot.entitlements))
    if any(e.symbol==request.symbol and e.ex_session==session and instant(e.available_at)>instant(at)
           for e in snapshot.entitlements):
        raise ValueError('corporate schedule not known at execution time')
    bars=[b for b in snapshot.bars if b.symbol==request.symbol and b.session_date==session]
    if len(bars)!=1:
        raise ValueError('opening bar missing')
    bar=bars[0]
    price=_exact_decimal(Fraction(Decimal(bar.open))*(1+Fraction(request.impact_bps)/10000))
    permitted=(fill and not corporate_day and rule.size==request.lot_size and price<=request.limit)
    cash=settle_buy(snapshot,state.cash,order_id=order_id,at=at,fill_price=price if permitted else None)
    if not permitted:
        return replace(state,cash=cash)
    basis_record=next(b for b in snapshot.unit_bases if b.basis_id==bar.unit_basis_id)
    if instant(basis_record.available_at)>instant(at):
        raise ValueError('buy unit basis not yet known')
    basis=_exact_decimal(Fraction(price)*request.quantity+Fraction(request.fee))
    position=Position(order_id,request.symbol,request.quantity,bar.unit_basis_id,basis,stop,session)
    result=replace(state,cash=cash,positions=state.positions+(position,),entries=state.entries+(position,))
    _check(snapshot,result,at)
    return result


def plan_exit(snapshot,state,*,sell_id,position_id,decision_at,target_session,
               impact_bps,fee,reason):
    _check(snapshot,state,decision_at);_amount(impact_bps);_amount(fee)
    day=_jst_day(decision_at)
    _splits_current(snapshot,state,day)
    if (day not in snapshot.sessions or instant(decision_at)!=instant(day+'T07:00:00Z')
            or snapshot.sessions.index(day)+1>=len(snapshot.sessions)
            or snapshot.sessions[snapshot.sessions.index(day)+1]!=target_session):
        raise ValueError('sell must be planned at prior close for next open')
    closed={t.sell_id for t in state.trades}
    if (not sell_id or not reason or sell_id in closed or any(e.sell_id==sell_id or e.position_id==position_id for e in state.exits)
            or not any(p.position_id==position_id for p in state.positions)
            or impact_bps>=10000):
        raise ValueError('invalid or duplicate exit instruction')
    instruction=SellInstruction(sell_id,position_id,decision_at,target_session,impact_bps,fee,reason)
    return replace(state,cash=replace(state.cash,as_of=decision_at),exits=state.exits+(instruction,))


def execute_sell(snapshot,state,*,sell_id,at):
    _check(snapshot,state,at)
    instructions=[e for e in state.exits if e.sell_id==sell_id]
    if len(instructions)!=1:
        raise ValueError('no pending sell instruction')
    e=instructions[0]
    if instant(at)!=instant(e.target_session+'T00:00:00Z'):
        raise ValueError('sell is not at its planned synthetic open')
    _splits_current(snapshot,state,e.target_session)
    matches=[p for p in state.positions if p.position_id==e.position_id]
    if len(matches)!=1:
        raise ValueError('no owned position to sell')
    p=matches[0]
    rule=max((r for r in snapshot.lots if r.symbol==p.symbol and r.effective_session<=e.target_session),
             key=lambda r:r.effective_session)
    if instant(rule.available_at)>instant(at) or p.quantity%rule.size:
        raise ValueError('position unsellable in known current lot')
    bar=next(b for b in snapshot.bars if b.symbol==p.symbol and b.session_date==e.target_session)
    if bar.unit_basis_id!=p.unit_basis_id:
        raise ValueError('sell price and position units disagree')
    price=Fraction(Decimal(bar.open))*(1-Fraction(e.impact_bps)/10000)
    proceeds=_exact_decimal(price*p.quantity-Fraction(e.fee))
    _amount(proceeds,positive=True)
    cash=credit_sale(snapshot,state.cash,transaction_id=sell_id,net_amount=proceeds,at=at,source='synthetic')
    trade=ClosedTrade(sell_id,p.position_id,p.symbol,p.quantity,p.entry_session,e.target_session,
                       p.total_cost_basis,proceeds,_difference(proceeds,p.total_cost_basis),
                       snapshot.sessions.index(e.target_session)-snapshot.sessions.index(p.entry_session),
                       _exact_decimal(price),e.fee,e.decision_at,e.reason)
    result=replace(state,cash=cash,positions=tuple(x for x in state.positions if x.position_id!=p.position_id),
                     exits=tuple(x for x in state.exits if x.sell_id!=sell_id),trades=state.trades+(trade,))
    _check(snapshot,result,at)
    return result


def attributed_trade(snapshot,rights,trade,*,as_of,mode='restated'):
    if instant(as_of)<instant(trade.exit_session+'T00:00:00Z'):
        raise ValueError('trade attribution predates exit')
    valuation=value_rights(snapshot,rights,as_of=as_of,mode=mode)
    lines=[l for l in valuation.lines if l.position_id==trade.position_id]
    income=None if any(l.amount is None for l in lines) else _sum(l.amount for l in lines)
    return dict(position_id=trade.position_id,as_of=as_of,mode=mode,price_pnl=trade.price_pnl,
                distribution_income=income,net_pnl=None if income is None else _sum((trade.price_pnl,income)))
