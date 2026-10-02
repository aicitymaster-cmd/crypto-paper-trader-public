"""One-shot cross-asset 7-day comparison for the user's fixed objective.

Goal: JPY 10,000 -> JPY 50,000, stop immediately on first touch, max horizon 7 days.
Quantitative models:
- KO-like normalized model on GOLD/SILVER/OIL/NASDAQ/NIKKEI/VIX proxies
- Regulated leverage caps for USDJPY FX (25x) and BTC (2x)
- Option categories are NOT assigned fabricated option prices; instead report the
  frequency of large underlying moves as an opportunity proxy only.

Historical research only. Not a future probability or trading recommendation.
"""
from __future__ import annotations
import json, ssl, urllib.request, urllib.parse, math
from datetime import datetime, timezone, timedelta
from bisect import bisect_left
from statistics import median
from cross_market_backtest import Bar

START=10_000.0
TARGET=50_000.0
RANGE="2y"; INTERVAL="1h"
FAST=6; SLOW=18
USDJPY_REF=158.2
KO_PCT=0.0075
KO_PREMIUM=0.5
SPREAD=0.6

SYMBOLS={
 "gold_ko":"GC=F",
 "silver_ko":"SI=F",
 "oil_ko":"CL=F",
 "nasdaq_ko":"NQ=F",
 "nikkei_ko":"^N225",
 "vix_ko":"^VIX",
 "fx_usdjpy":"JPY=X",
 "btc_2x":"BTC-USD",
 "nikkei_option_proxy":"^N225",
}

