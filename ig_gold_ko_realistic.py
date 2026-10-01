"""IG-style GOLD knock-out feasibility simulation using product mechanics.

Models a JPY 10,000 budget converted at a fixed USDJPY reference rate.
Position size is chosen so the full opening KO price fits the budget:
  option_price_points = KO distance points + KO premium
  cost_usd = option_price_points * lots
The trade is knocked out if the underlying moves adversely by the KO distance.
The campaign stops immediately when total wealth reaches JPY 50,000.

Research only. This approximates IG product mechanics using public OHLC and
published point value/premium; it is not an order, quote, or broker guarantee.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from statistics import median

from gold_filter_holdout import fetch, parse, candidates, FAST, SLOW

START_JPY=10_000.0
TARGET_JPY=50_000.0
USDJPY=158.2
KO_PREMIUM_POINTS=0.5
POINT_VALUE_USD_PER_LOT=1.0
SPREAD_POINTS=0.6
KO_DIST_PCTS=(0.005,0.0075,0.01,0.0125,0.015)
LOT_STEPS=(0.04,0.1)
TAKE_MOVE_PCT=0.08

@dataclass(frozen=True)
class R:
    final_jpy: float
    target_hit: bool
    knocked_out: bool
    lots: float
    ko_distance_points: float
    trades: int

def sma(v,n): return sum(v[-n:])/n

def floor_step(x,step):
    return int(x/step+1e-12)*step

def run_window_realistic(bars, ko_pct, lot_step):
    equity_jpy=START_JPY
    trades=0
    ever_ko=False
    i=SLOW
    last_lots=0.0
    last_ko=0.0

    while i < len(bars)-1 and equity_jpy>0:
        closes=[b.close for b in bars[:i+1]]
        bar=bars[i]
        signal=1 if sma(closes,FAST)>sma(closes,SLOW) else -1
        price=bar.close
        ko_distance=price*ko_pct
        option_points=ko_distance+KO_PREMIUM_POINTS+SPREAD_POINTS/2
        budget_usd=equity_jpy/USDJPY
        lots=floor_step(budget_usd/option_points,lot_step)
        last_lots=lots; last_ko=ko_distance
        if lots<lot_step-1e-12:
            break

        entry=price
        exited=False
        j=i+1
        while j < len(bars):
            b=bars[j]
            _,high,low,close=b.ohlc()
            adverse=(entry-low) if signal==1 else (high-entry)
            favorable=(high-entry) if signal==1 else (entry-low)

            # Conservative same-bar ordering: if both KO and target are
            # possible inside one OHLC bar, count the KO first because the
            # intrabar path is unknown.
            if adverse>=ko_distance:
                equity_jpy=0.0
                trades+=1
                ever_ko=True
                exited=True
                i=j+1
                break

            favorable_pnl_usd=favorable*lots*POINT_VALUE_USD_PER_LOT
            if equity_jpy+favorable_pnl_usd*USDJPY>=TARGET_JPY:
                trades+=1
                return R(TARGET_JPY,True,ever_ko,lots,round(ko_distance,2),trades)

            closes2=[x.close for x in bars[:j+1]]
            sig2=1 if sma(closes2,FAST)>sma(closes2,SLOW) else -1
            if sig2!=signal:
                move=(close-entry) if signal==1 else (entry-close)
                pnl_jpy=move*lots*POINT_VALUE_USD_PER_LOT*USDJPY
                equity_jpy=max(0.0,equity_jpy+pnl_jpy)
                trades+=1
                exited=True
                i=j+1
                break
            j+=1

        if not exited:
            b=bars[-1]
            move=(b.close-entry) if signal==1 else (entry-b.close)
            equity_jpy=max(0.0,equity_jpy+move*lots*USDJPY)
            trades+=1
            i=len(bars)

    return R(round(equity_jpy,2),equity_jpy>=TARGET_JPY,ever_ko,last_lots,round(last_ko,2),trades)

def summ(rows):
    n=len(rows); finals=[r.final_jpy for r in rows]
    hits=sum(r.target_hit for r in rows); kos=sum(r.knocked_out for r in rows)
    return {
        "windows":n,
        "target_hits":hits,
        "target_rate_pct":round(100*hits/n,4) if n else 0,
        "knockout_rate_pct":round(100*kos/n,4) if n else 0,
        "median_final_jpy":round(median(finals),2) if n else 0,
        "best_final_jpy":round(max(finals),2) if n else 0,
        "worst_final_jpy":round(min(finals),2) if n else 0,
    }

def main():
    bars=parse(fetch()); c=candidates(bars)
    midpoint=bars[0].ts+(bars[-1].ts-bars[0].ts)/2
    out=[]
    for ko in KO_DIST_PCTS:
        for step in LOT_STEPS:
            allr=[run_window_realistic(chunk,ko,step) for _,chunk in c]
            first=[run_window_realistic(chunk,ko,step) for ts,chunk in c if ts<midpoint]
            second=[run_window_realistic(chunk,ko,step) for ts,chunk in c if ts>=midpoint]
            out.append({
                "ko_distance_pct":ko,
                "lot_step":step,
                "all":summ(allr),
                "first_half":summ(first),
                "second_half_holdout":summ(second),
            })
    out.sort(key=lambda x:(min(x["first_half"]["target_rate_pct"],x["second_half_holdout"]["target_rate_pct"]),
                           x["all"]["target_rate_pct"],-x["all"]["knockout_rate_pct"]),reverse=True)
    print(json.dumps({
        "paper_only":True,
        "assumptions":{
            "start_jpy":START_JPY,"target_jpy":TARGET_JPY,"usdjpy":USDJPY,
            "ko_premium_points":KO_PREMIUM_POINTS,"spread_points":SPREAD_POINTS,
            "point_value_usd_per_lot":POINT_VALUE_USD_PER_LOT,
        },
        "cases":out,
        "warning":"approximation of published KO mechanics; excludes variable funding, changing FX conversion and live quote effects",
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__": main()
