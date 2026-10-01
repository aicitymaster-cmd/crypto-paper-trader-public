"""PAPER-only aggressive 7-day target-touch research.

Goal: maximize the observed probability that JPY 10,000 touches JPY 50,000
within seven days. Total loss is allowed. Research only; no orders, auth, or
broker-specific claim of executable leverage.
"""
from __future__ import annotations
import itertools, json
from statistics import median
from datetime import timedelta

from cross_market_backtest import run_window
from cross_market_public_run import MARKETS, fetch_chart, parse_chart

START_YEN=10_000.0
TARGET_YEN=50_000.0
LEVERAGES=(25,50,75,100)
MA_PAIRS=((6,18),(12,36))
STOPS=(0.005,0.01)
TAKES=(0.02,0.04,0.08)
SPREAD_BPS=5.0
FEE_BPS=1.0

def windows(bars, fast, slow, leverage, stop, take):
    out=[]
    cursor=bars[0].ts.replace(hour=0,minute=0,second=0,microsecond=0)
    end=bars[-1].ts
    while cursor+timedelta(days=7)<=end:
        stop_ts=cursor+timedelta(days=7)
        chunk=[b for b in bars if cursor<=b.ts<stop_ts]
        if len(chunk)>slow:
            r=run_window(
                chunk,start_yen=START_YEN,leverage=float(leverage),
                spread_bps=SPREAD_BPS,fee_bps=FEE_BPS,
                fast=fast,slow=slow,stop_pct=stop,take_pct=take,
                target_yen=TARGET_YEN,ruin_yen=0.0,
            )
            out.append(r)
        cursor+=timedelta(days=1)
    return out

def summarize(rows):
    if not rows:return {"windows":0}
    n=len(rows); finals=[r.final_yen for r in rows]
    hits=sum(r.target_hit for r in rows)
    zeros=sum(v<=0 for v in finals)
    return {
        "windows":n,
        "target_hits":hits,
        "target_rate_pct":round(100*hits/n,4),
        "zero_finishes":zeros,
        "zero_finish_rate_pct":round(100*zeros/n,4),
        "median_final_yen":round(median(finals),2),
        "best_final_yen":round(max(finals),2),
        "worst_final_yen":round(min(finals),2),
    }

def split(rows):
    mid=len(rows)//2
    return {"all":summarize(rows),"first_half":summarize(rows[:mid]),"second_half":summarize(rows[mid:])}

def rank_key(row):
    s=row["summary"]
    # prioritize repeatability: weaker half target rate first, then overall target rate
    weak=min(s["first_half"].get("target_rate_pct",0),s["second_half"].get("target_rate_pct",0))
    return (weak,s["all"].get("target_rate_pct",0),-s["all"].get("zero_finish_rate_pct",100))

def run_all():
    cases=[]; failures={}
    for name,symbol in MARKETS.items():
        try:
            bars=parse_chart(fetch_chart(symbol))
        except Exception as exc:
            failures[name]=f"{type(exc).__name__}:{exc}"; continue
        for lev,(fast,slow),st,tp in itertools.product(LEVERAGES,MA_PAIRS,STOPS,TAKES):
            rows=windows(bars,fast,slow,lev,st,tp)
            if rows:
                cases.append({
                    "market":name,"leverage_equivalent":lev,
                    "fast":fast,"slow":slow,"stop_pct":st,"take_pct":tp,
                    "summary":split(rows),
                })
    cases.sort(key=rank_key,reverse=True)
    return {
        "paper_only":True,
        "goal":"touch 50000 yen within 7 days from 10000 yen; zero loss allowed",
        "warning":"generic leveraged simulation, not proof of broker-executable leverage or future probability",
        "tested_cases":len(cases),
        "top_15":cases[:15],
        "failures":failures,
    }

if __name__=="__main__":
    print(json.dumps(run_all(),ensure_ascii=False,sort_keys=True))
