"""PAPER-only holdout validation for frozen GOLD entry filter.

Frozen candidate from prior discovery:
Thursday 16:00 UTC, abs 24h move >=1%, 125x equivalent, MA 6/18,
stop 0.75% or 1.0%, take 8%. Evaluates chronological first vs second half.
"""
from __future__ import annotations
import json, ssl, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from statistics import median
from bisect import bisect_left
from cross_market_backtest import Bar, run_window

HOST="query1.finance.yahoo.com"; SYMBOL="GC=F"; RANGE="2y"; INTERVAL="1h"
START=10_000.0; TARGET=50_000.0
WEEKDAY=3; UTC_HOUR=16; MIN_MOVE=0.01
LEVERAGE=125; FAST=6; SLOW=18; STOPS=(0.0075,0.01); TAKE=0.08
SPREAD=5.0; FEE=1.0

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
    ts=res.get("timestamp") or []; q=((res.get("indicators") or {}).get("quote") or [{}])[0]
    out=[]
    for i,t in enumerate(ts):
        vals=[q.get(k,[None]*len(ts))[i] for k in ("open","high","low","close")]
        if any(v is None for v in vals): continue
        o,h,l,c=map(float,vals)
        if min(o,h,l,c)<=0: continue
        out.append(Bar(datetime.fromtimestamp(int(t),tz=timezone.utc),c,o,h,l))
    return out

def candidates(bars):
    times=[b.ts for b in bars]; out=[]
    for i,b in enumerate(bars):
        ts=b.ts
        if ts.weekday()!=WEEKDAY or ts.hour!=UTC_HOUR: continue
        h0=bisect_left(times,ts-timedelta(hours=24))
        hist=bars[h0:i]
        if len(hist)<8: continue
        mv=abs(hist[-1].close/hist[0].close-1.0)
        if mv<MIN_MOVE: continue
        e=bisect_left(times,ts+timedelta(days=7),lo=i)
        chunk=bars[i:e]
        if len(chunk)>SLOW: out.append((ts,chunk))
    return out

def summ(rows):
    n=len(rows); finals=[r.final_yen for r in rows]; hits=sum(r.target_hit for r in rows); z=sum(v<=0 for v in finals)
    return {"windows":n,"target_hits":hits,"target_rate_pct":round(100*hits/n,4) if n else 0,
            "zero_finish_rate_pct":round(100*z/n,4) if n else 0,
            "median_final_yen":round(median(finals),2) if n else 0,
            "best_final_yen":round(max(finals),2) if n else 0,
            "worst_final_yen":round(min(finals),2) if n else 0}

def run(rows,stop):
    return [run_window(chunk,start_yen=START,leverage=float(LEVERAGE),spread_bps=SPREAD,fee_bps=FEE,
        fast=FAST,slow=SLOW,stop_pct=stop,take_pct=TAKE,target_yen=TARGET,ruin_yen=0.0) for _,chunk in rows]

def main():
    bars=parse(fetch()); c=candidates(bars)
    midpoint=bars[0].ts + (bars[-1].ts-bars[0].ts)/2
    first=[x for x in c if x[0]<midpoint]; second=[x for x in c if x[0]>=midpoint]
    cases={}
    for st in STOPS:
        cases[str(st)]={"first_half":summ(run(first,st)),"second_half_holdout":summ(run(second,st)),
                        "all":summ(run(c,st))}
    print(json.dumps({"paper_only":True,"frozen_filter":{"weekday":WEEKDAY,"utc_hour":UTC_HOUR,
      "min_abs_24h_move":MIN_MOVE,"leverage_equivalent":LEVERAGE,"fast":FAST,"slow":SLOW,"take_pct":TAKE},
      "midpoint":midpoint.isoformat(),"cases":cases,
      "warning":"holdout is chronological within the same 2y source; still historical simulation, not future probability or broker-executable terms"},
      ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
