"""Funding-cost stress test for the corrected IG-style GOLD KO model.

Adds a configurable all-in overnight funding debit in points per lot per
rollover. IG publishes that spot-gold KO funding uses TomNext plus a 0.6%
annual add-on. The live TomNext component varies, so this test stresses a
range rather than pretending one fixed historical value.

Campaign stops immediately at JPY 50,000. Research only.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from statistics import median
from datetime import timedelta

from gold_filter_holdout import fetch, parse, candidates, FAST, SLOW
import ig_gold_ko_realistic as base

START_JPY=10_000.0
TARGET_JPY=50_000.0
USDJPY=158.2
KO_PCT=0.0075
LOT_STEP=0.04
FUNDING_POINTS_PER_LOT_PER_DAY=(0.0,0.10,0.25,0.50,1.00)

@dataclass(frozen=True)
class R:
    final_jpy: float
    target_hit: bool
    knocked_out: bool
    funding_jpy: float
    trades: int

def sma(v,n): return sum(v[-n:])/n

def rollovers_between(a,b):
    # Approximate one daily funding event per crossed UTC date boundary.
    # Stress test purpose only; IG's actual cutover is Japan 06:00 in US DST.
    return max(0,(b.date()-a.date()).days)

def run_window_funding(bars, funding_points):
    equity=START_JPY; funding_paid=0.0; trades=0; ever_ko=False
    i=SLOW
    while i < len(bars)-1 and equity>0:
        closes=[b.close for b in bars[:i+1]]
        signal=1 if sma(closes,FAST)>sma(closes,SLOW) else -1
        entry_bar=bars[i]; entry=entry_bar.close
        ko_distance=entry*KO_PCT
        option_points=ko_distance+base.KO_PREMIUM_POINTS+base.SPREAD_POINTS/2
        lots=base.floor_step((equity/USDJPY)/option_points,LOT_STEP)
        if lots<LOT_STEP-1e-12: break

        j=i+1; exited=False
        while j<len(bars):
            b=bars[j]
            _,high,low,close=b.ohlc()
            adverse=(entry-low) if signal==1 else (high-entry)
            favorable=(high-entry) if signal==1 else (entry-low)

            r=rollovers_between(entry_bar.ts,b.ts)
            accrued=funding_points*lots*r*USDJPY

            if adverse>=ko_distance:
                equity=max(0.0,equity-accrued)
                funding_paid+=accrued
                equity=0.0; trades+=1; ever_ko=True
                exited=True; i=j+1; break

            favorable_pnl=favorable*lots*USDJPY
            if equity+favorable_pnl-accrued>=TARGET_JPY:
                funding_paid+=accrued
                return R(TARGET_JPY,True,ever_ko,round(funding_paid,2),trades+1)

            closes2=[x.close for x in bars[:j+1]]
            sig2=1 if sma(closes2,FAST)>sma(closes2,SLOW) else -1
            if sig2!=signal:
                move=(close-entry) if signal==1 else (entry-close)
                pnl=move*lots*USDJPY-accrued
                funding_paid+=accrued
                equity=max(0.0,equity+pnl)
                trades+=1; exited=True; i=j+1; break
            j+=1

        if not exited:
            b=bars[-1]
            accrued=funding_points*lots*rollovers_between(entry_bar.ts,b.ts)*USDJPY
            move=(b.close-entry) if signal==1 else (entry-b.close)
            equity=max(0.0,equity+move*lots*USDJPY-accrued)
            funding_paid+=accrued; trades+=1; i=len(bars)

    return R(round(equity,2),equity>=TARGET_JPY,ever_ko,round(funding_paid,2),trades)

def summ(rows):
    n=len(rows); finals=[r.final_jpy for r in rows]
    return {
      "windows":n,
      "target_hits":sum(r.target_hit for r in rows),
      "target_rate_pct":round(100*sum(r.target_hit for r in rows)/n,4) if n else 0,
      "knockout_rate_pct":round(100*sum(r.knocked_out for r in rows)/n,4) if n else 0,
      "median_final_jpy":round(median(finals),2) if n else 0,
      "median_funding_jpy":round(median([r.funding_jpy for r in rows]),2) if n else 0,
      "max_funding_jpy":round(max([r.funding_jpy for r in rows]),2) if n else 0,
    }

def main():
    bars=parse(fetch()); c=candidates(bars)
    midpoint=bars[0].ts+(bars[-1].ts-bars[0].ts)/2
    out=[]
    for fp in FUNDING_POINTS_PER_LOT_PER_DAY:
        allr=[run_window_funding(chunk,fp) for _,chunk in c]
        first=[run_window_funding(chunk,fp) for ts,chunk in c if ts<midpoint]
        second=[run_window_funding(chunk,fp) for ts,chunk in c if ts>=midpoint]
        out.append({"funding_points_per_lot_per_day":fp,
                    "all":summ(allr),"first_half":summ(first),
                    "second_half_holdout":summ(second)})
    print(json.dumps({
      "paper_only":True,
      "ko_distance_pct":KO_PCT,
      "lot_step":LOT_STEP,
      "official_addon_reference":"0.6% annual add-on plus variable TomNext; stressed here as all-in daily points",
      "cases":out,
      "warning":"funding stress approximation, not reconstructed historical IG swap quotes",
    },ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
