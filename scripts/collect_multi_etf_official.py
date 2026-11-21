"""Bounded free official-page acquisition. One request per URL, no automatic retry."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

SOURCES={
    'cabinet-holidays':'https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv',
    'jpx-session-rules':'https://www.jpx.co.jp/faq/others_general.html',
    'jpx-daily-past-guide':'https://www.jpx.co.jp/markets/statistics-equities/daily/03.html',
    'nf-1321-split':'https://nextfunds.jp/news/2026/pd_261006a.html',
    'nf-1306-history':'https://www.nomura-am.co.jp/fund/etf/history/ETF_1306.csv',
    'nf-1321-history':'https://www.nomura-am.co.jp/fund/etf/history/ETF_1321.csv',
    'jpx-calendar':'https://www.jpx.co.jp/corporate/about-jpx/calendar/index.html',
    'jpx-1475-unit':'https://www.jpx.co.jp/news/1030/20240722-01.html',
    'jpx-1321-unit':'https://www.jpx.co.jp/news/1030/20260915-01.html',
    'nf-1306-split':'https://nextfunds.jp/news/2026/pd_260330a.html',
    'nf-1321-product':'https://nextfunds.jp/lineup/1321/',
    'jpx-daily-index':'https://www.jpx.co.jp/markets/statistics-equities/daily/index.html',
}


def validate_automatic_source(url):
    parsed=urlparse(url)
    if parsed.hostname in ('www.jpx.co.jp','jpx.co.jp'):
        path=parsed.path
        if '/statistics-equities/daily/' in path and path.rsplit('/',1)[-1] not in ('index.html','01.html','03.html'):
            raise ValueError('JPX historical price originals require manual acquisition')
        if '/automation/markets/statistics-equities/daily/' in path:
            raise ValueError('historical daily data acquisition is not automated')
    return url


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--only',nargs='+',choices=tuple(SOURCES))
    parser.add_argument('--ca-bundle',type=Path,help='Optional trusted CA bundle; TLS verification remains enabled')
    args=parser.parse_args()
    tls=ssl.create_default_context(cafile=str(args.ca_bundle) if args.ca_bundle else None)
    args.directory.mkdir(parents=True,exist_ok=False)
    records=[]
    for name,url in SOURCES.items():
        if args.only and name not in args.only:
            continue
        validate_automatic_source(url)
        record=dict(name=name,url=url,request_started_at_utc=datetime.now(timezone.utc).isoformat())
        try:
            with urlopen(Request(url,headers={'User-Agent':'stock-ai-local-research/0.1'}),timeout=20,context=tls) as response:
                payload=response.read(8_000_001)
                if len(payload)>8_000_000:
                    raise ValueError('response exceeds collection limit')
                record.update(status=response.status,final_url=response.url,content_type=response.headers.get('Content-Type'))
            suffix=Path(url).suffix or '.html'
            path=args.directory/(name+suffix)
            with path.open('xb') as f:
                f.write(payload)
            record.update(path=str(path),sha256=hashlib.sha256(payload).hexdigest(),bytes=len(payload))
        except HTTPError as exc:
            record.update(status=exc.code,error=str(exc),retry_count=0)
        except (URLError,TimeoutError,ValueError) as exc:
            record.update(status='FAILED',error=str(exc),retry_count=0)
        record['retrieved_at_utc']=datetime.now(timezone.utc).isoformat()
        records.append(record)
        print(json.dumps(record,ensure_ascii=False),flush=True)
        # Persist partial success/failure, including interruption after a completed request.
        with (args.directory/(name+'.meta.json')).open('x') as f:
            json.dump(record,f,ensure_ascii=False,indent=2)
    with (args.directory/'manifest.json').open('x') as f:
        json.dump(dict(role='official_evidence_acquisition_no_pnl',requests=records),f,ensure_ascii=False,indent=2)


if __name__=='__main__':
    main()
