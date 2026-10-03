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
TARGETS=(30_000.0,50_000.0)
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
 "sp500_ko":"ES=F",
 "russell2000_ko":"RTY=F",
 "tesla_ko_proxy":"TSLA",
 "nvidia_ko_proxy":"NVDA",
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

def ko_window(chunk,target):
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
            if eq+favorable*lots*USDJPY_REF>=target:
                eq=target; touched=hit_day(chunk[0].ts,b.ts); break
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

def leverage_window(chunk,lev,target):
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
            if eq*(1+favorable*lev)>=target:
                eq=target; touched=hit_day(chunk[0].ts,b.ts); break
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
    return {
      "windows":n,
      "hit_7d_pct":round(100*sum(d is not None for d,_,_ in rows)/n,2) if n else 0,
      "ruin_pct":round(100*sum(r for _,r,_ in rows)/n,2) if n else 0,
      "median_hit_day":median(hitdays) if hitdays else None,
      "median_final_jpy":round(median([e for _,_,e in rows]),2) if n else None,
    }



def ko_window_distance(chunk, target, ko_pct, reserve_jpy=2000.0):
    """Reserve-cash KO model with variable KO distance."""
    risk_start=START-reserve_jpy
    if risk_start<=0 or reserve_jpy<0 or target<=reserve_jpy:
        raise ValueError("invalid reserve")
    eq=risk_start; i=SLOW; touched=None; ruined=False
    needed=target-reserve_jpy
    while i<len(chunk)-1 and eq>0 and touched is None:
        closes=[b.close for b in chunk[:i+1]]
        sig=1 if sma(closes,FAST)>sma(closes,SLOW) else -1
        e=chunk[i]; entry=e.close; ko=entry*ko_pct
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
            if eq+favorable*lots*USDJPY_REF>=needed:
                eq=needed; touched=hit_day(chunk[0].ts,b.ts); break
            closes2=[x.close for x in chunk[:j+1]]
            sig2=1 if sma(closes2,FAST)>sma(closes2,SLOW) else -1
            if sig2!=sig:
                move=(c-entry) if sig==1 else (entry-c)
                eq=max(0,eq+move*lots*USDJPY_REF); i=j+1; break
            j+=1
        else:
            b=chunk[-1]; move=(b.close-entry) if sig==1 else (entry-b.close)
            eq=max(0,eq+move*lots*USDJPY_REF); i=len(chunk)
    total=reserve_jpy+eq
    return touched, (total<=0), total, ruined

def ko_window_reserve(chunk, target, reserve_jpy):
    """Keep reserve cash untouched. Risk sleeve alone follows the KO model."""
    risk_start=START-reserve_jpy
    if risk_start<=0 or reserve_jpy<0 or target<=reserve_jpy:
        raise ValueError("invalid reserve")
    eq=risk_start; i=SLOW; touched=None; ruined=False
    needed=target-reserve_jpy
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
            if eq+favorable*lots*USDJPY_REF>=needed:
                eq=needed; touched=hit_day(chunk[0].ts,b.ts); break
            closes2=[x.close for x in chunk[:j+1]]
            sig2=1 if sma(closes2,FAST)>sma(closes2,SLOW) else -1
            if sig2!=sig:
                move=(c-entry) if sig==1 else (entry-c)
                eq=max(0,eq+move*lots*USDJPY_REF); i=j+1; break
            j+=1
        else:
            b=chunk[-1]; move=(b.close-entry) if sig==1 else (entry-b.close)
            eq=max(0,eq+move*lots*USDJPY_REF); i=len(chunk)
    total=reserve_jpy+eq
    return touched, (total<=0), total, ruined

