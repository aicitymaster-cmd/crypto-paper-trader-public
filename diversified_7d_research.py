"""PAPER-only diversified 7-day portfolio research.

Splits JPY 10,000 equally across independent public-market OHLC series and
tests the same 7-day calendar windows. Research only: no orders, auth, or
broker-specific execution assumptions.
"""
from __future__ import annotations
import itertools, json
from datetime import timedelta
from statistics import median

from cross_market_backtest import run_window
from cross_market_public_run import MARKETS, fetch_chart, parse_chart

START_YEN = 10_000.0
TARGET_YEN = 50_000.0
FLOOR_YEN = 5_000.0
LEVERAGES = (5, 10, 25)
PORTFOLIO_SIZES = (2, 3)
SPREAD_BPS = 5.0
FEE_BPS = 1.0
FAST = 12
SLOW = 36
STOP_PCT = 0.01
TAKE_PCT = 0.03

def evaluate(finals):
    if not finals:
        return {"windows": 0}
    n=len(finals)
    return {
        "windows": n,
        "target_hits": sum(v >= TARGET_YEN for v in finals),
        "target_rate_pct": round(100*sum(v >= TARGET_YEN for v in finals)/n, 4),
        "at_least_5000": sum(v >= FLOOR_YEN for v in finals),
        "at_least_5000_rate_pct": round(100*sum(v >= FLOOR_YEN for v in finals)/n, 4),
        "median_final_yen": round(median(finals), 2),
        "best_final_yen": round(max(finals), 2),
        "worst_final_yen": round(min(finals), 2),
    }

def split_evaluate(finals):
    n=len(finals); mid=n//2
    return {
        "all": evaluate(finals),
        "first_half": evaluate(finals[:mid]),
        "second_half": evaluate(finals[mid:]),
    }

def robustness_key(row):
    parts=(row["summary"]["first_half"], row["summary"]["second_half"])
    min_target=min(p.get("target_rate_pct",0) for p in parts)
    min_floor=min(p.get("at_least_5000_rate_pct",0) for p in parts)
    all_s=row["summary"]["all"]
    return (min_target, min_floor, all_s.get("target_rate_pct",0), all_s.get("median_final_yen",0))

def common_windows(series, names):
    first=max(series[n][0].ts for n in names)
    last=min(series[n][-1].ts for n in names)
    cursor=first.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
    while cursor+timedelta(days=7)<=last:
        stop=cursor+timedelta(days=7)
        chunks={n:[b for b in series[n] if cursor<=b.ts<stop] for n in names}
        if all(len(v)>SLOW for v in chunks.values()):
            yield cursor,chunks
        cursor+=timedelta(days=1)

def simulate(series, names, leverage):
    allocation=START_YEN/len(names)
    finals=[]
    dates=[]
    for start,chunks in common_windows(series,names):
        total=0.0
        for n in names:
            r=run_window(
                chunks[n], start_yen=allocation, leverage=float(leverage),
                spread_bps=SPREAD_BPS, fee_bps=FEE_BPS, fast=FAST, slow=SLOW,
                stop_pct=STOP_PCT, take_pct=TAKE_PCT,
                target_yen=1e12, ruin_yen=0.0,
            )
            total+=r.final_yen
        finals.append(round(total,2)); dates.append(start.date().isoformat())
    return finals,dates

def run_all():
    series={}; failures={}
    for name,symbol in MARKETS.items():
        try:
            series[name]=parse_chart(fetch_chart(symbol))
        except Exception as exc:
            failures[name]=f"{type(exc).__name__}:{exc}"
    rows=[]
    names=sorted(series)
    for size in PORTFOLIO_SIZES:
        for combo in itertools.combinations(names,size):
            for lev in LEVERAGES:
                finals,dates=simulate(series,combo,lev)
                if not finals:
                    continue
                rows.append({
                    "markets": combo, "leverage": lev,
                    "summary": split_evaluate(finals),
                    "first_window": dates[0], "last_window": dates[-1],
                })
    rows.sort(key=robustness_key, reverse=True)
    return {
        "paper_only": True,
        "start_yen": START_YEN,
        "target_yen": TARGET_YEN,
        "floor_yen": FLOOR_YEN,
        "method": "equal-weight 2/3-market portfolio; same 7-day windows; rank by weakest-half target then floor retention",
        "cost_assumption": {"spread_bps":SPREAD_BPS,"fee_bps_each_side":FEE_BPS},
        "tested_cases": len(rows),
        "top_10": rows[:10],
        "failures": failures,
    }

if __name__=="__main__":
    print(json.dumps(run_all(),ensure_ascii=False,sort_keys=True))
