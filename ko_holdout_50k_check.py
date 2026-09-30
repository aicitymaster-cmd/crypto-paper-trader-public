"""Holdout validation for the selected profit-lock adaptive portfolio.

The strategy is frozen before this check:
- Initial allocation: GBPJPY 50%, GOLD 25%, NASDAQ100 25%
- GBPJPY: distance 1.0%, risk 25%
- GOLD: distance 0.5%, risk 100%
- NASDAQ100: distance 0.25%, risk 50%
- Daily winner tilt: 70%
- Profit lock: once total >= 15,000 JPY, reserve 5,000 JPY
- Start 10,000 / target 50,000 / floor 5,000

Research only. Zero spread/funding/KO premium remains optimistic.
"""
from __future__ import annotations
import json
from datetime import timedelta

from cross_market_public_run import fetch_chart, parse_chart
from ko_portfolio_50k_check import run_sleeve

START=10_000.0
TARGET=50_000.0
FLOOR=5_000.0
MARKETS={"GBPJPY":"GBPJPY=X","GOLD":"GC=F","NASDAQ100":"NQ=F"}
INITIAL={"GBPJPY":0.50,"GOLD":0.25,"NASDAQ100":0.25}
SETTINGS={"GBPJPY":(0.01,0.25),"GOLD":(0.005,1.00),"NASDAQ100":(0.0025,0.50)}
WINNER_WEIGHT=0.70

def seven_day_windows(bars, step_days=1):
    start=max(v[0].ts.replace(hour=0,minute=0,second=0,microsecond=0) for v in bars.values())
    end=min(v[-1].ts for v in bars.values())
    out=[]; cur=start
    while cur+timedelta(days=7)<=end:
        days=[]
        for day in range(7):
            a=cur+timedelta(days=day); b=a+timedelta(days=1)
            chunks={m:[x for x in bs if a<=x.ts<b] for m,bs in bars.items()}
            if all(len(v)>36 for v in chunks.values()):
                days.append(chunks)
        if len(days)>=4:
            out.append((cur,days))
        cur+=timedelta(days=step_days)
    return out

def run(days):
    reserve=0.0; active=START; alloc=dict(INITIAL)
    for d in days:
        mults={m:run_sleeve(d[m],1.0,*SETTINGS[m]) for m in MARKETS}
        active=sum(active*alloc[m]*mults[m] for m in MARKETS)
        total=reserve+active
        if total>=TARGET:
            return TARGET
        if total>=15_000.0 and reserve<5_000.0:
            reserve=5_000.0
            active=max(0.0,total-reserve)
        if active<=0:
            break
        winner=max(mults,key=mults.get)
        rest=(1.0-WINNER_WEIGHT)/2.0
        alloc={m:(WINNER_WEIGHT if m==winner else rest) for m in MARKETS}
    return reserve+active

def summary(rows):
    finals=[x["final_yen"] for x in rows]
    s=sorted(finals); n=len(s)
    if not n:
        return {"windows":0}
    med=s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2
    return {
        "windows":n,
        "target_hits":sum(x>=TARGET for x in finals),
        "target_rate_pct":round(100*sum(x>=TARGET for x in finals)/n,4),
        "below_5000":sum(x<FLOOR for x in finals),
        "below_5000_rate_pct":round(100*sum(x<FLOOR for x in finals)/n,4),
        "at_least_10000_rate_pct":round(100*sum(x>=START for x in finals)/n,4),
        "median_final_yen":round(med,2),
        "best_final_yen":round(max(s),2),
        "worst_final_yen":round(min(s),2),
    }

def main():
    bars={m:parse_chart(fetch_chart(sym)) for m,sym in MARKETS.items()}

    rolling=[]
    for start,days in seven_day_windows(bars,1):
        rolling.append({"start":start.isoformat(),"final_yen":round(run(days),2)})

    split=max(1,int(len(rolling)*2/3))
    train=rolling[:split]
    holdout=rolling[split:]

    nonoverlap=[]
    for start,days in seven_day_windows(bars,7):
        nonoverlap.append({"start":start.isoformat(),"final_yen":round(run(days),2)})

    return {
        "paper_only":True,
        "model":"frozen selected adaptive profit-lock holdout validation",
        "assumptions":{"spread":0,"funding":0,"ko_premium":0},
        "frozen_strategy":{
            "initial_allocation":INITIAL,
            "settings":{m:{"distance":SETTINGS[m][0],"risk":SETTINGS[m][1]} for m in MARKETS},
            "winner_weight":WINNER_WEIGHT,
            "profit_lock":{"threshold_yen":15000,"reserve_yen":5000},
            "start_yen":START,"target_yen":TARGET,"floor_yen":FLOOR,
        },
        "chronological_train_first_two_thirds":summary(train),
        "chronological_holdout_last_third":summary(holdout),
        "non_overlapping_7day_windows":summary(nonoverlap),
        "holdout_window_starts":[x["start"] for x in holdout],
        "nonoverlap_window_starts":[x["start"] for x in nonoverlap],
    }

if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
