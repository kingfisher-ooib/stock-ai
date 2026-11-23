"""Synthetic-only prior-close execution experiment; never a live order interface."""
from dataclasses import asdict
from decimal import Decimal, ROUND_FLOOR
from math import floor, isfinite

from stock_ai.backtest.swing import SwingConfig, signal
from stock_ai.data.multi_etf import audit_dataset, history_at, lot_at


def buy_limit(close, tick):
    if not isfinite(tick) or tick <= 0:
        raise ValueError('positive synthetic tick required')
    quantum = Decimal(str(tick))
    return float((Decimal(str(close)) * Decimal('1.01') / quantum)
                 .to_integral_value(rounding=ROUND_FLOOR) * quantum)


def run_swing_v2(data, *, strategy, start, end, config=None, priority=None):
    audit_dataset(data)
    if not data.get('synthetic'):
        raise ValueError('v2 is synthetic-only; real-data execution is not qualified')
    if strategy not in ('cash', 'hold', 'A', 'B', 'C') or start > end:
        raise ValueError('invalid experiment')
    cfg = config or SwingConfig()
    instruments = data['instruments']
    order = priority if priority is not None else sorted(instruments)
    if set(order) != set(instruments) or len(order) != len(set(order)):
        raise ValueError('priority must cover universe exactly')
    calendar = data['calendar']
    indices = [i for i, day in enumerate(calendar) if start <= day <= end]
    if not indices or calendar[indices[0]] != start or calendar[indices[-1]] != end:
        raise ValueError('empty or incomplete period')
    if strategy != 'cash' and indices[0] == 0:
        raise ValueError('prior session required to freeze orders')
    for instrument in instruments.values():
        buy_limit(1, instrument.get('price_tick_yen', .1))
    cash = cfg.initial_cash
    positions, pending, exits, receivables = {}, {}, set(), []
    fills, trades, curve, rejections, orders = [], [], [], [], []
    total_cost = 0.
    previous_equity = cash
    daily_exit = False

    def place(symbol, index, equity, remaining, hold=False):
        history = history_at(instruments[symbol], index)
        close = history[-1]['close']
        if hold:
            active, stop = True, 0.
        else:
            active, stop, _ = signal(history, strategy)
        if not active or (not hold and stop <= 0):
            return remaining
        limit = buy_limit(close, instruments[symbol].get('price_tick_yen', .1))
        entry = limit * (1 + cfg.impact)
        lot = lot_at(instruments[symbol], calendar[index])
        allocation = equity * (min(cfg.max_position_ratio, 1 / len(order)) if hold else cfg.max_position_ratio)
        quantities = [(allocation - cfg.fee_per_side) / entry,
                      (remaining - cfg.fee_per_side) / entry]
        if not hold:
            risk = entry - stop * (1 - cfg.impact)
            if risk <= 0:
                return remaining
            quantities.append((cfg.trade_risk_yen - 2 * cfg.fee_per_side) / risk)
        quantity = floor(min(quantities) / lot) * lot
        if quantity <= 0:
            rejections.append(dict(date=calendar[index], symbol=symbol, reason='minimum_lot_or_budget'))
            return remaining
        reservation = quantity * entry + cfg.fee_per_side
        pending[symbol] = dict(created_date=calendar[index], quantity=quantity, lot=lot,
                               limit=limit, stop=stop, reservation=reservation)
        orders.append(dict(symbol=symbol, **pending[symbol]))
        return remaining - reservation

    def sell(symbol, price, day, index, reason):
        nonlocal cash, total_cost
        position = positions[symbol]
        if position['quantity'] % lot_at(instruments[symbol], day):
            raise ValueError('position cannot be sold in current lot')
        position = positions.pop(symbol)
        cost = position['quantity'] * price * cfg.impact + cfg.fee_per_side
        proceeds = position['quantity'] * price - cost
        cash += proceeds
        total_cost += cost
        trades.append(dict(symbol=symbol, entry_date=position['entry_date'], exit_date=day,
                           quantity=position['quantity'], net_pnl=proceeds-position['basis']+position['income'],
                           holding_days=index-position['entry_index'], reason=reason,
                           cost=position['entry_cost']+cost))

    if strategy == 'hold':
        remaining = cash
        for symbol in order[:cfg.max_positions]:
            remaining = place(symbol, indices[0]-1, cash, remaining, hold=True)
    for index in indices:
        day = calendar[index]
        # Existing orders were funded before today's dividends and sales.
        available = cash
        for symbol, position in positions.items():
            for event in instruments[symbol]['actions']:
                if event['date'] != day:
                    continue
                if event['kind'] == 'split':
                    quantity = position['quantity'] * event['ratio']
                    if not float(quantity).is_integer():
                        raise ValueError('fractional corporate-action position unsupported')
                    position['quantity'] = int(quantity)
                    position['stop'] /= event['ratio']
                else:
                    value = position['quantity'] * event['amount']
                    position['income'] += value
                    receivables.append(dict(pay_date=event['pay_date'], value=value))
        for due in list(receivables):
            if due['pay_date'] <= day:
                cash += due['value']
                receivables.remove(due)
        for symbol in list(positions):
            if symbol in exits:
                sell(symbol, instruments[symbol]['bars'][index]['open'], day, index,
                     'daily_loss_prior_close' if daily_exit else 'prior_close_exit')
        for symbol in order:
            if symbol not in pending:
                continue
            p = pending[symbol]
            price = instruments[symbol]['bars'][index]['open'] * (1 + cfg.impact)
            debit = p['quantity'] * price + cfg.fee_per_side
            if (symbol in positions or len(positions) >= cfg.max_positions
                    or p['lot'] != lot_at(instruments[symbol], day)
                    or any(e['date'] == day for e in instruments[symbol]['actions'])
                    or price > p['limit'] or debit > min(cash, available, p['reservation'])):
                rejections.append(dict(date=day, symbol=symbol, reason='execution_or_frozen_budget'))
                continue
            cost = p['quantity'] * instruments[symbol]['bars'][index]['open'] * cfg.impact + cfg.fee_per_side
            cash -= debit
            available -= debit
            total_cost += cost
            positions[symbol] = dict(quantity=p['quantity'], stop=p['stop'], basis=debit,
                                     income=0., entry_cost=cost, entry_date=day, entry_index=index)
            fills.append(dict(date=day, symbol=symbol, quantity=p['quantity'], price=price,
                              order_date=p['created_date'], limit=p['limit']))
        pending, exits = {}, set()
        if index == indices[-1]:
            for symbol in list(positions):
                sell(symbol, instruments[symbol]['bars'][index]['close'], day, index, 'period_end')
        exposure = sum(p['quantity'] * instruments[s]['bars'][index]['close'] for s, p in positions.items())
        equity = cash + exposure + sum(r['value'] for r in receivables)
        curve.append(dict(date=day, equity=equity, cash=cash, exposure=exposure, positions=len(positions)))
        if cash < -1e-7:
            raise RuntimeError('negative cash')
        daily_exit = (strategy in ('A', 'B', 'C')
                      and equity-previous_equity <= -previous_equity*cfg.max_daily_loss_ratio)
        previous_equity = equity
        if index == indices[-1] or strategy in ('cash', 'hold'):
            continue
        for symbol, position in positions.items():
            history = history_at(instruments[symbol], index)
            _, _, sma = signal(history, strategy)
            if (daily_exit or history[-1]['close'] <= position['stop']
                    or history[-1]['close'] <= sma
                    or index-position['entry_index']+1 >= cfg.max_holding_days):
                exits.add(symbol)
        if daily_exit:
            continue
        remaining = cash
        for symbol in order:
            if len(positions) + len(pending) >= cfg.max_positions:
                break
            if symbol not in positions and index >= 59:
                remaining = place(symbol, index, equity, remaining)
    return dict(strategy=strategy, config=asdict(cfg), curve=curve, trades=trades, fills=fills,
                rejections=rejections, orders=orders, total_cost=total_cost, synthetic=True,
                execution_model='prior_close_v2', qualified_for_real_data=False)
