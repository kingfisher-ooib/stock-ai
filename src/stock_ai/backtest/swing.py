"""Deterministic multi-ETF swing simulation, with prior-close frozen orders."""
from dataclasses import dataclass, asdict
from datetime import datetime, time, date, timezone
from math import floor, isfinite, sqrt
from random import Random
from statistics import mean, stdev

from stock_ai.data.multi_etf import audit_dataset, history_at, lot_at, quality_reasons, timestamp
from stock_ai.features.technical import compute_features


def execution_model_reasons(strategy):
    """Known chronology defects in frozen v1; data-verification flags cannot fix them."""
    if strategy in ('A', 'B', 'C'):
        return ['opening_price_lower_bound_cancellation_not_preordered',
                'open_equity_stop_filled_at_same_open']
    return []


@dataclass(frozen=True)
class SwingConfig:
    initial_cash: float = 100000
    trade_risk_yen: float = 100
    max_position_ratio: float = .05
    max_positions: int = 3
    max_daily_loss_ratio: float = .02
    max_holding_days: int = 5
    spread_bps: float = 6
    slippage_bps: float = 2
    fee_per_side: float = 0

    def __post_init__(self):
        values = asdict(self)
        if not all(isfinite(v) for v in values.values()):
            raise ValueError('nonfinite configuration')
        if (self.initial_cash <= 0 or self.trade_risk_yen <= 0
                or not 0 < self.max_position_ratio <= 1
                or not 0 < self.max_daily_loss_ratio <= 1
                or type(self.max_positions) is not int or not 1 <= self.max_positions <= 3
                or type(self.max_holding_days) is not int or not 1 <= self.max_holding_days <= 5
                or min(self.spread_bps,self.slippage_bps,self.fee_per_side) < 0
                or self.impact >= 1):
            raise ValueError('invalid configuration')

    @property
    def impact(self):
        return (self.spread_bps / 2 + self.slippage_bps) / 10000


def signal(history, strategy):
    f = compute_features(*[[b[k] for b in history] for k in ('high','low','close','volume')])
    close = history[-1]['close']
    trend = f['sma20'] > f['sma60']
    if strategy == 'A':
        active = trend and close > f['sma20'] and f['macd_histogram'] > 0
    elif strategy == 'B':
        active = trend and close < f['sma20'] and 40 <= f['rsi14'] <= 50
    elif strategy == 'C':
        active = (trend and close > max(b['high'] for b in history[-21:-1])
                  and history[-1]['volume'] >= 1.5 * mean(b['volume'] for b in history[-21:-1]))
    else:
        raise ValueError('unknown strategy')
    return active, close - f['atr14'], f['sma20']


