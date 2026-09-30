"""Adaptive 3-market KO portfolio screening.

Research only. Uses public OHLC and zero spread/funding/KO premium.
Capital is fully deployable. Each 7-day window is split into daily sleeves.
After each day, the next day's largest weight is assigned to the market with
the strongest prior-day return. If total equity falls to/below a guard level,
trading stops and remaining equity is preserved.
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

INITIAL_ALLOCS=(
    {"GBPJPY":0.50,"GOLD":0.25,"NASDAQ100":0.25},
    {"GBPJPY":0.25,"GOLD":0.50,"NASDAQ100":0.25},
    {"GBPJPY":0.25,"GOLD":0.25,"NASDAQ100":0.50},
)
SETTINGS={
    "GBPJPY":((0.01,0.25),(0.005,0.25),(0.01,0.50)),
    "GOLD":((0.01,0.25),(0.005,0.50),(0.005,1.00)),
    "NASDAQ100":((0.01,0.25),(0.005,0.50),(0.0025,0.50)),
}
WINNER_WEIGHTS=(0.50,0.60,0.70)
GUARDS=(5000.0,5500.0,6000.0)

def aligned_windows(bars):
    start=max(v[0].ts.replace(hour=0,minute=0,second=0,microsecond=0) for v in bars.values())
    end=min(v[-1].ts for v in bars.values())
    cur=start
    out=[]
    while cur+timedelta(days=7)<=end:
        days=[]
        ok=True
        for day in range(7):
            a=cur+timedelta(days=day)
            b=a+timedelta(days=1)
            chunks={m:[x for x in bs if a<=x.ts<b] for m,bs in bars.items()}
            # Daily slices need enough bars for SMA36.
            if not all(len(v)>36 for v in chunks.values()):
                ok=False
                break
            days.append(chunks)
        if ok:
            out.append((cur,days))
        cur+=timedelta(days=1)
    return out

def daily_multiplier(chunk, setting):
    d,r=setting
    return run_sleeve(chunk,1.0,d,r)

def run_window(days, initial_alloc, settings, winner_weight, guard):
    equity=START
    alloc=dict(initial_alloc)
    stopped=False
    for day_chunks in days:
        if equity<=guard:
            stopped=True
            break
        results={}
        total=0.0
        for m in MARKETS:
            mult=daily_multiplier(day_chunks[m],settings[m])
            results[m]=mult
            total+=equity*alloc[m]*mult
        equity=max(0.0,total)
        if equity>=TARGET:
            return TARGET,True,False
        if equity<=guard:
            stopped=True
            break
        winner=max(results,key=results.get)
        rest=(1.0-winner_weight)/2.0
        alloc={m:(winner_weight if m==winner else rest) for m in MARKETS}
    return equity,equity>=TARGET,equity<FLOOR

def summarize(finals, hits, below):
    s=sorted(finals); n=len(s)
    med=s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2
    return {
        "windows":n,
        "target_hits":sum(hits),
        "target_rate_pct":round(100*sum(hits)/n,4),
        "below_5000":sum(below),
        "below_5000_rate_pct":round(100*sum(below)/n,4),
        "at_least_10000_rate_pct":round(100*sum(x>=START for x in finals)/n,4),
        "median_final_yen":round(med,2),
        "best_final_yen":round(max(s),2),
        "worst_final_yen":round(min(s),2),
    }

def main():
    bars={m:parse_chart(fetch_chart(sym)) for m,sym in MARKETS.items()}
    windows=aligned_windows(bars)

    # Precompute daily multipliers for every market/setting/window/day.
    cache={m:{s:[] for s in SETTINGS[m]} for m in MARKETS}
    for m in MARKETS:
        for s in SETTINGS[m]:
            for _,days in windows:
                cache[m][s].append([daily_multiplier(d[m],s) for d in days])

    rows=[]
    for initial in INITIAL_ALLOCS:
      for gs in SETTINGS["GBPJPY"]:
       for xs in SETTINGS["GOLD"]:
        for ns in SETTINGS["NASDAQ100"]:
         settings={"GBPJPY":gs,"GOLD":xs,"NASDAQ100":ns}
         for ww in WINNER_WEIGHTS:
          for guard in GUARDS:
            finals=[]; hits=[]; below=[]
            for wi,(_,days) in enumerate(windows):
                equity=START
                alloc=dict(initial)
                hit=False
                for di in range(7):
                    if equity<=guard:
                        break
                    mults={
                        "GBPJPY":cache["GBPJPY"][gs][wi][di],
                        "GOLD":cache["GOLD"][xs][wi][di],
                        "NASDAQ100":cache["NASDAQ100"][ns][wi][di],
                    }
                    equity=sum(equity*alloc[m]*mults[m] for m in MARKETS)
                    if equity>=TARGET:
                        equity=TARGET; hit=True; break
                    if equity<=guard:
                        break
                    winner=max(mults,key=mults.get)
                    rest=(1.0-ww)/2.0
                    alloc={m:(ww if m==winner else rest) for m in MARKETS}
                finals.append(equity); hits.append(hit); below.append(equity<FLOOR)
            row={
                "initial_allocation":initial,
                "settings":{m:{"distance":settings[m][0],"risk":settings[m][1]} for m in MARKETS},
                "winner_weight":ww,
                "guard_yen":guard,
            }
            row.update(summarize(finals,hits,below))
            rows.append(row)

    rows.sort(key=lambda x:(-x["target_rate_pct"],x["below_5000_rate_pct"],-x["at_least_10000_rate_pct"],-x["median_final_yen"]))
    constrained={}
    for lim in (0,5,10,15,20,25,30):
        eligible=[x for x in rows if x["below_5000_rate_pct"]<=lim]
        constrained[str(lim)]=eligible[:5]
    return {
        "paper_only":True,
        "model":"adaptive 3-market daily winner-tilt KO screening",
        "assumptions":{"start_yen":START,"target_yen":TARGET,"floor_yen":FLOOR,
                       "spread":0,"funding":0,"ko_premium":0},
        "aligned_windows":len(windows),
        "configs_tested":len(rows),
        "best_target":rows[:10],
        "best_by_floor_failure_limit_pct":constrained,
    }

if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