def summarize_reserve(rows):
    n=len(rows); hitdays=[d for d,zero,total,koed in rows if d is not None]
    return {
      "windows":n,
      "hit_7d_pct":round(100*sum(d is not None for d,_,_,_ in rows)/n,2) if n else 0,
      "account_zero_pct":round(100*sum(zero for _,zero,_,_ in rows)/n,2) if n else 0,
      "risk_sleeve_ko_pct":round(100*sum(koed for _,_,_,koed in rows)/n,2) if n else 0,
      "median_hit_day":median(hitdays) if hitdays else None,
      "median_final_jpy":round(median([total for _,_,total,_ in rows]),2) if n else None,
    }


def staged_ko_window(chunk, ko_pct, reserve_jpy=2000.0, stages=(15000.0,20000.0,30000.0)):
    """Stage profits: total-account targets are hit sequentially and risk sleeve is resized."""
    reserve=float(reserve_jpy)
    risk=max(0.0, START-reserve)
    stage_idx=0
    i=SLOW
    touched=None
    ever_ko=False
    while i<len(chunk)-1 and risk>0 and stage_idx<len(stages):
        total=reserve+risk
        stage_target=stages[stage_idx]
        if total>=stage_target:
            stage_idx+=1
            if stage_idx>=len(stages):
                touched=hit_day(chunk[0].ts,chunk[i].ts)
                break
            continue
        closes=[b.close for b in chunk[:i+1]]
        sig=1 if sma(closes,FAST)>sma(closes,SLOW) else -1
        entry=chunk[i].close
        ko=entry*ko_pct
        option_points=ko+KO_PREMIUM+SPREAD/2
        lots=(risk/USDJPY_REF)/option_points
        if lots<=0: break
        j=i+1
        while j<len(chunk):
            b=chunk[j]; _,h,l,c=b.ohlc()
            adverse=(entry-l) if sig==1 else (h-entry)
            favorable=(h-entry) if sig==1 else (entry-l)
            if adverse>=ko:
                risk=0.0; ever_ko=True; i=j+1; break
            stage_needed=stage_target-reserve
            if risk+favorable*lots*USDJPY_REF>=stage_needed:
                risk=stage_needed
                stage_idx+=1
                i=j+1
                if stage_idx>=len(stages):
                    touched=hit_day(chunk[0].ts,b.ts)
                break
            closes2=[x.close for x in chunk[:j+1]]
            sig2=1 if sma(closes2,FAST)>sma(closes2,SLOW) else -1
            if sig2!=sig:
                move=(c-entry) if sig==1 else (entry-c)
                risk=max(0.0,risk+move*lots*USDJPY_REF)
                i=j+1
                break
            j+=1
        else:
            b=chunk[-1]
            move=(b.close-entry) if sig==1 else (entry-b.close)
            risk=max(0.0,risk+move*lots*USDJPY_REF)
            i=len(chunk)
    return touched, reserve+risk, ever_ko

def summarize_staged(rows):
    n=len(rows); hitdays=[d for d,total,koed in rows if d is not None]
    return {
      "windows":n,
      "hit_7d_pct":round(100*sum(d is not None for d,_,_ in rows)/n,2) if n else 0,
      "ko_pct":round(100*sum(koed for _,_,koed in rows)/n,2) if n else 0,
      "median_hit_day":median(hitdays) if hitdays else None,
      "median_final_jpy":round(median([total for _,total,_ in rows]),2) if n else None,
    }


