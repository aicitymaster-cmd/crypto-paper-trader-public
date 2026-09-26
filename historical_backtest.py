"""Search aggressive spot-only PAPER strategies across independent 7-day windows.

Goal under test: JPY 10,000 -> JPY 200,000 in seven days.
No credentials, no account access, no live orders, no leverage, no borrowing.
Historical OHLCV does not preserve historical bid/ask spread; configured fees
and slippage are modeled, while unavailable historical spread is not.
"""
from __future__ import annotations
import json, math, ssl, time, urllib.request, statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, ROUND_DOWN
from itertools import product
from pathlib import Path

CFG=json.loads(Path(__file__).with_name("paper_campaign_v2.json").read_text())
RISK=CFG["common_risk"]
ASSETS={"BTC":"btc_jpy","ETH":"eth_jpy","SOL":"sol_jpy","XRP":"xrp_jpy","DOGE":"doge_jpy"}
STRATEGIES=("momentum","breakout","mean_reversion")
START=D(CFG["initial_state"]["cash_yen_per_strategy"])
TARGET=D("200000")
FEE=D(RISK["fee_rate_each_side"]); SLIP=D(RISK["slippage_rate_each_side"])
RESERVE_RATE=D(RISK["reserve_rate"])
UA="crypto-paper-seven-day-target-search/1.0"

def profiles():
    out={}
    i=0
    # Aggressive but still spot-only. Capital fraction never exceeds cash.
    for fraction,take,stop,cooldown,max_hold in product(
        (D("0.50"),D("0.75"),D("0.95")),
        (D("0.03"),D("0.05"),D("0.08")),
        (D("0.01"),D("0.02")),
        (6,18),
        (72,144),
    ):
        i+=1
        out[f"p{i:03d}"]={
          "fraction":fraction,"max_pos":1,"stop":stop,"take":take,
          "max_hold":max_hold,"cooldown":cooldown,"exit_signal":False,
          "mom_lookback":12,"mom_min":D("0.004"),
          "break_buffer":D("0.002"),
          "mean_z":D("-2.3"),"mean_trend":D("0.998")
        }
    return out

PROFILES=profiles()

