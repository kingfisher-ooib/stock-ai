"""Deterministic implementation fixture. Not market data or profitability evidence."""
from datetime import date, timedelta


def synthetic_dataset(n=85, symbols=('1475','1306','1321','1346','2558')):
    days=[]
    day=date(2024,1,1)
    while len(days)<n:
        if day.weekday()<5:
            days.append(day.isoformat())
        day+=timedelta(days=1)
    instruments={}
    for s in symbols:
        bars=[]
        for j,d in enumerate(days):
            p=100+j*.2
            bars.append(dict(bar_date=d,open=p,high=p+.5,low=p-.5,close=p+.1,
                             volume=10000,observed_at=d+'T08:00:00+00:00',source='synthetic fixture'))
        instruments[s]=dict(price_basis='raw',bars=bars,lots=[dict(date=days[0],size=10)],actions=[])
    return dict(synthetic=True,calendar=days,calendar_source='synthetic weekdays, not JPX',instruments=instruments)