def split_staged_window(chunk_a, chunk_b, weight_a=0.5, reserve_jpy=2000.0,
                        target=30000.0, ko_a=0.015, ko_b=0.0125):
    """Approximate concurrent split between NASDAQ and S&P500 sleeves.
    Each sleeve is simulated independently with staged logic, then combined by proportional P/L.
    """
    invest=START-reserve_jpy
    alloc_a=invest*weight_a
    alloc_b=invest*(1-weight_a)
    def sleeve(chunk, alloc, ko_pct):
        if alloc<=0: return {"hit":None,"final":0.0,"ko":False}
        base_start=START
        # scale the existing staged model from 8k risk sleeve to this allocation.
        # Equivalent total-account stages are scaled around the reserve.
        scale=alloc/8000.0
        stages=(reserve_jpy+13000.0*scale, reserve_jpy+18000.0*scale, reserve_jpy+28000.0*scale)
        # local copy of staged logic using allocation as sleeve
        risk=alloc; i=SLOW; stage_idx=0; touched=None; ever_ko=False
        while i<len(chunk)-1 and risk>0 and stage_idx<len(stages):
            stage_target=stages[stage_idx]
            if reserve_jpy+risk>=stage_target:
                stage_idx+=1
                if stage_idx>=len(stages):
                    touched=hit_day(chunk[0].ts,chunk[i].ts)
                    break
                continue
            closes=[b.close for b in chunk[:i+1]]
            sig=1 if sma(closes,FAST)>sma(closes,SLOW) else -1
            entry=chunk[i].close; ko=entry*ko_pct
            option_points=ko+KO_PREMIUM+SPREAD/2
            lots=(risk/USDJPY_REF)/option_points
            if lots<=0: break
            j=i+1
            while j<len(chunk):
                b=chunk[j]; _,h,l,c=b.ohlc()
                adverse=(entry-l) if sig==1 else (h-entry)
                favorable=(h-entry) if sig==1 else (entry-l)
                if adverse>=ko:
                    risk=0.0; ever_ko=True; i=j+1; break
                needed=stage_target-reserve_jpy
                if risk+favorable*lots*USDJPY_REF>=needed:
                    risk=needed; stage_idx+=1; i=j+1
                    if stage_idx>=len(stages): touched=hit_day(chunk[0].ts,b.ts)
                    break
                closes2=[x.close for x in chunk[:j+1]]
                sig2=1 if sma(closes2,FAST)>sma(closes2,SLOW) else -1
                if sig2!=sig:
                    move=(c-entry) if sig==1 else (entry-c)
                    risk=max(0.0,risk+move*lots*USDJPY_REF); i=j+1; break
                j+=1
            else:
                b=chunk[-1]; move=(b.close-entry) if sig==1 else (entry-b.close)
                risk=max(0.0,risk+move*lots*USDJPY_REF); i=len(chunk)
        return {"hit":touched,"final":risk,"ko":ever_ko}

    a=sleeve(chunk_a,alloc_a,ko_a); b=sleeve(chunk_b,alloc_b,ko_b)
    total=reserve_jpy+a["final"]+b["final"]
    hit = None
    # conservative: declare success only if combined terminal wealth reaches target;
    # if both sleeves have hit times, use the later one as an approximate combined hit time.
    if total>=target:
        hs=[x for x in (a["hit"],b["hit"]) if x is not None]
        hit=max(hs) if hs else 7
    return hit,total,a["ko"],b["ko"]

def summarize_split(rows):
    n=len(rows); hitdays=[d for d,total,ka,kb in rows if d is not None]
    return {
      "windows":n,
      "hit_7d_pct":round(100*sum(d is not None for d,_,_,_ in rows)/n,2) if n else 0,
      "any_sleeve_ko_pct":round(100*sum((ka or kb) for _,_,ka,kb in rows)/n,2) if n else 0,
      "both_sleeves_ko_pct":round(100*sum((ka and kb) for _,_,ka,kb in rows)/n,2) if n else 0,
      "median_hit_day":median(hitdays) if hitdays else None,
      "median_final_jpy":round(median([total for _,total,_,_ in rows]),2) if n else None,
    }


