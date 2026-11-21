"""Spot-market sessions from Cabinet Office holidays and JPX closure rules."""
import csv
from datetime import date, timedelta
from io import StringIO


def spot_sessions(holiday_csv, *, start, end):
    first,last=date.fromisoformat(start),date.fromisoformat(end)
    if first>last:
        raise ValueError('invalid calendar period')
    rows=list(csv.reader(StringIO(holiday_csv.decode('cp932'))))
    if not rows or rows[0]!=['国民の祝日・休日月日','国民の祝日・休日名称']:
        raise ValueError('unexpected Cabinet Office CSV schema')
    holidays={}
    for row in rows[1:]:
        if len(row)!=2 or not row[1].strip():
            raise ValueError('invalid holiday row')
        y,m,d=map(int,row[0].split('/'))
        day=date(y,m,d)
        if day in holidays:
            raise ValueError('duplicate holiday')
        holidays[day]=row[1]
    for year in range(first.year,last.year+1):
        yearly=[d for d in holidays if d.year==year]
        if date(year,1,1) not in holidays or len(yearly)<16:
            raise ValueError(f'holiday year absent or incomplete: {year}')
    sessions=[]
    current=first
    while current<=last:
        year_end=current.month==12 and current.day==31
        year_start=current.month==1 and current.day<=3
        if current.weekday()<5 and current not in holidays and not year_end and not year_start:
            sessions.append(current.isoformat())
        current+=timedelta(days=1)
    return sessions
