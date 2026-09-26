"""Expanded-universe spot-only PAPER discovery using bitbank public data.

Stage 1: discover all enabled JPY spot pairs and scan 4-hour candles.
Goal under test: JPY 10,000 -> JPY 200,000 in seven days.
No credentials, no account access, no live orders, no leverage, no borrowing.
"""
from __future__ import annotations
import json, math, ssl, urllib.request, statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, ROUND_DOWN
from itertools import product
from pathlib import Path

CFG=json.loads(Path(__file__).with_name("paper_campaign_v2.json").read_text())
RISK=CFG["common_risk"]
START=D(CFG["initial_state"]["cash_yen_per_strategy"])
TARGET=D("200000")
FEE=D(RISK["fee_rate_each_side"]); SLIP=D(RISK["slippage_rate_each_side"])
RESERVE_RATE=D(RISK["reserve_rate"])
UA="crypto-paper-expanded-universe/1.0"

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

def zscore(xs,n):
    vals=[float(x) for x in xs[-n:]]
    mean=sum(vals)/len(vals)
    sd=math.sqrt(sum((x-mean)**2 for x in vals)/len(vals))
    return D("0") if sd==0 else D(str((vals[-1]-mean)/sd))

def signal(strategy,bars,p):
    if len(bars)<20:return "skip"
    closes=[b[4] for b in bars]; highs=[b[2] for b in bars]; c=closes[-1]
    if strategy=="momentum":
        s3,s9=sma(closes,3),sma(closes,9)
        momentum=c/closes[-p["mom_lookback"]]-D(1)
        return "buy" if c>s3>s9 and momentum>=p["mom_min"] else "sell" if c<s3 else "skip"
    if strategy=="breakout":
        prior=max(highs[-7:-1])
        return "buy" if c>prior*(D(1)+p["break_buffer"]) else "sell" if c<sma(closes,3) else "skip"
    zz=zscore(closes,12); trend=sma(closes,6)>=sma(closes,12)*p["mean_trend"]
    return "buy" if zz<=p["mean_z"] and trend else "sell" if zz>=0 else "skip"

def profiles():
    out={}; i=0
    for fraction,take,stop,cooldown,max_hold in product(
        (D("0.50"),D("0.75"),D("0.95")),
        (D("0.08"),D("0.15"),D("0.25")),
        (D("0.03"),D("0.06")),
        (1,3),
        (12,24),
    ):
        i+=1
        out[f"p{i:03d}"]={
          "fraction":fraction,"take":take,"stop":stop,"cooldown":cooldown,
          "max_hold":max_hold,"mom_lookback":3,"mom_min":D("0.02"),
          "break_buffer":D("0.01"),"mean_z":D("-2.0"),"mean_trend":D("0.995")
        }
    return out

PROFILES=profiles()
STRATEGIES=("momentum","breakout","mean_reversion")

def new_account():
    return {"cash":START,"reserve":D(0),"positions":{},"last_exit":{},
            "fees":D(0),"sells":0,"wins":0,"peak":START,"max_dd":D(0),
            "symbols_used":[]}

def equity(a,prices):
    return a["cash"]+a["reserve"]+sum(pos["qty"]*prices[s] for s,pos in a["positions"].items() if s in prices)

def buy(a,sym,close,ts,p):
    if a["positions"]:return
    last=a["last_exit"].get(sym)
    if last is not None and ts-last<p["cooldown"]*4*60*60*1000:return
    px=close*(D(1)+SLIP); budget=a["cash"]*p["fraction"]
    qty=(budget/(px*(D(1)+FEE))).quantize(D("0.00000001"),rounding=ROUND_DOWN)
    if qty<=0:return
    gross=qty*px; fee=gross*FEE; cost=gross+fee
    if cost>a["cash"]:return
    a["cash"]-=cost; a["fees"]+=fee
    a["positions"][sym]={"qty":qty,"entry":px,"cost":cost,"entry_ts":ts}
    if sym not in a["symbols_used"]: a["symbols_used"].append(sym)

def sell(a,sym,close,ts):
    pos=a["positions"].pop(sym); px=close*(D(1)-SLIP)
    gross=pos["qty"]*px; fee=gross*FEE; net=gross-fee; pnl=net-pos["cost"]
    reserve=max(D(0),pnl*RESERVE_RATE)
    a["cash"]+=net-reserve; a["reserve"]+=reserve; a["fees"]+=fee
    a["sells"]+=1; a["last_exit"][sym]=ts
    if pnl>0:a["wins"]+=1

