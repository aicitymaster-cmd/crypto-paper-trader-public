"""Profit-lock portfolio screening for the 50k / 5k objective.

Research only. Starts with the full 10,000 JPY at risk. Once total equity
crosses specified thresholds, part of the account is moved to a protected
reserve. The reserve remains part of total equity but is no longer traded.
Uses public OHLC with zero spread/funding/KO premium, so results are optimistic.
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

BASES={
  "fixed_balanced":{
    "initial":{"GBPJPY":0.50,"GOLD":0.25,"NASDAQ100":0.25},
    "settings":{"GBPJPY":(0.01,0.50),"GOLD":(0.0025,0.50),"NASDAQ100":(0.0025,0.25)},
    "winner_weight":None,
  },
  "adaptive_attack":{
    "initial":{"GBPJPY":0.50,"GOLD":0.25,"NASDAQ100":0.25},
    "settings":{"GBPJPY":(0.01,0.25),"GOLD":(0.005,1.00),"NASDAQ100":(0.0025,0.50)},
    "winner_weight":0.70,
  },
}
LOCK_SCHEMES={
  "none":(),
  "early5":((15_000.0,5_000.0),),
  "mid5":((20_000.0,5_000.0),),
  "late5":((25_000.0,5_000.0),),
  "staged_15_25":((15_000.0,5_000.0),(25_000.0,10_000.0)),
  "staged_20_30":((20_000.0,5_000.0),(30_000.0,10_000.0)),
}

def aligned_windows(bars):
    start=max(v[0].ts.replace(hour=0,minute=0,second=0,microsecond=0) for v in bars.values())
    end=min(v[-1].ts for v in bars.values())
    cur=start; out=[]
    while cur+timedelta(days=7)<=end:
        days=[]
        for day in range(7):
            a=cur+timedelta(days=day); b=a+timedelta(days=1)
            chunks={m:[x for x in bs if a<=x.ts<b] for m,bs in bars.items()}
            if all(len(v)>36 for v in chunks.values()):
                days.append(chunks)
        if len(days)>=4:
            out.append((cur,days))
        cur+=timedelta(days=1)
    return out

def apply_locks(total,reserve,scheme):
    for threshold,target_reserve in scheme:
        if total>=threshold and reserve<target_reserve:
            reserve=min(target_reserve,total)
    return reserve

def summarize(finals):
    s=sorted(finals); n=len(s)
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
    windows=aligned_windows(bars)
    rows=[]
    for base_name,base in BASES.items():
        # Precompute per-day multipliers for this base.
        cache=[]
        for _,days in windows:
            per=[]
            for d in days:
                per.append({m:run_sleeve(d[m],1.0,*base["settings"][m]) for m in MARKETS})
            cache.append(per)
        for lock_name,scheme in LOCK_SCHEMES.items():
            finals=[]
            for wi,(_,days) in enumerate(windows):
                reserve=0.0
                active=START
                alloc=dict(base["initial"])
                for di in range(len(days)):
                    if active<=0:
                        break
                    mults=cache[wi][di]
                    active=sum(active*alloc[m]*mults[m] for m in MARKETS)
                    total=reserve+active
                    if total>=TARGET:
                        total=TARGET; reserve=total; active=0.0; break
                    new_reserve=apply_locks(total,reserve,scheme)
                    if new_reserve>reserve:
                        active=max(0.0,total-new_reserve)
                        reserve=new_reserve
                    if base["winner_weight"] is not None and active>0:
                        winner=max(mults,key=mults.get)
                        ww=base["winner_weight"]; rest=(1.0-ww)/2.0
                        alloc={m:(ww if m==winner else rest) for m in MARKETS}
                finals.append(reserve+active)
            row={"base":base_name,"lock_scheme":lock_name,
                 "settings":{m:{"distance":base["settings"][m][0],"risk":base["settings"][m][1]} for m in MARKETS},
                 "initial_allocation":base["initial"],"winner_weight":base["winner_weight"]}
            row.update(summarize(finals))
            rows.append(row)
    rows.sort(key=lambda x:(-x["target_rate_pct"],x["below_5000_rate_pct"],-x["at_least_10000_rate_pct"],-x["median_final_yen"]))
    return {"paper_only":True,"model":"profit-lock multi-market KO screening",
            "assumptions":{"start_yen":START,"target_yen":TARGET,"floor_yen":FLOOR,
                           "spread":0,"funding":0,"ko_premium":0},
            "aligned_windows":len(windows),"rows":rows}

if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