def run_swing(data, *, strategy, start, end, config=None, priority=None):
    cfg = config or SwingConfig()
    if strategy not in ('cash','hold','A','B','C') or start > end:
        raise ValueError('invalid experiment')
    audit_dataset(data)
    instruments = data['instruments']
    if any(quality_reasons(data, i) for i in instruments.values()):
        raise ValueError('unqualified real data')
    order = priority or sorted(instruments)
    if set(order) != set(instruments) or len(order) != len(set(order)):
        raise ValueError('priority must cover universe exactly')
    calendar = data['calendar']
    indices = [i for i,d in enumerate(calendar) if start <= d <= end]
    if not indices or calendar[indices[0]] != start or calendar[indices[-1]] != end:
        raise ValueError('empty or incomplete period')
    if not data.get('synthetic') and data['availability_mode'] == 'observed':
        # Validate before simulation, including baselines and the final session.
        # Historical warmup is first used at the first decision, not its own date.
        used_indices = range(indices[-1]+1) if strategy in ('A','B','C') else indices
        for index in used_indices:
            first_use_day = calendar[max(index, indices[0])]
            decision_time = datetime.combine(date.fromisoformat(first_use_day), time(23,59), timezone.utc)
            if any(timestamp(i['bars'][index]['observed_at']) > decision_time for i in instruments.values()):
                raise ValueError('decision uses a bar not yet observed; explicit historical assumption required')
    if not data.get('synthetic') and execution_model_reasons(strategy):
        raise ValueError('legacy swing execution is synthetic-only: '
                         + ', '.join(execution_model_reasons(strategy)))
    cash = cfg.initial_cash
    positions, pending, exits, receivables = {}, {}, set(), []
    trades, curve, rejections, fills = [], [], [], []
    total_cost = 0.
    previous_equity = cash

    def sell(symbol, price, day, index, reason):
        nonlocal cash, total_cost
        if positions[symbol]['quantity'] % lot_at(instruments[symbol], day):
            # Odd-lot handling is not modelled; never invent an executable sale.
            raise ValueError('position cannot be sold in current lot; odd-lot handling unsupported')
        p = positions.pop(symbol)
        cost = p['quantity'] * price * cfg.impact + cfg.fee_per_side
        proceeds = p['quantity'] * price - cost
        cash += proceeds
        total_cost += cost
        trades.append(dict(symbol=symbol, entry_date=p['entry_date'], exit_date=day,
                           quantity=p['quantity'], net_pnl=proceeds-p['basis']+p['income'],
                           holding_days=index-p['entry_index'], reason=reason,
                           cost=p['entry_cost']+cost))

    for index in indices:
        day = calendar[index]
        # Cash available before this day's sales; sale proceeds cannot fund today's entries.
        available = cash
        for due in list(receivables):
            if due['pay_date'] <= day:
                cash += due['value']
                available += due['value']
                receivables.remove(due)
        for symbol in list(positions):
            p = positions[symbol]
            for e in instruments[symbol]['actions']:
                if e['date'] != day:
                    continue
                if e['kind'] == 'split':
                    quantity = p['quantity'] * e['ratio']
                    if not float(quantity).is_integer():
                        raise ValueError('fractional corporate-action position unsupported')
                    p['quantity'] = int(quantity)
                    p['stop'] /= e['ratio']
                else:
                    income = p['quantity'] * e['amount']
                    p['income'] += income
                    receivables.append(dict(pay_date=e['pay_date'], value=income))
        open_equity = cash + sum(r['value'] for r in receivables) + sum(
            p['quantity'] * instruments[s]['bars'][index]['open'] for s,p in positions.items())
        # The frozen buy-and-hold comparator has no stop-loss; only the active
        # swing strategies use the portfolio daily loss control.
        daily_stop = (strategy in ('A', 'B', 'C')
                      and open_equity - previous_equity <= -previous_equity*cfg.max_daily_loss_ratio)
        sold = set()
        for symbol in list(positions):
            if daily_stop or symbol in exits:
                sell(symbol, instruments[symbol]['bars'][index]['open'], day, index,
                     'daily_loss' if daily_stop else 'prior_close_exit')
                sold.add(symbol)
        if strategy == 'hold' and index == indices[0]:
            # Equal fixed capped allocation, no hindsight price selection.
            for s in order[:cfg.max_positions]:
                price = instruments[s]['bars'][index]['open']
                lot = lot_at(instruments[s], day)
                budget = min(available, cfg.initial_cash * min(cfg.max_position_ratio, 1/len(order)))
                q = floor((budget-cfg.fee_per_side)/(price*(1+cfg.impact))/lot)*lot
                if q > 0:
                    pending[s] = dict(quantity=q, limit=float('inf'), stop=0, lot=lot)
        for symbol in order:
            if symbol not in pending or symbol in positions:
                continue
            p = pending[symbol]
            bar = instruments[symbol]['bars'][index]
            price = bar['open']
            q = p['quantity']
            debit = q*price*(1+cfg.impact)+cfg.fee_per_side
            # Pending orders crossing actions/lot changes expire, avoiding stale quantities.
            corporate_day = any(e['date'] == day for e in instruments[symbol]['actions'])
            if (daily_stop or symbol in sold or len(positions) >= cfg.max_positions
                    or p['lot'] != lot_at(instruments[symbol],day)
                    or q % lot_at(instruments[symbol],day) or corporate_day
                    or price > p['limit'] or price <= p['stop'] or debit > min(cash,available)):
                rejections.append(dict(date=day,symbol=symbol,reason='execution_or_risk_constraint'))
                continue
            cost = q*price*cfg.impact + cfg.fee_per_side
            cash -= debit
            available -= debit
            total_cost += cost
            positions[symbol] = dict(quantity=q, stop=p['stop'], basis=debit,
                                     income=0., entry_cost=cost, entry_date=day, entry_index=index)
            fills.append(dict(date=day,symbol=symbol,quantity=q,price=price*(1+cfg.impact)))
        pending, exits = {}, set()
        if index == indices[-1]:
            for symbol in list(positions):
                sell(symbol,instruments[symbol]['bars'][index]['close'],day,index,'period_end')
        exposure = sum(p['quantity']*instruments[s]['bars'][index]['close'] for s,p in positions.items())
        equity = cash + exposure + sum(r['value'] for r in receivables)
        curve.append(dict(date=day,equity=equity,cash=cash,exposure=exposure,
                          positions=len(positions)))
        if cash < -1e-7:
            raise RuntimeError('negative cash')
        previous_equity = equity
        if index == indices[-1] or strategy in ('cash','hold'):
            continue
        for s,p in positions.items():
            h = history_at(instruments[s],index)
            _,_,sma = signal(h,strategy)
            if h[-1]['close'] <= p['stop'] or h[-1]['close'] <= sma or index-p['entry_index']+1 >= cfg.max_holding_days:
                exits.add(s)
        remaining = cash
        for s in order:
            if s in positions or index < 59:
                continue
            h = history_at(instruments[s],index)
            active,stop,_ = signal(h,strategy)
            if not active or stop <= 0:
                continue
            limit = h[-1]['close'] * 1.01
            entry = limit*(1+cfg.impact)
            risk = entry-stop*(1-cfg.impact)
            lot = lot_at(instruments[s],day)
            q = floor(min((cfg.trade_risk_yen-2*cfg.fee_per_side)/risk,
                          equity*cfg.max_position_ratio/entry,
                          (remaining-cfg.fee_per_side)/entry)/lot)*lot
            if q <= 0:
                rejections.append(dict(date=day,symbol=s,reason='minimum_lot_or_budget'))
                continue
            pending[s] = dict(quantity=q,limit=limit,stop=stop,lot=lot)
            remaining -= q*entry+cfg.fee_per_side
    return dict(strategy=strategy,config=asdict(cfg),curve=curve,trades=trades,fills=fills,
                rejections=rejections,total_cost=total_cost,synthetic=data.get('synthetic',False))