def run_window(start_day,bars_by_pair,p,strategy):
    start=datetime.combine(start_day,datetime.min.time(),tzinfo=timezone.utc)
    end=start+timedelta(days=7); start_ms=int(start.timestamp()*1000); end_ms=int(end.timestamp()*1000)
    warm_ms=int((start-timedelta(days=7)).timestamp()*1000)
    histories={s:[] for s in bars_by_pair}; by_ts=defaultdict(dict)
    for sym,bars in bars_by_pair.items():
        for b in bars:
            if warm_ms<=b[0]<end_ms:by_ts[b[0]][sym]=b
    a=new_account(); prices={}
    for ts in sorted(by_ts):
        row=by_ts[ts]
        for sym,b in row.items():
            histories[sym].append(b); histories[sym]=histories[sym][-30:]; prices[sym]=b[4]
        if ts<start_ms:continue
        for sym in list(a["positions"]):
            if sym not in row:continue
            cur=row[sym][4]; pos=a["positions"][sym]
            held=max(0,int((ts-pos["entry_ts"])/(4*60*60*1000)))
            if cur<=pos["entry"]*(D(1)-p["stop"]) or cur>=pos["entry"]*(D(1)+p["take"]) or held>=p["max_hold"]:
                sell(a,sym,cur,ts)
        if not a["positions"]:
            candidates=[]
            for sym,b in row.items():
                if signal(strategy,histories[sym],p)=="buy":
                    h=histories[sym]
                    score=abs(h[-1][4]/h[-2][4]-D(1))
                    candidates.append((score,sym,b[4]))
            if candidates:
                _,sym,close=max(candidates)
                buy(a,sym,close,ts,p)
        eq=equity(a,prices); a["peak"]=max(a["peak"],eq)
        if a["peak"]>0:a["max_dd"]=max(a["max_dd"],(a["peak"]-eq)/a["peak"])
    last_ts=max(by_ts) if by_ts else end_ms
    for sym in list(a["positions"]):sell(a,sym,prices[sym],last_ts)
    final=a["cash"]+a["reserve"]
    return {"final_yen":float(final),"return_pct":float((final/START-D(1))*100),
            "closed_trades":a["sells"],"wins":a["wins"],"fees_yen":float(a["fees"]),
            "max_drawdown_pct":float(a["max_dd"]*100),"hit_200k":final>=TARGET,
            "symbols_used":sorted(a["symbols_used"])}

def main():
    now=datetime.now(timezone.utc); end_day=(now-timedelta(days=1)).date()
    pairs=discover_pairs()
    bars={}
    year=str(end_day.year)
    for pair in pairs:
        rows=fetch_year(pair,year)
        if rows:bars[pair]=rows

    starts=[end_day-timedelta(days=55-7*i) for i in range(8)]
    labels=[f"{s.isoformat()}..{(s+timedelta(days=6)).isoformat()}" for s in starts]
    search_ids=(0,1,2,3); validation_ids=(4,5,6,7)
    candidates=[]; best=None; target_hits=0
    for name,p in PROFILES.items():
        for strategy in STRATEGIES:
            wr=[run_window(s,bars,p,strategy) for s in starts]
            target_hits+=sum(int(r["hit_200k"]) for r in wr)
            for i,r in enumerate(wr):
                item={"profile":name,"strategy":strategy,"window":labels[i],**r}
                if best is None or r["final_yen"]>best["final_yen"]:best=item
            vals=[wr[i]["return_pct"] for i in validation_ids]
            candidates.append({
              "profile":name,"strategy":strategy,
              "settings":{"fraction":str(p["fraction"]),"take_profit":str(p["take"]),
                          "stop_loss":str(p["stop"]),"cooldown_bars":p["cooldown"],"max_hold_bars":p["max_hold"]},
              "search_avg_return_pct":round(statistics.mean(wr[i]["return_pct"] for i in search_ids),3),
              "validation_avg_return_pct":round(statistics.mean(vals),3),
              "validation_median_return_pct":round(statistics.median(vals),3),
              "validation_worst_return_pct":round(min(vals),3),
              "validation_best_return_pct":round(max(vals),3),
              "validation_target_hits":sum(int(wr[i]["hit_200k"]) for i in validation_ids),
              "validation_windows":[wr[i] for i in validation_ids]
            })
    ranked=sorted(candidates,key=lambda x:(x["validation_target_hits"],x["validation_median_return_pct"],x["validation_worst_return_pct"]),reverse=True)
    result={
      "paper_only":True,"stage":"expanded_universe_4hour_discovery",
      "goal":{"start_yen":10000,"target_yen":200000,"days":7},
      "constraints":{"spot_only":True,"leverage":False,"borrowing":False},
      "pairs_discovered":len(pairs),"pairs_with_4hour_history":len(bars),
      "pair_names":sorted(bars),"windows":labels,
      "profiles_tested":len(PROFILES),"candidate_strategy_combinations":len(candidates),
      "total_7day_runs":len(candidates)*8,"target_hits_all_runs":target_hits,
      "best_single_7day_run":best,"top_validation_candidates":ranked[:10],
      "historical_spread_available":False,
      "modeled_costs":{"fee_each_side":str(FEE),"slippage_each_side":str(SLIP)}
    }
    print(json.dumps(result,ensure_ascii=False))
    Path("historical-backtest-results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
