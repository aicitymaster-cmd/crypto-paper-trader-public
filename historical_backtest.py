"""Robust high-return spot-only PAPER search across independent 7-day windows.

Priority:
1) reject candidates that lose on unseen validation weeks,
2) among survivors, maximize seven-day return toward JPY 200,000.

No credentials, no account access, no live orders, no leverage, no borrowing.
Historical OHLCV does not preserve historical bid/ask spread; configured fee and
slippage are modeled, unavailable historical spread is not.
"""
from __future__ import annotations
import json, math, ssl, statistics, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, ROUND_DOWN
from itertools import product
from pathlib import Path

CFG=json.loads(Path(__file__).with_name("paper_campaign_v2.json").read_text())
RISK=CFG["common_risk"]
START=D(CFG["initial_state"]["cash_yen_per_strategy"]); TARGET=D("200000")
FEE=D(RISK["fee_rate_each_side"]); SLIP=D(RISK["slippage_rate_each_side"])
UA="crypto-paper-robust-seven-day-search/1.0"

def get_json(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
    ctx=ssl.create_default_context()
    with urllib.request.urlopen(req,timeout=20,context=ctx) as r: obj=json.loads(r.read())
    if obj.get("success")!=1: raise RuntimeError("API_FAILED")
    return obj["data"]

def discover_pairs():
    data=get_json("https://api.bitbank.cc/v1/spot/pairs")
    out=[]
    for p in data.get("pairs",[]):
        name=str(p.get("name","")).lower()
        if (p.get("is_enabled") is True and p.get("quote_asset")=="jpy"
            and not p.get("stop_buy_order") and not p.get("stop_sell_order")):
            out.append(name)
    return sorted(set(out))

def fetch_year(pair,year):
    try:
        rows=get_json(f"https://public.bitbank.cc/{pair}/candlestick/4hour/{year}")["candlestick"][0]["ohlcv"]
        return [(int(ts),D(o),D(h),D(l),D(c),D(v)) for o,h,l,c,v,ts in rows]
    except Exception:
        return []

def sma(xs,n): return sum(xs[-n:],D(0))/D(n)

def profile_grid():
    out={}; i=0
    for fraction,take,stop,breadth,cooldown,max_hold,loss_limit in product(
        (D("0.50"),D("0.75"),D("0.95")),
        (D("0.12"),D("0.20")),
        (D("0.03"),D("0.05")),
        (D("0.55"),D("0.65")),
        (1,3),
        (12,24),
        (D("0.03"),D("0.05")),
    ):
        i+=1
        out[f"r{i:03d}"]={
          "fraction":fraction,"take":take,"stop":stop,"breadth":breadth,
          "cooldown":cooldown,"max_hold":max_hold,"loss_limit":loss_limit,
          "mom3":D("0.02"),"mom6":D("0.035"),"volume_ratio":D("1.10"),
          "pause_after_losses":2,"pause_bars":6
        }
    return out

PROFILES=profile_grid()

def new_account():
    return {"cash":START,"positions":{},"fees":D(0),"sells":0,"wins":0,
            "peak":START,"max_dd":D(0),"last_exit":{},"loss_streak":0,
            "pause_until":-1,"symbols_used":[]}

def equity(a,prices):
    return a["cash"]+sum(pos["qty"]*prices[s] for s,pos in a["positions"].items() if s in prices)

def sell(a,sym,close,ts,index):
    pos=a["positions"].pop(sym); px=close*(D(1)-SLIP)
    gross=pos["qty"]*px; fee=gross*FEE; net=gross-fee; pnl=net-pos["cost"]
    a["cash"]+=net; a["fees"]+=fee; a["sells"]+=1; a["last_exit"][sym]=ts
    if pnl>0:
        a["wins"]+=1; a["loss_streak"]=0
    else:
        a["loss_streak"]+=1
    return pnl

def buy(a,sym,close,ts,p,index):
    if a["positions"] or index<a["pause_until"]:return
    last=a["last_exit"].get(sym)
    if last is not None and ts-last<p["cooldown"]*4*60*60*1000:return
    # Increase exposure only while the account is already above start.
    growth=max(D(1),a["cash"]/START)
    fraction=min(D("0.99"),p["fraction"]*(D("1")+min(D("0.20"),(growth-D(1))*D("0.25"))))
    px=close*(D(1)+SLIP); budget=a["cash"]*fraction
    qty=(budget/(px*(D(1)+FEE))).quantize(D("0.00000001"),rounding=ROUND_DOWN)
    if qty<=0:return
    gross=qty*px; fee=gross*FEE; cost=gross+fee
    if cost>a["cash"]:return
    a["cash"]-=cost; a["fees"]+=fee
    a["positions"][sym]={"qty":qty,"entry":px,"cost":cost,"entry_ts":ts,"entry_index":index}
    if sym not in a["symbols_used"]:a["symbols_used"].append(sym)

def market_breadth(histories):
    eligible=up=0
    for h in histories.values():
        if len(h)<12:continue
        closes=[b[4] for b in h]
        eligible+=1
        if closes[-1]>sma(closes,6)>sma(closes,12):up+=1
    return D(up)/D(eligible) if eligible else D(0)

def candidate_score(h,p):
    if len(h)<12:return None
    closes=[b[4] for b in h]; vols=[b[5] for b in h]
    c=closes[-1]
    mom3=c/closes[-3]-D(1); mom6=c/closes[-6]-D(1)
    vol_avg=sum(vols[-6:-1],D(0))/D(5) if len(vols)>=6 else D(0)
    vol_ratio=(vols[-1]/vol_avg) if vol_avg>0 else D(0)
    trend=c>sma(closes,3)>sma(closes,9)
    if not trend or mom3<p["mom3"] or mom6<p["mom6"] or vol_ratio<p["volume_ratio"]:
        return None
    # Favor strong momentum, but penalize extremely stretched one-bar spikes.
    one=c/closes[-2]-D(1)
    if one>D("0.20"):return None
    return mom3*D("2")+mom6+min(vol_ratio,D("3"))/D("20")

def run_window(start_day,bars_by_pair,p):
    start=datetime.combine(start_day,datetime.min.time(),tzinfo=timezone.utc)
    end=start+timedelta(days=7); start_ms=int(start.timestamp()*1000); end_ms=int(end.timestamp()*1000)
    warm_ms=int((start-timedelta(days=7)).timestamp()*1000)
    histories={s:[] for s in bars_by_pair}; by_ts=defaultdict(dict)
    for sym,bars in bars_by_pair.items():
        for b in bars:
            if warm_ms<=b[0]<end_ms:by_ts[b[0]][sym]=b
    a=new_account(); prices={}
    for index,ts in enumerate(sorted(by_ts)):
        row=by_ts[ts]
        for sym,b in row.items():
            histories[sym].append(b); histories[sym]=histories[sym][-36:]; prices[sym]=b[4]
        if ts<start_ms:continue

        for sym in list(a["positions"]):
            if sym not in row:continue
            cur=row[sym][4]; pos=a["positions"][sym]
            held=index-pos["entry_index"]
            reason=(cur<=pos["entry"]*(D(1)-p["stop"]) or
                    cur>=pos["entry"]*(D(1)+p["take"]) or
                    held>=p["max_hold"])
            if reason:
                pnl=sell(a,sym,cur,ts,index)
                if pnl<=0 and a["loss_streak"]>=p["pause_after_losses"]:
                    a["pause_until"]=index+p["pause_bars"]; a["loss_streak"]=0

        eq=equity(a,prices)
        if eq<=START*(D(1)-p["loss_limit"]):
            # Weekly circuit breaker: no new risk after reaching the loss limit.
            continue

        if not a["positions"] and index>=a["pause_until"] and market_breadth(histories)>=p["breadth"]:
            candidates=[]
            for sym in row:
                score=candidate_score(histories[sym],p)
                if score is not None:candidates.append((score,sym,row[sym][4]))
            if candidates:
                _,sym,close=max(candidates)
                buy(a,sym,close,ts,p,index)

        eq=equity(a,prices); a["peak"]=max(a["peak"],eq)
        if a["peak"]>0:a["max_dd"]=max(a["max_dd"],(a["peak"]-eq)/a["peak"])

    last_ts=max(by_ts) if by_ts else end_ms
    for sym in list(a["positions"]):sell(a,sym,prices[sym],last_ts,len(by_ts))
    final=a["cash"]
    return {
      "final_yen":float(final),"return_pct":float((final/START-D(1))*100),
      "closed_trades":a["sells"],"wins":a["wins"],"fees_yen":float(a["fees"]),
      "max_drawdown_pct":float(a["max_dd"]*100),"hit_200k":final>=TARGET,
      "profitable":final>=START,"symbols_used":sorted(a["symbols_used"])
    }

def main():
    now=datetime.now(timezone.utc); end_day=(now-timedelta(days=1)).date()
    pairs=discover_pairs(); bars={}; year=str(end_day.year)
    for pair in pairs:
        rows=fetch_year(pair,year)
        if rows:bars[pair]=rows

    starts=[end_day-timedelta(days=55-7*i) for i in range(8)]
    labels=[f"{s.isoformat()}..{(s+timedelta(days=6)).isoformat()}" for s in starts]
    search_ids=(0,1,2,3); validation_ids=(4,5,6,7)
    candidates=[]; best=None; target_hits=0
    for name,p in PROFILES.items():
        wr=[run_window(s,bars,p) for s in starts]
        target_hits+=sum(int(r["hit_200k"]) for r in wr)
        for i,r in enumerate(wr):
            item={"profile":name,"window":labels[i],**r}
            if best is None or r["final_yen"]>best["final_yen"]:best=item
        vals=[wr[i]["return_pct"] for i in validation_ids]
        profitable_all=all(wr[i]["profitable"] for i in validation_ids)
        candidates.append({
          "profile":name,
          "settings":{"fraction":str(p["fraction"]),"take_profit":str(p["take"]),
                      "stop_loss":str(p["stop"]),"breadth":str(p["breadth"]),
                      "cooldown_bars":p["cooldown"],"max_hold_bars":p["max_hold"],
                      "weekly_loss_limit":str(p["loss_limit"])},
          "search_avg_return_pct":round(statistics.mean(wr[i]["return_pct"] for i in search_ids),3),
          "validation_avg_return_pct":round(statistics.mean(vals),3),
          "validation_median_return_pct":round(statistics.median(vals),3),
          "validation_worst_return_pct":round(min(vals),3),
          "validation_best_return_pct":round(max(vals),3),
          "validation_all_nonnegative":profitable_all,
          "validation_target_hits":sum(int(wr[i]["hit_200k"]) for i in validation_ids),
          "validation_windows":[wr[i] for i in validation_ids]
        })

    robust=[x for x in candidates if x["validation_all_nonnegative"]]
    robust_ranked=sorted(robust,key=lambda x:(x["validation_target_hits"],x["validation_median_return_pct"],x["validation_worst_return_pct"]),reverse=True)
    overall_ranked=sorted(candidates,key=lambda x:(x["validation_all_nonnegative"],x["validation_target_hits"],x["validation_median_return_pct"],x["validation_worst_return_pct"]),reverse=True)
    result={
      "paper_only":True,"stage":"robust_high_return_expanded_universe",
      "goal":{"start_yen":10000,"target_yen":200000,"days":7,"minimum":"nonnegative_on_all_validation_windows"},
      "constraints":{"spot_only":True,"leverage":False,"borrowing":False},
      "pairs_discovered":len(pairs),"pairs_with_4hour_history":len(bars),
      "profiles_tested":len(PROFILES),"total_7day_runs":len(PROFILES)*8,
      "windows":labels,"target_hits_all_runs":target_hits,
      "robust_candidates_count":len(robust),
      "best_single_7day_run":best,
      "top_robust_candidates":robust_ranked[:10],
      "top_overall_candidates":overall_ranked[:10],
      "historical_spread_available":False,
      "modeled_costs":{"fee_each_side":str(FEE),"slippage_each_side":str(SLIP),"reserve_rate":"0"}
    }
    print(json.dumps(result,ensure_ascii=False))
    Path("historical-backtest-results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