def summarize_swing(result):
    curve, trades = result['curve'], result['trades']
    initial = result['config']['initial_cash']
    pnl = [t['net_pnl'] for t in trades]
    wins, losses = [x for x in pnl if x>0], [x for x in pnl if x<0]
    peak, dd, previous, returns = initial, 0., initial, []
    for point in curve:
        equity = point['equity']
        returns.append(equity/previous-1 if previous>0 else 0.)
        peak = max(peak,equity)
        dd = max(dd,(peak-equity)/peak)
        previous = equity
    ci = None
    if len(pnl)>=30 and len(curve)>=10:
        grouped = [[t['net_pnl'] for t in trades if t['exit_date']==p['date']] for p in curve]
        rng, samples = Random(20261121), []
        for _ in range(1000):
            days=[]
            while len(days)<len(curve):
                first=rng.randrange(len(curve))
                days.extend(grouped[(first+j)%len(curve)] for j in range(10))
            values=[x for day in days[:len(curve)] for x in day]
            if values:
                samples.append(mean(values))
        if samples:
            samples.sort()
            ci=[samples[int(.025*(len(samples)-1))],samples[int(.975*(len(samples)-1))]]
    net=curve[-1]['equity']-initial
    spread=stdev(returns) if len(returns)>1 else 0
    return dict(net_pnl_yen=net,total_return=net/initial,
                annual_return=(curve[-1]['equity']/initial)**(252/len(curve))-1 if len(curve)>=252 and curve[-1]['equity']>0 else None,
                max_drawdown=dd,sharpe_annualized=mean(returns)/spread*sqrt(252) if spread else None,
                profit_factor=sum(wins)/-sum(losses) if losses else None,
                win_rate=len(wins)/len(pnl) if pnl else None,
                average_win=mean(wins) if wins else None,average_loss=mean(losses) if losses else None,
                expectancy_yen=mean(pnl) if pnl else None,expectancy_95pct=ci,
                trade_count=len(pnl),average_holding_days=mean(t['holding_days'] for t in trades) if trades else None,
                capital_utilization=mean(p['exposure']/p['equity'] if p['equity']>0 else 0 for p in curve),
                total_cost_yen=result['total_cost'],statistical_edge_confirmed=False,
                worst_trade_yen=min(pnl) if pnl else None,
                risk_budget_exceedances=sum(x < -result['config']['trade_risk_yen'] for x in pnl))