def get_json(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
    ctx=ssl.create_default_context()
    with urllib.request.urlopen(req,timeout=20,context=ctx) as r: obj=json.loads(r.read())
    if obj.get("success")!=1: raise RuntimeError("API_FAILED")
    return obj["data"]

def fetch_day(pair,day):
    rows=get_json(f"https://public.bitbank.cc/{pair}/candlestick/5min/{day:%Y%m%d}")["candlestick"][0]["ohlcv"]
    return [(int(ts),D(o),D(h),D(l),D(c),D(v)) for o,h,l,c,v,ts in rows]

def sma(xs,n): return sum(xs[-n:],D(0))/D(n)

def zscore(xs,n):
    vals=[float(x) for x in xs[-n:]]; mean=sum(vals)/n
    sd=math.sqrt(sum((x-mean)**2 for x in vals)/n)
    return D("0") if sd==0 else D(str((vals[-1]-mean)/sd))

def signal(strategy,bars,p):
    if len(bars)<60:return "skip"
    closes=[b[4] for b in bars]; highs=[b[2] for b in bars]; c=closes[-1]
    if strategy=="momentum":
        lb=p["mom_lookback"]; s12,s36=sma(closes,12),sma(closes,36)
        momentum=c/closes[-lb]-D(1)
        return "buy" if c>s12>s36 and momentum>=p["mom_min"] else "sell" if c<s12 else "skip"
    if strategy=="breakout":
        prior=max(highs[-21:-1])
        return "buy" if c>prior*(D(1)+p["break_buffer"]) else "sell" if c<sma(closes,12) else "skip"
    zz=zscore(closes,20); trend=sma(closes,20)>=sma(closes,50)*p["mean_trend"]
    return "buy" if zz<=p["mean_z"] and trend else "sell" if zz>=0 else "skip"

def new_account():
    return {"cash":START,"reserve":D(0),"positions":{},"sells":0,"wins":0,
            "fees":D(0),"max_dd":D(0),"peak":START,"last_exit":{}}

def equity(a,prices):
    return a["cash"]+a["reserve"]+sum(pos["qty"]*prices[s] for s,pos in a["positions"].items() if s in prices)

def buy(a,sym,close,ts,p):
    if sym in a["positions"] or len(a["positions"])>=p["max_pos"]:return
    last=a["last_exit"].get(sym)
    if last is not None and ts-last < p["cooldown"]*5*60*1000:return
    px=close*(D(1)+SLIP); budget=a["cash"]*p["fraction"]
    qty=(budget/(px*(D(1)+FEE))).quantize(D("0.00000001"),rounding=ROUND_DOWN)
    if qty<=0:return
    gross=qty*px; fee=gross*FEE; cost=gross+fee
    if cost>a["cash"]:return
    a["cash"]-=cost; a["fees"]+=fee
    a["positions"][sym]={"qty":qty,"entry":px,"cost":cost,"entry_ts":ts}

def sell(a,sym,close,ts):
    pos=a["positions"].pop(sym); px=close*(D(1)-SLIP)
    gross=pos["qty"]*px; fee=gross*FEE; net=gross-fee; pnl=net-pos["cost"]
    reserve=max(D(0),pnl*RESERVE_RATE)
    a["cash"]+=net-reserve; a["reserve"]+=reserve; a["fees"]+=fee
    a["sells"]+=1; a["last_exit"][sym]=ts
    if pnl>0:a["wins"]+=1

def run_window(start_day,bars_by_asset,p,strategy):
    start=datetime.combine(start_day,datetime.min.time(),tzinfo=timezone.utc)
    end=start+timedelta(days=7); start_ms=int(start.timestamp()*1000); end_ms=int(end.timestamp()*1000)
    warm_ms=int((start-timedelta(days=1)).timestamp()*1000)
    histories={s:[] for s in ASSETS}; by_ts=defaultdict(dict)
    for sym,bars in bars_by_asset.items():
        for b in bars:
            if warm_ms<=b[0]<end_ms:by_ts[b[0]][sym]=b
    a=new_account(); prices={}
    for ts in sorted(by_ts):
        row=by_ts[ts]
        for sym,b in row.items():
            histories[sym].append(b); histories[sym]=histories[sym][-180:]; prices[sym]=b[4]
        if ts<start_ms:continue
        for sym in list(a["positions"]):
            if sym not in row:continue
            cur=row[sym][4]; pos=a["positions"][sym]
            held=max(0,int((ts-pos["entry_ts"])/(5*60*1000)))
            sig=signal(strategy,histories[sym],p)
            should_sell=(cur<=pos["entry"]*(D(1)-p["stop"]) or
                         cur>=pos["entry"]*(D(1)+p["take"]) or
                         held>=p["max_hold"] or
                         (p["exit_signal"] and sig=="sell"))
            if should_sell:sell(a,sym,cur,ts)
        candidates=[]
        for sym,b in row.items():
            if sym in a["positions"]:continue
            if signal(strategy,histories[sym],p)=="buy":
                h=histories[sym]; score=abs(h[-1][4]/h[-4][4]-D(1))
                candidates.append((score,sym,b[4]))
        for _,sym,close in sorted(candidates,reverse=True):
            if len(a["positions"])>=p["max_pos"]:break
            buy(a,sym,close,ts,p)
        eq=equity(a,prices); a["peak"]=max(a["peak"],eq)
        if a["peak"]>0:a["max_dd"]=max(a["max_dd"],(a["peak"]-eq)/a["peak"])
    last_ts=max(by_ts) if by_ts else end_ms
    for sym in list(a["positions"]):sell(a,sym,prices[sym],last_ts)
    final=a["cash"]+a["reserve"]
    return {
      "final_yen":float(final),
      "return_pct":float((final/START-D(1))*D(100)),
      "closed_trades":a["sells"],"wins":a["wins"],
      "fees_yen":float(a["fees"]),
      "max_drawdown_pct":float(a["max_dd"]*D(100)),
      "hit_200k":final>=TARGET,
    }

def summarize_candidate(name,strategy,p,window_results,search_ids,validation_ids):
    search=[window_results[i] for i in search_ids]
    validation=[window_results[i] for i in validation_ids]
    vals=[r["return_pct"] for r in validation]
    return {
      "profile":name,"strategy":strategy,
      "settings":{
        "fraction":str(p["fraction"]),"take_profit":str(p["take"]),
        "stop_loss":str(p["stop"]),"cooldown_bars":p["cooldown"],
        "max_hold_bars":p["max_hold"]
      },
      "search_avg_return_pct":round(statistics.mean(r["return_pct"] for r in search),3),
      "validation_avg_return_pct":round(statistics.mean(vals),3),
      "validation_median_return_pct":round(statistics.median(vals),3),
      "validation_worst_return_pct":round(min(vals),3),
      "validation_best_return_pct":round(max(vals),3),
      "validation_target_hits":sum(1 for r in validation if r["hit_200k"]),
      "validation_windows":validation,
    }

def main():
    end_day=(datetime.now(timezone.utc)-timedelta(days=1)).date()
    first=end_day-timedelta(days=56)
    bars={s:[] for s in ASSETS}; d=first
    while d<=end_day:
        for sym,pair in ASSETS.items():
            bars[sym].extend(fetch_day(pair,d)); time.sleep(0.03)
        d+=timedelta(days=1)

    # Eight non-overlapping completed 7-day windows, oldest first.
    starts=[end_day-timedelta(days=55-7*i) for i in range(8)]
    window_labels=[f"{s.isoformat()}..{(s+timedelta(days=6)).isoformat()}" for s in starts]
    search_ids=(0,1,2,3); validation_ids=(4,5,6,7)

    candidates=[]
    best_single=None
    total_target_hits=0
    for name,p in PROFILES.items():
        for strategy in STRATEGIES:
            wr=[run_window(s,bars,p,strategy) for s in starts]
            for idx,r in enumerate(wr):
                total_target_hits+=int(r["hit_200k"])
                item={"profile":name,"strategy":strategy,"window":window_labels[idx],**r}
                if best_single is None or r["final_yen"]>best_single["final_yen"]:best_single=item
            candidates.append(summarize_candidate(name,strategy,p,wr,search_ids,validation_ids))

    # Rank on unseen validation robustness, not one lucky week.
    ranked=sorted(candidates,key=lambda x:(
        x["validation_target_hits"],
        x["validation_median_return_pct"],
        x["validation_worst_return_pct"]
    ),reverse=True)

    result={
      "paper_only":True,
      "goal":{"start_yen":10000,"target_yen":200000,"target_multiplier":20,"days":7},
      "constraints":{"spot_only":True,"leverage":False,"borrowing":False},
      "data_source":"bitbank public 5min OHLCV",
      "historical_spread_available":False,
      "modeled_costs":{"fee_each_side":str(FEE),"slippage_each_side":str(SLIP)},
      "windows":window_labels,
      "search_windows":[window_labels[i] for i in search_ids],
      "validation_windows":[window_labels[i] for i in validation_ids],
      "profiles_tested":len(PROFILES),
      "candidate_strategy_combinations":len(candidates),
      "total_7day_runs":len(candidates)*8,
      "target_hits_all_runs":total_target_hits,
      "best_single_7day_run":best_single,
      "top_validation_candidates":ranked[:10],
    }
    print(json.dumps(result,ensure_ascii=False))
    Path("historical-backtest-results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
