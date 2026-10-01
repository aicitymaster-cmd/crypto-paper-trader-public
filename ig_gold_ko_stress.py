"""Stress test the corrected IG-style GOLD KO model."""
from __future__ import annotations
import json
import ig_gold_ko_realistic as m
from gold_filter_holdout import fetch, parse, candidates

PREMIUMS=(0.5,1.0,1.5)
SPREADS=(0.6,1.2,2.0)
KO_PCT=0.005
LOT_STEPS=(0.04,0.1)

def main():
    bars=parse(fetch()); c=candidates(bars)
    midpoint=bars[0].ts+(bars[-1].ts-bars[0].ts)/2
    out=[]
    original_premium=m.KO_PREMIUM_POINTS
    original_spread=m.SPREAD_POINTS
    try:
        for prem in PREMIUMS:
            for spr in SPREADS:
                for step in LOT_STEPS:
                    m.KO_PREMIUM_POINTS=prem
                    m.SPREAD_POINTS=spr
                    allr=[m.run_window_realistic(chunk,KO_PCT,step) for _,chunk in c]
                    first=[m.run_window_realistic(chunk,KO_PCT,step) for ts,chunk in c if ts<midpoint]
                    second=[m.run_window_realistic(chunk,KO_PCT,step) for ts,chunk in c if ts>=midpoint]
                    out.append({"premium_points":prem,"spread_points":spr,"lot_step":step,
                                "all":m.summ(allr),"first_half":m.summ(first),
                                "second_half_holdout":m.summ(second)})
    finally:
        m.KO_PREMIUM_POINTS=original_premium
        m.SPREAD_POINTS=original_spread
    out.sort(key=lambda x:(min(x["first_half"]["target_rate_pct"],x["second_half_holdout"]["target_rate_pct"]),
                           x["all"]["target_rate_pct"],-x["all"]["knockout_rate_pct"]),reverse=True)
    print(json.dumps({"paper_only":True,"ko_distance_pct":KO_PCT,"cases":out,
                      "warning":"cost sensitivity only; excludes variable overnight funding and live quote effects"},
                     ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
