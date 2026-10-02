"""Frozen forward signal for the selected GOLD KO research candidate.

No parameter optimization. Uses only data available before the scheduled entry.
Entry rule:
- Thursday 16:00 UTC bar, evaluated only after that 1h bar has closed
- abs move over prior 24h >= 1.0%
- paper-only candidate: GOLD KO distance 0.75%, target JPY 50k, start JPY 10k

Outputs ELIGIBLE / NOT_ELIGIBLE plus the exact inputs used.
"""
from __future__ import annotations
import json
from datetime import timedelta, datetime, timezone
from gold_filter_holdout import fetch, parse

WEEKDAY=3
UTC_HOUR=16
MIN_ABS_MOVE=0.01
KO_DISTANCE_PCT=0.0075
START_JPY=10_000
TARGET_JPY=50_000

def latest_complete_entry(bars, now=None):
    now=now or datetime.now(timezone.utc)
    monday=(now-timedelta(days=now.weekday())).date()
    eligible=[b for b in bars if b.ts.weekday()==WEEKDAY and b.ts.hour==UTC_HOUR and b.ts.date()>=monday and b.ts+timedelta(hours=1)<=now]
    if not eligible:
        return None
    return eligible[-1]

def evaluate(bars, now=None):
    entry=latest_complete_entry(bars,now=now)
    if entry is None:
        return {"status":"WAITING_ENTRY_WINDOW","parameters_frozen":True,"paper_only":True}
    hist=[b for b in bars if entry.ts-timedelta(hours=24) <= b.ts < entry.ts]
    if len(hist)<8:
        return {"status":"INSUFFICIENT_HISTORY","entry_utc":entry.ts.isoformat()}
    move=abs(hist[-1].close/hist[0].close-1.0)
    return {
        "status":"ELIGIBLE" if move>=MIN_ABS_MOVE else "NOT_ELIGIBLE",
        "entry_utc":entry.ts.isoformat(),
        "entry_reference_price":round(entry.close,4),
        "prior_24h_start_price":round(hist[0].close,4),
        "prior_24h_end_price":round(hist[-1].close,4),
        "prior_24h_abs_move_pct":round(move*100,4),
        "threshold_pct":MIN_ABS_MOVE*100,
        "ko_distance_pct":KO_DISTANCE_PCT*100,
        "approx_ko_distance_points":round(entry.close*KO_DISTANCE_PCT,4),
        "start_jpy":START_JPY,
        "target_jpy":TARGET_JPY,
        "parameters_frozen":True,
        "paper_only":True,
    }

def main():
    bars=parse(fetch())
    print(json.dumps(evaluate(bars),ensure_ascii=False,sort_keys=True))

if __name__=="__main__": main()
