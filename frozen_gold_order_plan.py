"""Prepare exact frozen GOLD KO order-plan numbers without placing an order.

Runs only from the already-frozen forward signal. If NOT_ELIGIBLE or before
the entry window, no order plan is produced. If ELIGIBLE, calculates reference
KO levels at +/-0.75% and budget feasibility under several possible minimum
lot increments because IG's public commodity-KO page does not state the
minimum new-order lot size.

PAPER / PREPARATION ONLY. Never submits orders.
"""
from __future__ import annotations
import json
from frozen_gold_forward_signal import evaluate
from gold_filter_holdout import fetch, parse

USDJPY_REF=158.2
KO_PREMIUM_POINTS=0.5
START_JPY=10_000.0
KO_PCT=0.0075
LOT_CANDIDATES=(0.04,0.1,1.0)

def plan(sig):
    if sig.get("status")!="ELIGIBLE":
        return {"status":sig.get("status"),"paper_only":True,"order_allowed":False}
    px=float(sig["entry_reference_price"])
    d=px*KO_PCT
    option_points=d+KO_PREMIUM_POINTS
    budget_usd=START_JPY/USDJPY_REF
    sizes=[]
    for lot in LOT_CANDIDATES:
        est_jpy=option_points*lot*USDJPY_REF
        sizes.append({
            "lot":lot,
            "estimated_max_loss_jpy":round(est_jpy,0),
            "fits_10000_jpy":est_jpy<=START_JPY,
        })
    return {
        "status":"ELIGIBLE",
        "paper_only":True,
        "order_allowed":False,
        "reference_price":round(px,2),
        "ko_distance_pct":KO_PCT*100,
        "ko_distance_points":round(d,2),
        "bull_ko_reference":round(px-d,2),
        "bear_ko_reference":round(px+d,2),
        "ko_premium_points_reference":KO_PREMIUM_POINTS,
        "estimated_option_points_per_lot":round(option_points,2),
        "budget_jpy":START_JPY,
        "usdjpy_reference":USDJPY_REF,
        "lot_feasibility":sizes,
        "note":"Final IG screen values override these references; do not place an order from this file alone.",
    }

def main():
    sig=evaluate(parse(fetch()))
    print(json.dumps({"signal":sig,"order_plan":plan(sig)},ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
