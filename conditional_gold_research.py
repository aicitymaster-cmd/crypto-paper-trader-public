"""PAPER-only conditional GOLD target-touch research over two years.

Strategy parameters are frozen from prior long-horizon leaders. This stage
tests only entry filters (weekday, UTC hour, recent 24h move), reducing
multiple-testing/overfit versus re-optimizing all strategy knobs.
"""
from __future__ import annotations
import itertools, json, ssl, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from statistics import median
from cross_market_backtest import Bar, run_window

HOST="query1.finance.yahoo.com"; SYMBOL="GC=F"; RANGE="2y"; INTERVAL="1h"
START=10_000.0; TARGET=50_000.0
FROZEN=(
    (125,6,18,0.0075,0.08),
    (125,6,18,0.01,0.08),
    (100,6,18,0.01,0.08),
    (75,6,18,0.005,0.08),
)
WEEKDAYS=(0,1,2,3,4)
HOURS=(0,4,8,12,16,20)
VOL_THRESHOLDS=(0.0,0.01,0.02,0.03)
SPREAD=5.0; FEE=1.0; MIN_WINDOWS=12

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

def candidate_starts(bars):
    out=[]
    for i,b in enumerate(bars):
        ts=b.ts
        if ts.weekday() not in WEEKDAYS or ts.hour not in HOURS: continue
        hist=[x for x in bars if ts-timedelta(hours=24)<=x.ts<ts]
        if len(hist)<8: continue
        chunk=[x for x in bars if ts<=x.ts<ts+timedelta(days=7)]
        if len(chunk)<=18: continue
        mv=abs(hist[-1].close/hist[0].close-1.0)
        out.append((ts,mv,chunk))
    return out

def summ(rows):
    n=len(rows); finals=[r.final_yen for r in rows]
    hits=sum(r.target_hit for r in rows); z=sum(v<=0 for v in finals)
    return {"windows":n,"target_hits":hits,"target_rate_pct":round(100*hits/n,4) if n else 0,
            "zero_finish_rate_pct":round(100*z/n,4) if n else 0,
            "median_final_yen":round(median(finals),2) if n else 0,
            "best_final_yen":round(max(finals),2) if n else 0,
            "worst_final_yen":round(min(finals),2) if n else 0}

def main():
    bars=parse(fetch()); starts=candidate_starts(bars); rows=[]
    for wd,hr,mv,(lev,fast,slow,st,tp) in itertools.product(WEEKDAYS,HOURS,VOL_THRESHOLDS,FROZEN):
        chunks=[chunk for ts,move,chunk in starts if ts.weekday()==wd and ts.hour==hr and move>=mv]
        if len(chunks)<MIN_WINDOWS: continue
        rs=[run_window(chunk,start_yen=START,leverage=float(lev),spread_bps=SPREAD,fee_bps=FEE,
            fast=fast,slow=slow,stop_pct=st,take_pct=tp,target_yen=TARGET,ruin_yen=0.0) for chunk in chunks]
        rows.append({"weekday":wd,"utc_hour":hr,"min_abs_24h_move":mv,
                     "leverage_equivalent":lev,"fast":fast,"slow":slow,
                     "stop_pct":st,"take_pct":tp,"summary":summ(rs)})
    rows.sort(key=lambda r:(r["summary"]["target_rate_pct"],min(r["summary"]["windows"],26),-r["summary"]["zero_finish_rate_pct"]),reverse=True)
    robust=[r for r in rows if r["summary"]["windows"]>=20]
    print(json.dumps({"paper_only":True,"range":RANGE,"interval":INTERVAL,
        "baseline_long_horizon_best_rate_pct":17.3077,
        "frozen_strategy_count":len(FROZEN),"tested_filter_cases":len(rows),
        "top_20_any":rows[:20],"top_20_windows_ge_20":robust[:20],
        "warning":"filters were selected on the same history and still need holdout validation; observed rates are not future probabilities or broker terms"},
        ensure_ascii=False,sort_keys=True))

if __name__=="__main__": main()