def staged_variant_window(chunk, ko_pct, reserve_jpy, stages):
    risk=max(0.0, START-reserve_jpy)
    i=SLOW; idx=0; touched=None; ever_ko=False
    while i<len(chunk)-1 and risk>0 and idx<len(stages):
        total=reserve_jpy+risk
        if total>=stages[idx]:
            idx+=1
            if idx>=len(stages):
                touched=hit_day(chunk[0].ts,chunk[i].ts); break
            continue
        closes=[b.close for b in chunk[:i+1]]
        sig=1 if sma(closes,FAST)>sma(closes,SLOW) else -1
        entry=chunk[i].close; ko=entry*ko_pct
        option_points=ko+KO_PREMIUM+SPREAD/2
        lots=(risk/USDJPY_REF)/option_points
        j=i+1
        while j<len(chunk):
            b=chunk[j]; _,h,l,c=b.ohlc()
            adverse=(entry-l) if sig==1 else (h-entry)
            favorable=(h-entry) if sig==1 else (entry-l)
            if adverse>=ko:
                risk=0.0; ever_ko=True; i=j+1; break
            needed=stages[idx]-reserve_jpy
            if risk+favorable*lots*USDJPY_REF>=needed:
                risk=needed; idx+=1; i=j+1
                if idx>=len(stages): touched=hit_day(chunk[0].ts,b.ts)
                break
            closes2=[x.close for x in chunk[:j+1]]
            sig2=1 if sma(closes2,FAST)>sma(closes2,SLOW) else -1
            if sig2!=sig:
                move=(c-entry) if sig==1 else (entry-c)
                risk=max(0.0,risk+move*lots*USDJPY_REF); i=j+1; break
            j+=1
        else:
            b=chunk[-1]; move=(b.close-entry) if sig==1 else (entry-b.close)
            risk=max(0.0,risk+move*lots*USDJPY_REF); i=len(chunk)
    return touched,reserve_jpy+risk,ever_ko


def filtered_staged_window(chunk, ko_pct=0.0125, reserve_jpy=2000.0,
                           min_trend_gap=0.002, min_abs_24h=0.01):
    """Only trade when trend separation and 24h move are both strong."""
    risk=max(0.0, START-reserve_jpy)
    stages=(15000.0,20000.0,30000.0)
    i=max(SLOW,24); idx=0; touched=None; ever_ko=False; traded=False
    while i<len(chunk)-1 and risk>0 and idx<len(stages):
        closes=[b.close for b in chunk[:i+1]]
        fast=sma(closes,FAST); slow=sma(closes,SLOW)
        gap=abs(fast/slow-1) if slow else 0.0
        move24=abs(closes[-1]/closes[-25]-1) if len(closes)>=25 else 0.0
        if gap<min_trend_gap or move24<min_abs_24h:
            i+=1; continue
        traded=True
        sig=1 if fast>slow else -1
        entry=chunk[i].close; ko=entry*ko_pct
        option_points=ko+KO_PREMIUM+SPREAD/2
        lots=(risk/USDJPY_REF)/option_points
        j=i+1
        stage_target=stages[idx]
        while j<len(chunk):
            b=chunk[j]; _,h,l,c=b.ohlc()
            adverse=(entry-l) if sig==1 else (h-entry)
            favorable=(h-entry) if sig==1 else (entry-l)
            if adverse>=ko:
                risk=0.0; ever_ko=True; i=j+1; break
            needed=stage_target-reserve_jpy
            if risk+favorable*lots*USDJPY_REF>=needed:
                risk=needed; idx+=1; i=j+1
                if idx>=len(stages): touched=hit_day(chunk[0].ts,b.ts)
                break
            closes2=[x.close for x in chunk[:j+1]]
            sig2=1 if sma(closes2,FAST)>sma(closes2,SLOW) else -1
            if sig2!=sig:
                move=(c-entry) if sig==1 else (entry-c)
                risk=max(0.0,risk+move*lots*USDJPY_REF); i=j+1; break
            j+=1
        else:
            b=chunk[-1]; move=(b.close-entry) if sig==1 else (entry-b.close)
            risk=max(0.0,risk+move*lots*USDJPY_REF); i=len(chunk)
    return touched,reserve_jpy+risk,ever_ko,traded

