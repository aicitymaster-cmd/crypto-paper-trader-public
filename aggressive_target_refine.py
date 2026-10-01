"""Focused PAPER-only refinement around the best GOLD target-touch region."""
from __future__ import annotations
import itertools, json
from statistics import median
from datetime import timedelta
from cross_market_backtest import run_window
from cross_market_public_run import fetch_chart, parse_chart

START=10_000.0
TARGET=50_000.0
SYMBOL="GC=F"
LEVS=(100,125,150,175,200)
MAS=((6,18),(8,24),(12,36),(18,54))
STOPS=(0.0025,0.005,0.0075,0.01)
TAKES=(0.03,0.04,0.06,0.08)
SPREAD=5.0
FEE=1.0

def windows(bars,fast,slow,lev,stop,take):
    out=[]; cursor=bars[0].ts.replace(hour=0,minute=0,second=0,microsecond=0)
    end=bars[-1].ts
    while cursor+timedelta(days=7)<=end:
        stop_ts=cursor+timedelta(days=7)
        chunk=[b for b in bars if cursor<=b.ts<stop_ts]
        if len(chunk)>slow:
            out.append(run_window(chunk,start_yen=START,leverage=float(lev),
                spread_bps=SPREAD,fee_bps=FEE,fast=fast,slow=slow,
                stop_pct=stop,take_pct=take,target_yen=TARGET,ruin_yen=0.0))
        cursor+=timedelta(days=1)
    return out

def s(rows):
    if not rows:return {"windows":0}
    n=len(rows); finals=[r.final_yen for r in rows]; hits=sum(r.target_hit for r in rows)
    z=sum(v<=0 for v in finals)
    return {"windows":n,"target_hits":hits,"target_rate_pct":round(100*hits/n,4),
            "zero_finish_rate_pct":round(100*z/n,4),"median_final_yen":round(median(finals),2),
            "best_final_yen":round(max(finals),2),"worst_final_yen":round(min(finals),2)}

def split(rows):
    m=len(rows)//2
    return {"all":s(rows),"first_half":s(rows[:m]),"second_half":s(rows[m:])}

def key(r):
    q=r["summary"]; weak=min(q["first_half"]["target_rate_pct"],q["second_half"]["target_rate_pct"])
    return (weak,q["all"]["target_rate_pct"],-q["all"]["zero_finish_rate_pct"])

def main():
    bars=parse_chart(fetch_chart(SYMBOL)); rows=[]
    for lev,(fast,slow),st,tp in itertools.product(LEVS,MAS,STOPS,TAKES):
        rs=windows(bars,fast,slow,lev,st,tp)
        rows.append({"leverage_equivalent":lev,"fast":fast,"slow":slow,"stop_pct":st,
                     "take_pct":tp,"summary":split(rs)})
    rows.sort(key=key,reverse=True)
    print(json.dumps({"paper_only":True,"market":"GOLD","tested_cases":len(rows),
        "warning":"generic leveraged simulation; not evidence that 100-200x is executable or suitable",
        "top_20":rows[:20]},ensure_ascii=False,sort_keys=True))

if __name__=="__main__": main()
