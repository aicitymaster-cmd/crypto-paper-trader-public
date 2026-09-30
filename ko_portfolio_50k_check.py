"""Three-market KO portfolio research: GBPJPY + GOLD + NASDAQ100.

Research-only optimistic upper bound. Uses zero spread/funding/KO premium so
this is a screening test, not a live-trading forecast. Starts with 10,000 JPY
fully allocated across three independent sleeves and evaluates total equity
after each aligned 7-day window.
"""
from __future__ import annotations
import json
from datetime import timedelta

from cross_market_public_run import fetch_chart, parse_chart
from ko_upper_bound_run import sma

START=10_000.0
TARGET=50_000.0
FLOOR=5_000.0
FAST=12
SLOW=36
MARKETS={"GBPJPY":"GBPJPY=X","GOLD":"GC=F","NASDAQ100":"NQ=F"}
DISTANCES=(0.0025,0.005,0.01)
RISKS=(0.25,0.5,1.0)
# All capital is used; minimum 25% per sleeve.
ALLOCATIONS=((0.5,0.25,0.25),(0.25,0.5,0.25),(0.25,0.25,0.5))

def run_sleeve(bars,start,distance,risk_fraction):
    equity=start
    pos=0; entry=0.0; entry_equity=equity; risk_budget=0.0
    for i in range(SLOW,len(bars)):
        closes=[b.close for b in bars[:i+1]]
        bar=bars[i]
        signal=1 if sma(closes,FAST)>sma(closes,SLOW) else -1
        if pos:
            _,high,low,close=bar.ohlc()
            adverse=(low/entry-1.0) if pos==1 else (entry/high-1.0)
            close_move=pos*(close/entry-1.0)
            if adverse<=-distance:
                equity=max(0.0,entry_equity-risk_budget); pos=0
            elif signal!=pos:
                pnl=max(-risk_budget,risk_budget*close_move/distance)
                equity=max(0.0,entry_equity+pnl); pos=0
        if not pos and equity>0:
            pos=signal; entry=bar.close; entry_equity=equity; risk_budget=equity*risk_fraction
    if pos and equity>0:
        close_move=pos*(bars[-1].close/entry-1.0)
        pnl=max(-risk_budget,risk_budget*close_move/distance)
        equity=max(0.0,entry_equity+pnl)
    return equity

def chunks(bars_by_market):
    starts=[]
    latest_start=max(v[0].ts.replace(hour=0,minute=0,second=0,microsecond=0) for v in bars_by_market.values())
    earliest_end=min(v[-1].ts for v in bars_by_market.values())
    cur=latest_start
    while cur+timedelta(days=7)<=earliest_end:
        stop=cur+timedelta(days=7)
        ch={m:[b for b in bars if cur<=b.ts<stop] for m,bars in bars_by_market.items()}
        if all(len(x)>SLOW for x in ch.values()):
            starts.append((cur,ch))
        cur+=timedelta(days=1)
    return starts

def main():
    bars={m:parse_chart(fetch_chart(sym)) for m,sym in MARKETS.items()}
    win=chunks(bars)

    # Precompute every market/setting/window once, then combine cached finals.
    cached={m:{} for m in MARKETS}
    for m in MARKETS:
        for d in DISTANCES:
            for r in RISKS:
                key=(d,r)
                cached[m][key]=[
                    run_sleeve(ch[m],START,d,r)/START
                    for _,ch in win
                ]

    configs=[]
    for alloc in ALLOCATIONS:
      for dg in DISTANCES:
       for rg in RISKS:
        for dx in DISTANCES:
         for rx in RISKS:
          for dn in DISTANCES:
           for rn in RISKS:
            finals=[]
            for i in range(len(win)):
                total=START*(
                    alloc[0]*cached["GBPJPY"][(dg,rg)][i]
                    +alloc[1]*cached["GOLD"][(dx,rx)][i]
                    +alloc[2]*cached["NASDAQ100"][(dn,rn)][i]
                )
                finals.append(total)
            s=sorted(finals); n=len(s)
            med=s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2
            configs.append({
              "allocation":{"GBPJPY":alloc[0],"GOLD":alloc[1],"NASDAQ100":alloc[2]},
              "settings":{
                "GBPJPY":{"distance":dg,"risk":rg},
                "GOLD":{"distance":dx,"risk":rx},
                "NASDAQ100":{"distance":dn,"risk":rn},
              },
              "windows":n,
              "target_hits":sum(x>=TARGET for x in finals),
              "target_rate_pct":round(100*sum(x>=TARGET for x in finals)/n,4),
              "below_5000":sum(x<FLOOR for x in finals),
              "below_5000_rate_pct":round(100*sum(x<FLOOR for x in finals)/n,4),
              "at_least_10000_rate_pct":round(100*sum(x>=START for x in finals)/n,4),
              "median_final_yen":round(med,2),
              "best_final_yen":round(max(finals),2),
              "worst_final_yen":round(min(finals),2),
            })
    configs.sort(key=lambda x:(-x["target_rate_pct"],x["below_5000_rate_pct"],-x["median_final_yen"]))
    best_target=configs[:20]
    safe=sorted(configs,key=lambda x:(x["below_5000_rate_pct"],-x["target_rate_pct"],-x["median_final_yen"]))[:20]
    balanced=sorted(configs,key=lambda x:(-(x["target_rate_pct"]-x["below_5000_rate_pct"]),-x["target_rate_pct"],-x["median_final_yen"]))[:20]
    constrained={}
    for limit in (0,5,10,15,20,25,30):
        eligible=[x for x in configs if x["below_5000_rate_pct"]<=limit]
        constrained[str(limit)]=sorted(
            eligible,
            key=lambda x:(-x["target_rate_pct"],-x["at_least_10000_rate_pct"],-x["median_final_yen"])
        )[:5]
    return {
      "paper_only":True,
      "model":"3-market KO portfolio optimistic screening",
      "assumptions":{"start_yen":START,"target_yen":TARGET,"floor_yen":FLOOR,
                     "spread":0,"funding":0,"ko_premium":0,"full_capital_allocated":True},
      "aligned_windows":len(win),
      "configs_tested":len(configs),
      "best_target":best_target,
      "safest":safe,
      "balanced":balanced,
      "best_by_floor_failure_limit_pct":constrained,
    }

if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
