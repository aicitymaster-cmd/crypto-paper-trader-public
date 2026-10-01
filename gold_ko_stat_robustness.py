"""Statistical robustness check for the frozen realistic GOLD KO candidate.

Uses the corrected IG-style model at KO distance 0.75%, lot step 0.04 and
stress funding 0.25 points/day. Reports Wilson interval, leave-one-quarter-out
rates, and deterministic bootstrap distribution. PAPER only.
"""
from __future__ import annotations
import json, math, random
from statistics import median
from gold_filter_holdout import fetch, parse, candidates
from ig_gold_ko_funding_stress import run_window_funding

KO_PCT=0.0075
FUNDING=0.25
BOOTSTRAPS=10000
SEED=20261001

def wilson(hits,n,z=1.959963984540054):
    if n==0: return [0.0,0.0]
    p=hits/n
    den=1+z*z/n
    center=(p+z*z/(2*n))/den
    half=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/den
    return [round(100*max(0,center-half),2),round(100*min(1,center+half),2)]

def main():
    bars=parse(fetch()); c=candidates(bars)
    outcomes=[]
    for ts,chunk in c:
        r=run_window_funding(chunk,FUNDING)
        outcomes.append((ts,bool(r.target_hit)))
    hits=sum(v for _,v in outcomes); n=len(outcomes)

    # chronological quarters
    qs=[]
    for q in range(4):
        a=q*n//4; b=(q+1)*n//4
        part=outcomes[a:b]
        h=sum(v for _,v in part)
        qs.append({"quarter":q+1,"windows":len(part),"hits":h,
                   "rate_pct":round(100*h/len(part),2) if part else 0})

    # leave-one-quarter-out
    loo=[]
    for q in range(4):
        kept=[v for i,(_,v) in enumerate(outcomes) if not (q*n//4 <= i < (q+1)*n//4)]
        h=sum(kept)
        loo.append({"left_out_quarter":q+1,"windows":len(kept),"hits":h,
                    "rate_pct":round(100*h/len(kept),2) if kept else 0})

    rng=random.Random(SEED)
    rates=[]
    vals=[int(v) for _,v in outcomes]
    for _ in range(BOOTSTRAPS):
        sample=[vals[rng.randrange(n)] for _ in range(n)]
        rates.append(100*sum(sample)/n)
    rates.sort()
    lo=rates[int(0.025*BOOTSTRAPS)]
    hi=rates[int(0.975*BOOTSTRAPS)-1]

    print(json.dumps({
        "paper_only":True,
        "candidate":{"ko_distance_pct":KO_PCT,"funding_points_per_lot_per_day":FUNDING},
        "observed":{"windows":n,"hits":hits,"rate_pct":round(100*hits/n,4),
                    "wilson_95_pct":wilson(hits,n)},
        "chronological_quarters":qs,
        "leave_one_quarter_out":loo,
        "bootstrap":{"samples":BOOTSTRAPS,"seed":SEED,
                     "median_rate_pct":round(median(rates),2),
                     "p2_5_rate_pct":round(lo,2),"p97_5_rate_pct":round(hi,2)},
        "warning":"statistical uncertainty from only the observed historical windows; not a future success probability"
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__": main()
