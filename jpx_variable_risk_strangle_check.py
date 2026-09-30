"""Scan JPX option-price CSV archive coverage for late 2025.

Read-only archive availability check. No trading, no auth.
"""
from __future__ import annotations
import json, ssl, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

BASE="https://www.jpx.co.jp/automation/markets/derivatives/option-price/files/"
UA="crypto-paper-trader-public-jpx-coverage-scan/1.0"
START=date(2025,10,1)
END=date(2025,12,31)

def weekdays(a,b):
    d=a
    while d<=b:
        if d.weekday()<5:
            yield d
        d+=timedelta(days=1)

def probe(day):
    ds=day.strftime("%Y%m%d")
    url=f"{BASE}ose{ds}tp.csv"
    req=urllib.request.Request(url,method="GET",
        headers={"User-Agent":UA,"Range":"bytes=0-127"})
    try:
        with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=10) as resp:
            body=resp.read(128)
            return day, resp.status, len(body)
    except urllib.error.HTTPError as e:
        return day, e.code, 0
    except Exception:
        return day, -1, 0

def main():
    days=list(weekdays(START,END))
    rows=[]
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs=[ex.submit(probe,d) for d in days]
        for fut in as_completed(futs):
            day,status,n=fut.result()
            rows.append((day,status,n))
    rows.sort()
    ok=[d for d,s,n in rows if s in (200,206)]
    by_month={}
    for d,s,n in rows:
        by_month.setdefault(d.strftime("%Y%m"),{"ok":0,"not_found":0,"other":0})
        if s in (200,206):by_month[d.strftime("%Y%m")]["ok"]+=1
        elif s==404:by_month[d.strftime("%Y%m")]["not_found"]+=1
        else:by_month[d.strftime("%Y%m")]["other"]+=1
    print(json.dumps({
      "paper_only":True,
      "scan_start":START.isoformat(),"scan_end":END.isoformat(),
      "available_count":len(ok),
      "first_available":ok[0].isoformat() if ok else None,
      "last_available":ok[-1].isoformat() if ok else None,
      "by_month":by_month,
      "available_dates":[d.isoformat() for d in ok]
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
