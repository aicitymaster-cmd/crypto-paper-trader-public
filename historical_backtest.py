"""Historical 5-minute PAPER backtest using bitbank public candles only.

No credentials, no account access, no live orders.
Historical OHLCV does not contain historical bid/ask spread, so fills model the
configured slippage and fees but not the unavailable historical spread.
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
STRATEGIES=tuple(v["name"] for v in SLOW["strategies"].values())
START=D(CFG["initial_state"]["cash_yen_per_strategy"])
FEE=D(RISK["fee_rate_each_side"]); SLIP=D(RISK["slippage_rate_each_side"])
FRACTION=D(SLOW["trade_fraction"]); RESERVE_RATE=D(RISK["reserve_rate"])
MAX_POS=int(RISK["max_positions"]); STOP=D(SLOW["stop_loss"])
TAKE=D(SLOW["take_profit"]); MAX_HOLD=int(SLOW["max_hold_bars"])
MIN_NET=D(RISK["minimum_projected_net_return"])
UA="crypto-paper-historical-backtest/1.0"

def get_json(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
    ctx=ssl.create_default_context()
    with urllib.request.urlopen(req,timeout=15,context=ctx) as r:
        obj=json.loads(r.read())
    if obj.get("success")!=1: raise RuntimeError(f"API_FAILED:{url}")
    return obj["data"]

def fetch_day(pair,day):
    data=get_json(f"https://public.bitbank.cc/{pair}/candlestick/5min/{day:%Y%m%d}")
    rows=data["candlestick"][0]["ohlcv"]
    out=[]
    for o,h,l,c,v,ts in rows:
        out.append((int(ts),D(o),D(h),D(l),D(c),D(v)))
    return out

def sma(xs,n): return sum(xs[-n:],D(0))/D(n)

def zscore(xs,n):
    vals=[float(x) for x in xs[-n:]]; mean=sum(vals)/n
    sd=math.sqrt(sum((x-mean)**2 for x in vals)/n)
    return D("0") if sd==0 else D(str((vals[-1]-mean)/sd))

def signal(strategy,bars):
    if len(bars)<60: return "skip"
    closes=[b[4] for b in bars]; highs=[b[2] for b in bars]; c=closes[-1]
    if strategy=="momentum":
        s12,s36=sma(closes,12),sma(closes,36)
        return "buy" if c>s12>s36 and c>closes[-4] else "sell" if c<s12 else "skip"
    if strategy=="breakout":
        return "buy" if c>max(highs[-21:-1]) else "sell" if c<sma(closes,12) else "skip"
    z=zscore(closes,20); trend=sma(closes,20)>=sma(closes,50)*D("0.985")
    return "buy" if z<=D("-1.5") and trend else "sell" if z>=0 else "skip"

def projected_net():
    buy=D(1)+SLIP
    entry=buy*(D(1)+FEE)
    exit_px=(D(1)+TAKE)*(D(1)-SLIP)
    exit_net=exit_px*(D(1)-FEE)
    return exit_net/entry-D(1)

def new_account():
    return {"cash":START,"reserve":D(0),"positions":{},"sells":0,"wins":0,"fees":D(0),"max_dd":D(0),"peak":START}

def equity(a,prices):
    return a["cash"]+a["reserve"]+sum(p["qty"]*prices[s] for s,p in a["positions"].items() if s in prices)

def buy(a,sym,close,ts):
    if sym in a["positions"] or len(a["positions"])>=MAX_POS or projected_net()<MIN_NET:return
    px=close*(D(1)+SLIP); budget=a["cash"]*FRACTION
    qty=(budget/(px*(D(1)+FEE))).quantize(D("0.00000001"),rounding=ROUND_DOWN)
    if qty<=0:return
    gross=qty*px; fee=gross*FEE; cost=gross+fee
    if cost>a["cash"]:return
    a["cash"]-=cost; a["fees"]+=fee
    a["positions"][sym]={"qty":qty,"entry":px,"cost":cost,"entry_ts":ts}

def sell(a,sym,close):
    p=a["positions"].pop(sym); px=close*(D(1)-SLIP)
    gross=p["qty"]*px; fee=gross*FEE; net=gross-fee; pnl=net-p["cost"]
    reserve=max(D(0),pnl*RESERVE_RATE)
    a["cash"]+=net-reserve; a["reserve"]+=reserve; a["fees"]+=fee
    a["sells"]+=1
    if pnl>0:a["wins"]+=1

def run(days,bars_by_asset,end_day):
    start=datetime.combine(end_day-timedelta(days=days-1),datetime.min.time(),tzinfo=timezone.utc)
    end=start+timedelta(days=days)
    start_ms=int(start.timestamp()*1000); end_ms=int(end.timestamp()*1000)
    histories={s:[] for s in ASSETS}; by_ts=defaultdict(dict)
    for sym,bars in bars_by_asset.items():
        for b in bars:
            if b[0]<end_ms: by_ts[b[0]][sym]=b
    accounts={s:new_account() for s in STRATEGIES}; prices={}
    for ts in sorted(by_ts):
        row=by_ts[ts]
        for sym,b in row.items():
            histories[sym].append(b); histories[sym]=histories[sym][-120:]
            prices[sym]=b[4]
        if ts<start_ms: continue
        for strategy,a in accounts.items():
            for sym in list(a["positions"]):
                if sym not in row: continue
                b=row[sym]; cur=b[4]; p=a["positions"][sym]
                held=max(0,int((ts-p["entry_ts"])/(5*60*1000)))
                sig=signal(strategy,histories[sym]); reason=False
                if cur<=p["entry"]*(D(1)-STOP):reason=True
                elif cur>=p["entry"]*(D(1)+TAKE):reason=True
                elif held>=MAX_HOLD:reason=True
                elif sig=="sell":reason=True
                if reason:sell(a,sym,cur)
            candidates=[]
            for sym,b in row.items():
                if sym in a["positions"]:continue
                if signal(strategy,histories[sym])=="buy":
                    h=histories[sym]; score=abs(h[-1][4]/h[-4][4]-D(1)); candidates.append((score,sym,b[4]))
            for _,sym,close in sorted(candidates,reverse=True):
                if len(a["positions"])>=MAX_POS:break
                buy(a,sym,close,ts)
            eq=equity(a,prices); a["peak"]=max(a["peak"],eq)
            if a["peak"]>0:a["max_dd"]=max(a["max_dd"],(a["peak"]-eq)/a["peak"])
    # force liquidation at the last known close within the period
    for a in accounts.values():
        for sym in list(a["positions"]):
            sell(a,sym,prices[sym])
    out={}
    for strategy,a in accounts.items():
        final=a["cash"]+a["reserve"]; pnl=final-START
        out[strategy]={
            "final_yen":str(final.quantize(D("0.01"))),
            "pnl_yen":str(pnl.quantize(D("0.01"))),
            "return_pct":str((pnl/START*100).quantize(D("0.001"))),
            "closed_trades":a["sells"],
            "wins":a["wins"],
            "win_rate_pct":str((D(a["wins"])/D(a["sells"])*100).quantize(D("0.1"))) if a["sells"] else "0.0",
            "fees_yen":str(a["fees"].quantize(D("0.01"))),
            "max_drawdown_pct":str((a["max_dd"]*100).quantize(D("0.001"))),
            "open_positions":0,
        }
    return out

def main():
    end_day=(datetime.now(timezone.utc)-timedelta(days=1)).date()
    first=end_day-timedelta(days=30)  # one warm-up day before 30-day window
    bars={s:[] for s in ASSETS}
    d=first
    while d<=end_day:
        for sym,pair in ASSETS.items():
            bars[sym].extend(fetch_day(pair,d))
            time.sleep(0.08)
        d+=timedelta(days=1)
    result={
        "paper_only":True,
        "data_source":"bitbank public 5min OHLCV",
        "end_day_utc":str(end_day),
        "historical_spread_available":False,
        "modeled_costs":{"fee_each_side":str(FEE),"slippage_each_side":str(SLIP)},
        "periods":{str(n):run(n,bars,end_day) for n in (3,10,30)}
    }
    print(json.dumps(result,ensure_ascii=False))
    Path("historical-backtest-results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
