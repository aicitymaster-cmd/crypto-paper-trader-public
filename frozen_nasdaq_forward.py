"""Frozen NASDAQ forward paper check.

Frozen rules:
- Starting capital JPY 10,000
- Reserve JPY 2,000; risk sleeve JPY 8,000
- Target JPY 30,000 within 7 days
- NASDAQ proxy: NQ=F hourly bars
- KO distance: 1.25%
- 4-hour breakout, ATR add-on 0
- Stages: 15,000 -> 20,000 -> 30,000
- PAPER ONLY. No live order placement.
"""
from __future__ import annotations
import json, ssl, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from cross_market_backtest import Bar

START=10_000.0
RESERVE=2_000.0
TARGET=30_000.0
KO_PCT=0.0125
LOOKBACK=4
STAGES=(15_000.0,20_000.0,30_000.0)
SYMBOL="NQ=F"
USDJPY_REF=158.2
KO_PREMIUM=0.5
SPREAD=0.6

def fetch(range_="10d", interval="1h"):
    sym=urllib.parse.quote(SYMBOL,safe="")
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={range_}&interval={interval}&includePrePost=false&events=div%2Csplits"
    req=urllib.request.Request(url,headers={"User-Agent":"aicity-paper-research/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=25,context=ssl.create_default_context()) as r:
        p=json.loads(r.read())
    res=((p.get("chart") or {}).get("result") or [])[0]
    ts=res.get("timestamp") or []; q=((res.get("indicators") or {}).get("quote") or [{}])[0]
    out=[]
    for i,t in enumerate(ts):
        vals=[q.get(k,[None]*len(ts))[i] for k in ("open","high","low","close")]
        if any(v is None for v in vals): continue
        o,h,l,c=map(float,vals)
        if min(o,h,l,c)<=0: continue
        out.append(Bar(datetime.fromtimestamp(int(t),tz=timezone.utc),c,o,h,l))
    return out

def latest_signal(bars):
    if len(bars)<LOOKBACK+1:
        return {"status":"INSUFFICIENT_DATA"}
    now=datetime.now(timezone.utc)
    complete=[b for b in bars if b.ts+timedelta(hours=1)<=now]
    if len(complete)<LOOKBACK+1:
        return {"status":"INSUFFICIENT_COMPLETE_BARS"}
    i=len(complete)-1
    hist=complete[i-LOOKBACK:i]
    cur=complete[i]
    hh=max(b.high for b in hist)
    ll=min(b.low for b in hist)
    if cur.close>hh:
        direction="LONG"
    elif cur.close<ll:
        direction="SHORT"
    else:
        direction="NO_TRADE"
    if direction=="LONG":
        ko_level=cur.close*(1-KO_PCT)
    elif direction=="SHORT":
        ko_level=cur.close*(1+KO_PCT)
    else:
        ko_level=None
    return {
      "status":"ELIGIBLE" if direction!="NO_TRADE" else "NOT_ELIGIBLE",
      "symbol":SYMBOL,
      "bar_utc":cur.ts.isoformat(),
      "reference_price":round(cur.close,4),
      "breakout_high_4h":round(hh,4),
      "breakout_low_4h":round(ll,4),
      "direction":direction,
      "ko_pct":KO_PCT,
      "approx_ko_level":round(ko_level,4) if ko_level else None,
      "reserve_jpy":RESERVE,
      "risk_sleeve_jpy":START-RESERVE,
      "stages_jpy":list(STAGES),
      "target_jpy":TARGET,
      "paper_only":True
    }

if __name__=="__main__":
    print(json.dumps(latest_signal(fetch()),ensure_ascii=False,sort_keys=True))
