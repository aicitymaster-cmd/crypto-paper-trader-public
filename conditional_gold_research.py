"""PAPER-only conditional GOLD target-touch research over two years.

Optimized version: candidate entry windows are precomputed once, then reused
across strategy parameters. Research only; no orders, auth, or broker claims.
"""
from __future__ import annotations
import itertools, json, ssl, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from statistics import median
from cross_market_backtest import Bar, run_window

HOST="query1.finance.yahoo.com"; SYMBOL="GC=F"; RANGE="2y"; INTERVAL="1h"
START=10_000.0; TARGET=50_000.0
LEVS=(75,100,125)
MAS=((4,12),(6,18),(9,27))
STOPS=(0.005,0.0075,0.01)
TAKES=(0.04,0.08)
WEEKDAYS=(0,1,2,3,4)
HOURS=(0,4,8,12,16,20)
VOL_THRESHOLDS=(0.0,0.01,0.02,0.03)
SPREAD=5.0; FEE=1.0
MIN_WINDOWS=12

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

def precompute_candidates(bars):
    by_ts={b.ts:b for b in bars}
    starts=[]
    for b in bars:
        ts=b.ts.replace(minute=0,second=0,microsecond=0)
        if ts.weekday() not in WEEKDAYS or ts.hour not in HOURS:
            continue
        hist=[x for x in bars if ts-timedelta(hours=24)<=x.ts<ts]
        if len(hist)<8: continue
        mv=abs(hist[-1].close/hist[0].close-1.0)
        chunk=[x for x in bars if ts<=x.ts<ts+timedelta(days=7)]
        if len(chunk)<=max(s for _,s in MAS): continue
        starts.append((ts,mv,chunk))
    return starts

def summ(rows):
    n=len(rows); finals=[r.final_yen for r in rows]
    hits=sum(r.target_hit for r in rows); z=sum(v<=0 for v in finals)
    return {"windows":n,"target_hits":hits,"target_rate_pct":round(100*hits/n,4) if n else 0,
            "zero_finish_rate_pct":round(100*z/n,4) if n else 0,
            "median_final_yen":round(median(finals),2) if n else 0,
            "best_final_yen":round(max(finals),2) if n else 0,
            "worst_final_yen":round(min(finals),2) if n else 0}

def score(row):
    s=row["summary"]
    return (s["target_rate_pct"], min(s["windows"],26), -s["zero_finish_rate_pct"])

def main():
    bars=parse(fetch())
    candidates=precompute_candidates(bars)
    rows=[]
    for wd,hr,mv,lev,(fast,slow),st,tp in itertools.product(WEEKDAYS,HOURS,VOL_THRESHOLDS,LEVS,MAS,STOPS,TAKES):
        chosen=[chunk for ts,move,chunk in candidates if ts.weekday()==wd and ts.hour==hr and move>=mv and len(chunk)>slow]
        if len(chosen)<MIN_WINDOWS: continue
        rs=[run_window(chunk,start_yen=START,leverage=float(lev),spread_bps=SPREAD,fee_bps=FEE,
            fast=fast,slow=slow,stop_pct=st,take_pct=tp,target_yen=TARGET,ruin_yen=0.0) for chunk in chosen]
        rows.append({"weekday":wd,"utc_hour":hr,"min_abs_24h_move":mv,
                     "leverage_equivalent":lev,"fast":fast,"slow":slow,
                     "stop_pct":st,"take_pct":tp,"summary":summ(rs)})
    rows.sort(key=score,reverse=True)
    robust=[r for r in rows if r["summary"]["windows"]>=20]
    print(json.dumps({"paper_only":True,"range":RANGE,"interval":INTERVAL,
        "baseline_long_horizon_best_rate_pct":17.3077,
        "min_windows":MIN_WINDOWS,"tested_cases":len(rows),
        "top_20_any":rows[:20],"top_20_windows_ge_20":robust[:20],
        "warning":"conditional search can overfit; observed historical rates are not future probabilities or executable broker terms"},
        ensure_ascii=False,sort_keys=True))

if __name__=="__main__": main()