def fetch_symbol(symbol):
    sym=urllib.parse.quote(symbol,safe="")
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={RANGE}&interval={INTERVAL}&includePrePost=false&events=div%2Csplits"
    req=urllib.request.Request(url,headers={"User-Agent":"aicity-paper-research/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=25,context=ssl.create_default_context()) as r:
        body=r.read(15_000_001)
    if len(body)>15_000_000: raise RuntimeError("BODY_TOO_LARGE")
    p=json.loads(body); res=((p.get("chart") or {}).get("result") or [])[0]
    ts=res.get("timestamp") or []; q=((res.get("indicators") or {}).get("quote") or [{}])[0]
    out=[]
    for i,t in enumerate(ts):
        vals=[q.get(k,[None]*len(ts))[i] for k in ("open","high","low","close")]
        if any(v is None for v in vals): continue
        o,h,l,c=map(float,vals)
        if min(o,h,l,c)<=0: continue
        out.append(Bar(datetime.fromtimestamp(int(t),tz=timezone.utc),c,o,h,l))
    return out

def sma(vals,n): return sum(vals[-n:])/n

def windows(bars):
    if not bars:return []
    out=[]; cursor=bars[0].ts; end=bars[-1].ts
    while cursor+timedelta(days=7)<=end:
        stop=cursor+timedelta(days=7)
        chunk=[b for b in bars if cursor<=b.ts<stop]
        if len(chunk)>SLOW: out.append(chunk)
        cursor=stop
    return out

def hit_day(ts0,ts):
    return max(1,min(7,math.ceil((ts-ts0).total_seconds()/86400)))

def ko_window(chunk):
    eq=START; i=SLOW; touched=None; ruined=False
    while i<len(chunk)-1 and eq>0 and touched is None:
        closes=[b.close for b in chunk[:i+1]]
        sig=1 if sma(closes,FAST)>sma(closes,SLOW) else -1
        e=chunk[i]; entry=e.close; ko=entry*KO_PCT
        option_points=ko+KO_PREMIUM+SPREAD/2
        lots=(eq/USDJPY_REF)/option_points
        if lots<=0: break
        j=i+1
        while j<len(chunk):
            b=chunk[j]; _,h,l,c=b.ohlc()
            adverse=(entry-l) if sig==1 else (h-entry)
            favorable=(h-entry) if sig==1 else (entry-l)
            if adverse>=ko:
                eq=0; ruined=True; i=j+1; break
            if eq+favorable*lots*USDJPY_REF>=TARGET:
                eq=TARGET; touched=hit_day(chunk[0].ts,b.ts); break
            closes2=[x.close for x in chunk[:j+1]]
            sig2=1 if sma(closes2,FAST)>sma(closes2,SLOW) else -1
            if sig2!=sig:
                move=(c-entry) if sig==1 else (entry-c)
                eq=max(0,eq+move*lots*USDJPY_REF); i=j+1; break
            j+=1
        else:
            b=chunk[-1]; move=(b.close-entry) if sig==1 else (entry-b.close)
            eq=max(0,eq+move*lots*USDJPY_REF); i=len(chunk)
    return touched,ruined,eq

def leverage_window(chunk,lev):
    eq=START; i=SLOW; touched=None; ruined=False
    while i<len(chunk)-1 and eq>0 and touched is None:
        closes=[b.close for b in chunk[:i+1]]
        sig=1 if sma(closes,FAST)>sma(closes,SLOW) else -1
        e=chunk[i]; entry=e.close; j=i+1
        while j<len(chunk):
            b=chunk[j]; _,h,l,c=b.ohlc()
            favorable=((h/entry)-1) if sig==1 else ((entry/l)-1)
            adverse=((l/entry)-1) if sig==1 else ((entry/h)-1)
            if eq*(1+adverse*lev)<=0:
                eq=0; ruined=True; i=j+1; break
            if eq*(1+favorable*lev)>=TARGET:
                eq=TARGET; touched=hit_day(chunk[0].ts,b.ts); break
            closes2=[x.close for x in chunk[:j+1]]
            sig2=1 if sma(closes2,FAST)>sma(closes2,SLOW) else -1
            if sig2!=sig:
                raw=(c/entry-1) if sig==1 else (entry/c-1)
                eq=max(0,eq*(1+raw*lev)); i=j+1; break
            j+=1
        else:
            c=chunk[-1].close; raw=(c/entry-1) if sig==1 else (entry/c-1)
            eq=max(0,eq*(1+raw*lev)); i=len(chunk)
    return touched,ruined,eq

def summarize(rows):
    n=len(rows); hitdays=[d for d,r,e in rows if d is not None]
    def rate(k): return round(100*sum(d is not None and d<=k for d,_,_ in rows)/n,2) if n else 0
    return {
      "windows":n,
      "hit_1d_pct":rate(1),"hit_3d_pct":rate(3),"hit_5d_pct":rate(5),"hit_7d_pct":rate(7),
      "ruin_pct":round(100*sum(r for _,r,_ in rows)/n,2) if n else 0,
      "median_hit_day":median(hitdays) if hitdays else None,
      "median_final_jpy":round(median([e for _,_,e in rows]),2) if n else None,
    }

def option_opportunity_proxy(chunk):
    start=chunk[0].close
    max_up=max(b.high for b in chunk)/start-1
    max_dn=1-min(b.low for b in chunk)/start
    m=max(max_up,max_dn)
    # Report underlying move opportunity only; no assumed option premium/payoff.
    return m

def main():
    data={k:fetch_symbol(v) for k,v in SYMBOLS.items()}
    out={}
    for k in ("gold_ko","silver_ko","oil_ko","nasdaq_ko","nikkei_ko","vix_ko"):
        out[k]=summarize([ko_window(w) for w in windows(data[k])])
    out["fx_usdjpy_25x"]=summarize([leverage_window(w,25.0) for w in windows(data["fx_usdjpy"])])
    out["btc_2x"]=summarize([leverage_window(w,2.0) for w in windows(data["btc_2x"])])
    op=[]
    for w in windows(data["nikkei_option_proxy"]):
        op.append(option_opportunity_proxy(w))
    out["nikkei_mini_option_opportunity_proxy"]={
      "windows":len(op),
      "underlying_move_ge_2pct":round(100*sum(x>=0.02 for x in op)/len(op),2) if op else 0,
      "underlying_move_ge_3pct":round(100*sum(x>=0.03 for x in op)/len(op),2) if op else 0,
      "underlying_move_ge_5pct":round(100*sum(x>=0.05 for x in op)/len(op),2) if op else 0,
      "note":"Underlying opportunity frequency only; no fabricated option premium or 5x-return probability."
    }
    print(json.dumps({
      "objective":"JPY10000 to JPY50000; stop on first touch; maximum 7 days",
      "paper_only":True,
      "normalized_ko_assumption":{"ko_pct":KO_PCT,"premium_points":KO_PREMIUM,"spread_points":SPREAD},
      "results":out,
      "limitations":[
        "KO proxy uses Yahoo underlying OHLC, fixed USDJPY reference and normalized KO parameters; not broker quotes.",
        "FX/BTC use simple regulated leverage-cap models and omit financing/slippage.",
        "Nikkei mini option is opportunity proxy only because reliable historical option-chain pricing was not reconstructed.",
        "Observed historical rates are not future probabilities."
      ]
    },ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
