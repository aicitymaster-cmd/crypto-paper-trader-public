"""Long-horizon independent validation of the frozen 3-market strategy.

Uses 1h bars and excludes the recent period used in prior 30m tuning.
To preserve the original time horizon, SMA12/36 on 30m is mapped to
SMA6/18 on 1h. Research only; zero spread/funding/KO premium remains optimistic.
"""
from __future__ import annotations
import json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

from cross_market_backtest import Bar

HOST="query1.finance.yahoo.com"
RANGE="730d"
INTERVAL="1h"
TIMEOUT=20
MAX_BYTES=12_000_000
UA="crypto-paper-trader-public-long-independent/1.0"

START=10_000.0
TARGET=50_000.0
FLOOR=5_000.0
CUT=datetime(2026,7,22,tzinfo=timezone.utc)
FAST=6
SLOW=18
MARKETS={"GBPJPY":"GBPJPY=X","GOLD":"GC=F","NASDAQ100":"NQ=F"}
INITIAL={"GBPJPY":0.50,"GOLD":0.25,"NASDAQ100":0.25}
SETTINGS={"GBPJPY":(0.01,0.25),"GOLD":(0.005,1.00),"NASDAQ100":(0.0025,0.50)}
WINNER_WEIGHT=0.70

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise RuntimeError("REDIRECT_NOT_ALLOWED")

def fetch(symbol):
    enc=urllib.parse.quote(symbol,safe="")
    url=(f"https://{HOST}/v8/finance/chart/{enc}"
         f"?range={RANGE}&interval={INTERVAL}&includePrePost=false&events=div%2Csplits")
    opener=urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Accept":"application/json"})
    with opener.open(req,timeout=TIMEOUT) as resp:
        body=resp.read(MAX_BYTES+1)
    if len(body)>MAX_BYTES: raise RuntimeError("BODY_TOO_LARGE")
    return json.loads(body)

def parse(payload):
    r=(payload.get("chart") or {}).get("result") or []
    if not r: raise RuntimeError("NO_RESULT")
    r=r[0]; ts=r.get("timestamp") or []
    q=((r.get("indicators") or {}).get("quote") or [{}])[0]
    oo=q.get("open") or []; hh=q.get("high") or []; ll=q.get("low") or []; cc=q.get("close") or []
    out=[]
    for t,o,h,l,c in zip(ts,oo,hh,ll,cc):
        if None in (o,h,l,c): continue
        dt=datetime.fromtimestamp(int(t),tz=timezone.utc)
        if dt>=CUT: continue
        vals=list(map(float,(o,h,l,c)))
        if min(vals)<=0: continue
        out.append(Bar(dt,vals[3],vals[0],vals[1],vals[2]))
    out.sort(key=lambda x:x.ts)
    return out

def sma(v,n): return sum(v[-n:])/n

def sleeve(bars,start,distance,risk_fraction):
    equity=start; pos=0; entry=0.; entry_equity=equity; risk_budget=0.
    for i in range(SLOW,len(bars)):
        closes=[b.close for b in bars[:i+1]]
        bar=bars[i]; signal=1 if sma(closes,FAST)>sma(closes,SLOW) else -1
        if pos:
            _,high,low,close=bar.ohlc()
            adverse=(low/entry-1.) if pos==1 else (entry/high-1.)
            close_move=pos*(close/entry-1.)
            if adverse<=-distance:
                equity=max(0.,entry_equity-risk_budget); pos=0
            elif signal!=pos:
                pnl=max(-risk_budget,risk_budget*close_move/distance)
                equity=max(0.,entry_equity+pnl); pos=0
        if not pos and equity>0:
            pos=signal; entry=bar.close; entry_equity=equity; risk_budget=equity*risk_fraction
    if pos and equity>0:
        raw=pos*(bars[-1].close/entry-1.)
        pnl=max(-risk_budget,risk_budget*raw/distance)
        equity=max(0.,entry_equity+pnl)
    return equity

def nonoverlap_windows(bars):
    start=max(v[0].ts.replace(hour=0,minute=0,second=0,microsecond=0) for v in bars.values())
    end=min(v[-1].ts for v in bars.values())
    out=[]; cur=start
    while cur+timedelta(days=7)<=end:
        days=[]
        for d in range(7):
            a=cur+timedelta(days=d); b=a+timedelta(days=1)
            chunks={m:[x for x in bs if a<=x.ts<b] for m,bs in bars.items()}
            if all(len(v)>SLOW for v in chunks.values()):
                days.append(chunks)
        if len(days)>=4: out.append((cur,days))
        cur+=timedelta(days=7)
    return out

def run(days):
    reserve=0.; active=START; alloc=dict(INITIAL)
    for d in days:
        mults={m:sleeve(d[m],1.0,*SETTINGS[m]) for m in MARKETS}
        active=sum(active*alloc[m]*mults[m] for m in MARKETS)
        total=reserve+active
        if total>=TARGET: return TARGET
        if total>=15_000. and reserve<5_000.:
            reserve=5_000.; active=max(0.,total-reserve)
        if active<=0: break
        winner=max(mults,key=mults.get)
        rest=(1.-WINNER_WEIGHT)/2.
        alloc={m:(WINNER_WEIGHT if m==winner else rest) for m in MARKETS}
    return reserve+active

def summarize(rows):
    finals=[x["final_yen"] for x in rows]; s=sorted(finals); n=len(s)
    med=s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2
    return {
      "windows":n,
      "target_hits":sum(x>=TARGET for x in finals),
      "target_rate_pct":round(100*sum(x>=TARGET for x in finals)/n,4),
      "below_5000":sum(x<FLOOR for x in finals),
      "below_5000_rate_pct":round(100*sum(x<FLOOR for x in finals)/n,4),
      "at_least_10000_rate_pct":round(100*sum(x>=START for x in finals)/n,4),
      "median_final_yen":round(med,2),
      "best_final_yen":round(max(s),2),
      "worst_final_yen":round(min(s),2),
    }

def regime_summary(rows):
    groups={}
    for r in rows:
        y=r["start"][:4]
        groups.setdefault(y,[]).append(r)
    return {k:summarize(v) for k,v in sorted(groups.items())}

def main():
    bars={m:parse(fetch(sym)) for m,sym in MARKETS.items()}
    wins=nonoverlap_windows(bars)
    rows=[{"start":st.isoformat(),"final_yen":round(run(days),2)} for st,days in wins]
    return {
      "paper_only":True,
      "model":"frozen adaptive profit-lock, long independent pre-cutoff validation",
      "interval":INTERVAL,
      "cutoff_excluded_from":CUT.isoformat(),
      "sma_equivalent_hours":{"fast":6,"slow":18},
      "assumptions":{"spread":0,"funding":0,"ko_premium":0},
      "coverage":{m:{"first":bs[0].ts.isoformat(),"last":bs[-1].ts.isoformat(),"bars":len(bs)} for m,bs in bars.items()},
      "non_overlapping_7day":summarize(rows),
      "by_calendar_year":regime_summary(rows),
      "window_starts":[r["start"] for r in rows],
    }

if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
