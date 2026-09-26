"""Historical 5-minute PAPER strategy search on bitbank public candles.

No credentials, no account access, no live orders.
Historical OHLCV does not contain historical bid/ask spread, so fills model the
configured fee and slippage but not the unavailable historical spread.
"""
from __future__ import annotations
import json, math, ssl, time, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path

CFG=json.loads(Path(__file__).with_name("paper_campaign_v2.json").read_text())
RISK=CFG["common_risk"]; SLOW=CFG["slow_5m"]
ASSETS={"BTC":"btc_jpy","ETH":"eth_jpy","SOL":"sol_jpy","XRP":"xrp_jpy","DOGE":"doge_jpy"}
STRATEGIES=("momentum","breakout","mean_reversion")
START=D(CFG["initial_state"]["cash_yen_per_strategy"])
FEE=D(RISK["fee_rate_each_side"]); SLIP=D(RISK["slippage_rate_each_side"])
RESERVE_RATE=D(RISK["reserve_rate"])
UA="crypto-paper-historical-search/1.0"

PROFILES={
  "baseline":{
    "fraction":D("0.25"),"max_pos":2,"stop":D("0.012"),"take":D("0.018"),
    "max_hold":36,"cooldown":0,"exit_signal":True,
    "mom_lookback":4,"mom_min":D("0"),"break_buffer":D("0"),
    "mean_z":D("-1.5"),"mean_trend":D("0.985")
  },
  "conservative":{
    "fraction":D("0.15"),"max_pos":1,"stop":D("0.015"),"take":D("0.030"),
    "max_hold":72,"cooldown":12,"exit_signal":False,
    "mom_lookback":12,"mom_min":D("0.004"),"break_buffer":D("0.002"),
    "mean_z":D("-2.2"),"mean_trend":D("0.995")
  },
  "strict":{
    "fraction":D("0.12"),"max_pos":1,"stop":D("0.012"),"take":D("0.030"),
    "max_hold":72,"cooldown":24,"exit_signal":False,
    "mom_lookback":12,"mom_min":D("0.006"),"break_buffer":D("0.003"),
    "mean_z":D("-2.5"),"mean_trend":D("1.000")
  },
  "very_strict":{
    "fraction":D("0.10"),"max_pos":1,"stop":D("0.010"),"take":D("0.035"),
    "max_hold":96,"cooldown":36,"exit_signal":False,
    "mom_lookback":18,"mom_min":D("0.008"),"break_buffer":D("0.005"),
    "mean_z":D("-2.8"),"mean_trend":D("1.000")
  },
  "balanced":{
    "fraction":D("0.12"),"max_pos":1,"stop":D("0.012"),"take":D("0.025"),
    "max_hold":60,"cooldown":18,"exit_signal":False,
    "mom_lookback":12,"mom_min":D("0.005"),"break_buffer":D("0.0025"),
    "mean_z":D("-2.3"),"mean_trend":D("0.998")
  }
}

def get_json(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
    ctx=ssl.create_default_context()
    with urllib.request.urlopen(req,timeout=15,context=ctx) as r: obj=json.loads(r.read())
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
        momentum=(c/closes[-lb])-D(1)
        return "buy" if c>s12>s36 and momentum>=p["mom_min"] else "sell" if c<s12 else "skip"
    if strategy=="breakout":
        prior=max(highs[-21:-1])
        return "buy" if c>prior*(D(1)+p["break_buffer"]) else "sell" if c<sma(closes,12) else "skip"
    zz=zscore(closes,20); trend=sma(closes,20)>=sma(closes,50)*p["mean_trend"]
    return "buy" if zz<=p["mean_z"] and trend else "sell" if zz>=0 else "skip"

def new_account():
    return {"cash":START,"reserve":D(0),"positions":{},"sells":0,"wins":0,"fees":D(0),
            "max_dd":D(0),"peak":START,"last_exit":{}}

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

def run(days,bars_by_asset,end_day,p):
    start=datetime.combine(end_day-timedelta(days=days-1),datetime.min.time(),tzinfo=timezone.utc)
    end=start+timedelta(days=days); start_ms=int(start.timestamp()*1000); end_ms=int(end.timestamp()*1000)
    histories={s:[] for s in ASSETS}; by_ts=defaultdict(dict)
    for sym,bars in bars_by_asset.items():
        for b in bars:
            if b[0]<end_ms:by_ts[b[0]][sym]=b
    accounts={s:new_account() for s in STRATEGIES}; prices={}
    for ts in sorted(by_ts):
        row=by_ts[ts]
        for sym,b in row.items():
            histories[sym].append(b); histories[sym]=histories[sym][-120:]; prices[sym]=b[4]
        if ts<start_ms:continue
        for strategy,a in accounts.items():
            for sym in list(a["positions"]):
                if sym not in row:continue
                cur=row[sym][4]; pos=a["positions"][sym]
                held=max(0,int((ts-pos["entry_ts"])/(5*60*1000))); sig=signal(strategy,histories[sym],p)
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
    for a in accounts.values():
        for sym in list(a["positions"]):sell(a,sym,prices[sym],last_ts)
    out={}
    for strategy,a in accounts.items():
        final=a["cash"]+a["reserve"]; pnl=final-START
        out[strategy]={
          "final_yen":str(final.quantize(D("0.01"))),
          "pnl_yen":str(pnl.quantize(D("0.01"))),
          "return_pct":str((pnl/START*100).quantize(D("0.001"))),
          "closed_trades":a["sells"],"wins":a["wins"],
          "win_rate_pct":str((D(a["wins"])/D(a["sells"])*100).quantize(D("0.1"))) if a["sells"] else "0.0",
          "fees_yen":str(a["fees"].quantize(D("0.01"))),
          "max_drawdown_pct":str((a["max_dd"]*100).quantize(D("0.001")))
        }
    return out

def main():
    end_day=(datetime.now(timezone.utc)-timedelta(days=1)).date()
    first=end_day-timedelta(days=30)
    bars={s:[] for s in ASSETS}; d=first
    while d<=end_day:
        for sym,pair in ASSETS.items():
            bars[sym].extend(fetch_day(pair,d)); time.sleep(0.05)
        d+=timedelta(days=1)
    results={}
    for name,p in PROFILES.items():
        results[name]={str(n):run(n,bars,end_day,p) for n in (3,10,30)}
    result={
      "paper_only":True,"data_source":"bitbank public 5min OHLCV","end_day_utc":str(end_day),
      "historical_spread_available":False,
      "modeled_costs":{"fee_each_side":str(FEE),"slippage_each_side":str(SLIP)},
      "profiles":results
    }
    print(json.dumps(result,ensure_ascii=False))
    Path("historical-backtest-results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