def summarize_filtered(rows):
    traded=[r for r in rows if r[3]]
    n=len(rows); m=len(traded)
    return {
      "windows":n,
      "trade_windows":m,
      "trade_rate_pct":round(100*m/n,2) if n else 0,
      "target_hit_all_windows_pct":round(100*sum(d is not None for d,_,_,_ in rows)/n,2) if n else 0,
      "target_hit_when_traded_pct":round(100*sum(d is not None for d,_,_,_ in traded)/m,2) if m else 0,
      "ko_when_traded_pct":round(100*sum(ko for _,_,ko,_ in traded)/m,2) if m else 0,
      "median_final_jpy":round(median([total for _,total,_,_ in traded]),2) if m else None,
    }


def session_direction_window(chunk, direction="both", start_hour=13, end_hour=21,
                             ko_pct=0.0125, reserve_jpy=2000.0):
    risk=max(0.0, START-reserve_jpy)
    stages=(15000.0,20000.0,30000.0)
    i=SLOW; idx=0; touched=None; ever_ko=False; traded=False
    while i<len(chunk)-1 and risk>0 and idx<len(stages):
        h=chunk[i].ts.hour
        in_session=(start_hour<=h<end_hour) if start_hour<end_hour else (h>=start_hour or h<end_hour)
        if not in_session:
            i+=1; continue
        closes=[b.close for b in chunk[:i+1]]
        fast=sma(closes,FAST); slow=sma(closes,SLOW)
        sig=1 if fast>slow else -1
        if direction=="long" and sig!=1:
            i+=1; continue
        if direction=="short" and sig!=-1:
            i+=1; continue
        traded=True
        entry=chunk[i].close; ko=entry*ko_pct
        option_points=ko+KO_PREMIUM+SPREAD/2
        lots=(risk/USDJPY_REF)/option_points
        j=i+1; stage_target=stages[idx]
        while j<len(chunk):
            b=chunk[j]; _,high,low,c=b.ohlc()
            adverse=(entry-low) if sig==1 else (high-entry)
            favorable=(high-entry) if sig==1 else (entry-low)
            if adverse>=ko:
                risk=0.0; ever_ko=True; i=j+1; break
            needed=stage_target-reserve_jpy
            if risk+favorable*lots*USDJPY_REF>=needed:
                risk=needed; idx+=1; i=j+1
                if idx>=len(stages): touched=hit_day(chunk[0].ts,b.ts)
                break
            closes2=[x.close for x in chunk[:j+1]]
            sig2=1 if sma(closes2,FAST)>sma(closes2,SLOW) else -1
            if sig2!=sig:
                move=(c-entry) if sig==1 else (entry-c)
                risk=max(0.0,risk+move*lots*USDJPY_REF); i=j+1; break
            j+=1
        else:
            b=chunk[-1]; move=(b.close-entry) if sig==1 else (entry-b.close)
            risk=max(0.0,risk+move*lots*USDJPY_REF); i=len(chunk)
    return touched,reserve_jpy+risk,ever_ko,traded


def breakout_staged_window(chunk, lookback=12, atr_mult=0.5, ko_pct=0.0125, reserve_jpy=2000.0):
    risk=max(0.0, START-reserve_jpy)
    stages=(15000.0,20000.0,30000.0)
    i=max(SLOW,lookback+1); idx=0; touched=None; ever_ko=False; traded=False
    while i<len(chunk)-1 and risk>0 and idx<len(stages):
        hist=chunk[i-lookback:i]
        hh=max(b.high for b in hist); ll=min(b.low for b in hist)
        trs=[max(b.high-b.low,abs(b.high-hist[max(0,j-1)].close),abs(b.low-hist[max(0,j-1)].close)) for j,b in enumerate(hist)]
        atr=sum(trs)/len(trs) if trs else 0.0
        px=chunk[i].close
        long_break=px > hh + atr_mult*atr
        short_break=px < ll - atr_mult*atr
        if not (long_break or short_break):
            i+=1; continue
        traded=True
        sig=1 if long_break else -1
        entry=px; ko=entry*ko_pct
        option_points=ko+KO_PREMIUM+SPREAD/2
        lots=(risk/USDJPY_REF)/option_points
        j=i+1; stage_target=stages[idx]
        while j<len(chunk):
            b=chunk[j]; _,high,low,c=b.ohlc()
            adverse=(entry-low) if sig==1 else (high-entry)
            favorable=(high-entry) if sig==1 else (entry-low)
            if adverse>=ko:
                risk=0.0; ever_ko=True; i=j+1; break
            needed=stage_target-reserve_jpy
            if risk+favorable*lots*USDJPY_REF>=needed:
                risk=needed; idx+=1; i=j+1
                if idx>=len(stages): touched=hit_day(chunk[0].ts,b.ts)
                break
            # exit when price crosses back inside breakout range
            if (sig==1 and c<hh) or (sig==-1 and c>ll):
                move=(c-entry) if sig==1 else (entry-c)
                risk=max(0.0,risk+move*lots*USDJPY_REF); i=j+1; break
            j+=1
        else:
            b=chunk[-1]; move=(b.close-entry) if sig==1 else (entry-b.close)
            risk=max(0.0,risk+move*lots*USDJPY_REF); i=len(chunk)
    return touched,reserve_jpy+risk,ever_ko,traded

