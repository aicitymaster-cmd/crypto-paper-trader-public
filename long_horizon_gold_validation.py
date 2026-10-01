"""Longer-horizon PAPER validation of the current best GOLD region.

Uses Yahoo public chart data at 1h / 2y to avoid relying on the overlapping
60-day 30m sample. Research only.
"""
from __future__ import annotations
import json, ssl, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone
from statistics import median
from cross_market_backtest import Bar, run_window

HOST="query1.finance.yahoo.com"
SYMBOL="GC=F"
RANGE="2y"
INTERVAL="1h"
START=10_000.0
TARGET=50_000.0
LEVS=(75,100,125)
MAS=((4,12),(6,18),(9,27))
STOPS=(0.005,0.0075,0.01)
TAKES=(0.04,0.08)
SPREAD=5.0
FEE=1.0

def fetch():
    sym=urllib.parse.quote(SYMBOL,safe="")
    url=f"https://{HOST}/v8/finance/chart/{sym}?range={RANGE}&interval={INTERVAL}&includePrePost=false&events=div%2Csplits"
    req=urllib.request.Request(url,headers={"User-Agent":"aicity-paper-research/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=20,context=ssl.create_default_context()) as r:
        body=r.read(12_000_001)
    if len(body)>12_000_000: raise RuntimeError("BODY_TOO_LARGE")
    return json.loads(body)

def parse(p):
    res=((p.get("chart") or {}).get("result") or [])[0]
    ts=res.get("timestamp") or []
    q=((res.get("indicators") or {}).get("quote") or [{}])[0]
    out=[]
    for i,t in enumerate(ts):
        vals=[q.get(k,[None]*len(ts))[i] for k in ("open","high","low","close")]
        if any(v is None for v in vals): continue
        o,h,l,c=map(float,vals)
        if min(o,h,l,c)<=0: continue
        out.append(Bar(datetime.fromtimestamp(int(t),tz=timezone.utc),c,o,h,l))
    return out

def windows(bars,fast,slow,lev,st,tp):
    out=[]
    cursor=bars[0].ts.replace(hour=0,minute=0,second=0,microsecond=0)
    end=bars[-1].ts
    while cursor+timedelta(days=7)<=end:
        stop=cursor+timedelta(days=7)
        chunk=[b for b in bars if cursor<=b.ts<stop]
        if len(chunk)>slow:
            out.append(run_window(chunk,start_yen=START,leverage=float(lev),spread_bps=SPREAD,fee_bps=FEE,
                fast=fast,slow=slow,stop_pct=st,take_pct=tp,target_yen=TARGET,ruin_yen=0.0))
        cursor+=timedelta(days=7)  # non-overlapping windows for cleaner validation
    return out

def summ(rows):
    n=len(rows); finals=[r.final_yen for r in rows]; hits=sum(r.target_hit for r in rows); z=sum(v<=0 for v in finals)
    return {"windows":n,"target_hits":hits,"target_rate_pct":round(100*hits/n,4) if n else 0,
            "zero_finish_rate_pct":round(100*z/n,4) if n else 0,
            "median_final_yen":round(median(finals),2) if n else 0,
            "best_final_yen":round(max(finals),2) if n else 0,
            "worst_final_yen":round(min(finals),2) if n else 0}

def main():
    bars=parse(fetch()); rows=[]
    for lev in LEVS:
      for fast,slow in MAS:
       for st in STOPS:
        for tp in TAKES:
          rs=windows(bars,fast,slow,lev,st,tp)
          rows.append({"leverage_equivalent":lev,"fast":fast,"slow":slow,"stop_pct":st,"take_pct":tp,"summary":summ(rs)})
    rows.sort(key=lambda r:(r["summary"]["target_rate_pct"],-r["summary"]["zero_finish_rate_pct"]),reverse=True)
    print(json.dumps({"paper_only":True,"range":RANGE,"interval":INTERVAL,"bars":len(bars),
      "method":"non-overlapping 7-day windows","tested_cases":len(rows),"top_15":rows[:15],
      "warning":"generic leveraged simulation, not broker execution or future probability"},ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
