"""GBP/JPY KO 50k cost sensitivity check.

Research only. Uses the previously selected KO distance 0.5% and 50% account
risk. Applies IG's published GBP/JPY KO premium of 8 points (0.08 JPY) and
tests 1/2/3 pip spread scenarios. Funding remains zero, so results are still
optimistic for positions held overnight.
"""
from __future__ import annotations
import json
from datetime import timedelta

from cross_market_public_run import fetch_chart, parse_chart
from ko_upper_bound_run import sma

START_YEN = 10_000.0
TARGET_YEN = 50_000.0
FLOOR_YEN = 5_000.0
DISTANCE = 0.005
RISK_FRACTION = 0.50
KO_PREMIUM_JPY = 0.08
SPREAD_PIPS = (1.0, 2.0, 3.0)
PIP_JPY = 0.01
FAST = 12
SLOW = 36

def run_window(bars, spread_pips):
    equity=START_YEN; peak=equity; max_dd=0.0
    pos=0; entry=0.0; entry_equity=equity; risk_budget=0.0; units_scale=1.0
    target=False
    for i in range(SLOW,len(bars)):
        closes=[b.close for b in bars[:i+1]]
        bar=bars[i]
        signal=1 if sma(closes,FAST)>sma(closes,SLOW) else -1
        if pos:
            _,high,low,close=bar.ohlc()
            spread_jpy=spread_pips*PIP_JPY
            adverse=((low-spread_jpy)/entry-1.0) if pos==1 else (entry/(high+spread_jpy)-1.0)
            favorable=((high-spread_jpy)/entry-1.0) if pos==1 else (entry/(low+spread_jpy)-1.0)
            close_move=pos*((close-spread_jpy*pos)/entry-1.0)
            adverse_pnl=max(-risk_budget, units_scale*risk_budget*adverse/DISTANCE)
            adverse_eq=max(0.0,entry_equity+adverse_pnl)
            max_dd=max(max_dd,(peak-adverse_eq)/peak if peak else 0.0)
            favorable_eq=max(0.0,entry_equity+units_scale*risk_budget*favorable/DISTANCE)
            peak=max(peak,favorable_eq)
            if favorable_eq>=TARGET_YEN:
                equity=TARGET_YEN; target=True; pos=0; break
            if adverse<=-DISTANCE:
                equity=max(0.0,entry_equity-risk_budget); pos=0
            elif signal!=pos:
                pnl=max(-risk_budget,units_scale*risk_budget*close_move/DISTANCE)
                equity=max(0.0,entry_equity+pnl); pos=0
            peak=max(peak,equity)
            max_dd=max(max_dd,(peak-equity)/peak if peak else 0.0)
        if not pos and equity>1_000.0:
            pos=signal; entry=bar.close; entry_equity=equity; risk_budget=equity*RISK_FRACTION
            distance_jpy=entry*DISTANCE
            # Same max-loss budget must fund both KO distance and premium,
            # reducing effective exposure versus the zero-premium model.
            units_scale=distance_jpy/(distance_jpy+KO_PREMIUM_JPY)
    if pos and equity>1_000.0 and not target:
        spread_jpy=spread_pips*PIP_JPY
        close_move=pos*((bars[-1].close-spread_jpy*pos)/entry-1.0)
        pnl=max(-risk_budget,units_scale*risk_budget*close_move/DISTANCE)
        equity=max(0.0,entry_equity+pnl)
    return {"final_yen":round(equity,2),"target_hit":target,
            "below_5000":equity<FLOOR_YEN,"max_dd_pct":round(max_dd*100,4)}

def windows(bars, spread):
    out=[]; cur=bars[0].ts.replace(hour=0,minute=0,second=0,microsecond=0); end=bars[-1].ts
    while cur+timedelta(days=7)<=end:
        stop=cur+timedelta(days=7); chunk=[b for b in bars if cur<=b.ts<stop]
        if len(chunk)>SLOW: out.append(run_window(chunk,spread))
        cur+=timedelta(days=1)
    return out

def summarize(rows):
    finals=sorted(r["final_yen"] for r in rows); n=len(rows)
    med=finals[n//2] if n%2 else (finals[n//2-1]+finals[n//2])/2
    return {"windows":n,"target_hits":sum(r["target_hit"] for r in rows),
            "target_rate_pct":round(100*sum(r["target_hit"] for r in rows)/n,4),
            "below_5000":sum(r["below_5000"] for r in rows),
            "below_5000_rate_pct":round(100*sum(r["below_5000"] for r in rows)/n,4),
            "median_final_yen":round(med,2),"best_final_yen":max(finals),
            "worst_final_yen":min(finals),
            "avg_max_dd_pct":round(sum(r["max_dd_pct"] for r in rows)/n,4)}

def main():
    bars=parse_chart(fetch_chart("GBPJPY=X"))
    return {"paper_only":True,"market":"GBPJPY","target_yen":TARGET_YEN,
            "distance_pct":DISTANCE*100,"risk_fraction_pct":RISK_FRACTION*100,
            "ko_premium_jpy":KO_PREMIUM_JPY,"funding":"omitted_optimistic",
            "spread_scenarios":{f"{s:.0f}pip":summarize(windows(bars,s)) for s in SPREAD_PIPS}}

if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