def summarize_split_halves(rows):
    n=len(rows); cut=n//2
    def sm(part):
        traded=[r for r in part if r[3]]
        m=len(traded)
        return {
          "windows":len(part),
          "trade_windows":m,
          "hit_all_pct":round(100*sum(d is not None for d,_,_,_ in part)/len(part),2) if part else 0,
          "hit_when_traded_pct":round(100*sum(d is not None for d,_,_,_ in traded)/m,2) if m else 0,
          "ko_when_traded_pct":round(100*sum(ko for _,_,ko,_ in traded)/m,2) if m else 0,
        }
    return {"train":sm(rows[:cut]),"holdout":sm(rows[cut:])}


def summarize_quarters(rows):
    n=len(rows)
    out=[]
    for q in range(4):
        a=n*q//4; b=n*(q+1)//4
        part=rows[a:b]; m=len(part)
        traded=[r for r in part if r[3]]
        tm=len(traded)
        out.append({
          "windows":m,
          "hit_pct":round(100*sum(d is not None for d,_,_,_ in part)/m,2) if m else 0,
          "ko_when_traded_pct":round(100*sum(ko for _,_,ko,_ in traded)/tm,2) if tm else 0,
        })
    return out

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
    for target in TARGETS:
        key=str(int(target))
        out[key]={}
        for k in ("gold_ko","silver_ko","oil_ko","nasdaq_ko","sp500_ko","russell2000_ko","nikkei_ko","vix_ko","tesla_ko_proxy","nvidia_ko_proxy"):
            out[key][k]=summarize([ko_window(w,target) for w in windows(data[k])])
        out[key]["fx_usdjpy_25x"]=summarize([leverage_window(w,25.0,target) for w in windows(data["fx_usdjpy"])])
        out[key]["btc_2x"]=summarize([leverage_window(w,2.0,target) for w in windows(data["btc_2x"])])
    out["reserve_tests_30000"]={}
    for reserve in (2000.0,4000.0,6000.0):
        rk=str(int(reserve))
        out["reserve_tests_30000"][rk]={}
        for k in ("sp500_ko","nikkei_ko","nasdaq_ko"):
            out["reserve_tests_30000"][rk][k]=summarize_reserve(
                [ko_window_reserve(w,30_000.0,reserve) for w in windows(data[k])]
            )
    out["distance_tests_30000_reserve2000"]={}
    for kpct in (0.0075,0.01,0.0125,0.015):
        dk=str(kpct)
        out["distance_tests_30000_reserve2000"][dk]={}
        for k in ("sp500_ko","nikkei_ko","nasdaq_ko"):
            out["distance_tests_30000_reserve2000"][dk][k]=summarize_reserve(
                [ko_window_distance(w,30_000.0,kpct,2000.0) for w in windows(data[k])]
            )
    out["staged_tests_30000_reserve2000"]={}
    for kpct in (0.01,0.0125,0.015):
        dk=str(kpct)
        out["staged_tests_30000_reserve2000"][dk]={}
        for k in ("sp500_ko","nasdaq_ko"):
            out["staged_tests_30000_reserve2000"][dk][k]=summarize_staged(
                [staged_ko_window(w,kpct,2000.0,(15000.0,20000.0,30000.0)) for w in windows(data[k])]
            )
    out["split_tests_30000_reserve2000"]={}
    nas_w=windows(data["nasdaq_ko"]); sp_w=windows(data["sp500_ko"])
    m=min(len(nas_w),len(sp_w))
    for wa in (0.25,0.5,0.75):
        key=str(wa)
        out["split_tests_30000_reserve2000"][key]=summarize_split([
            split_staged_window(nas_w[i],sp_w[i],wa,2000.0,30000.0,0.015,0.0125)
            for i in range(m)
        ])
    out["sp500_stage_variants"]={}
    variants={
      "12_15_20_30":(12000.0,15000.0,20000.0,30000.0),
      "13_17_22_30":(13000.0,17000.0,22000.0,30000.0),
      "15_20_30":(15000.0,20000.0,30000.0),
      "15_18_22_26_30":(15000.0,18000.0,22000.0,26000.0,30000.0),
      "20_30":(20000.0,30000.0)
    }
    spw=windows(data["sp500_ko"])
    for name,stages in variants.items():
        out["sp500_stage_variants"][name]=summarize_staged([
            staged_variant_window(w,0.01,2000.0,stages) for w in spw
        ])
    out["nasdaq_filter_tests"]={}
    nw=windows(data["nasdaq_ko"])
    for gap in (0.001,0.002,0.003,0.004):
        for mv in (0.005,0.01,0.015,0.02):
            key=f"gap{gap}_mv{mv}"
            out["nasdaq_filter_tests"][key]=summarize_filtered([
                filtered_staged_window(w,0.0125,2000.0,gap,mv) for w in nw
            ])
    out["nasdaq_session_direction_tests"]={}
    nw=windows(data["nasdaq_ko"])
    for direction in ("both","long","short"):
        for start,end in ((0,8),(8,13),(13,17),(13,21),(17,21),(21,24)):
            key=f"{direction}_{start}_{end}"
            out["nasdaq_session_direction_tests"][key]=summarize_filtered([
                session_direction_window(w,direction,start,end,0.0125,2000.0) for w in nw
            ])
    out["nasdaq_breakout_holdout"]={}
    nw=windows(data["nasdaq_ko"])
    for lb in (6,12,18,24):
        for am in (0.0,0.25,0.5,1.0):
            key=f"lb{lb}_atr{am}"
            rows=[breakout_staged_window(w,lb,am,0.0125,2000.0) for w in nw]
            out["nasdaq_breakout_holdout"][key]=summarize_split_halves(rows)
    out["nasdaq_breakout_refine_holdout"]={}
    nw=windows(data["nasdaq_ko"])
    for lb in (4,6,8):
        for am in (0.0,0.05,0.1,0.15,0.2,0.25,0.3):
            key=f"lb{lb}_atr{am}"
            rows=[breakout_staged_window(w,lb,am,0.0125,2000.0) for w in nw]
            out["nasdaq_breakout_refine_holdout"][key]=summarize_split_halves(rows)
    out["nasdaq_breakout_quarter_check"]={}
    nw=windows(data["nasdaq_ko"])
    for lb,am in ((4,0.0),(4,0.3),(8,0.1)):
        key=f"lb{lb}_atr{am}"
        rows=[breakout_staged_window(w,lb,am,0.0125,2000.0) for w in nw]
        out["nasdaq_breakout_quarter_check"][key]=summarize_quarters(rows)
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
      "objective":"JPY10000 to target JPY30000 or JPY50000; stop on first touch; maximum 7 days",
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
