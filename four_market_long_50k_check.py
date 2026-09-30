"""Pre-registered four-market long-horizon screening with BTC.

Research only. No broker/product execution is implied for the generic bounded-risk
sleeves. Uses 1h public OHLC, excludes the recent 30m tuning period from
2026-07-22 onward, and evaluates only non-overlapping 7-day windows.

No parameter sweep: six portfolio rules are fixed before evaluation.
"""
from __future__ import annotations
import json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from cross_market_backtest import Bar

HOST="query1.finance.yahoo.com"; RANGE="730d"; INTERVAL="1h"
TIMEOUT=20; MAX_BYTES=12_000_000
UA="crypto-paper-trader-public-four-market-long/1.0"
CUT=datetime(2026,7,22,tzinfo=timezone.utc)
START=10_000.0; TARGET=50_000.0; FLOOR=5_000.0
FAST=6; SLOW=18
MARKETS={"GBPJPY":"GBPJPY=X","GOLD":"GC=F","NASDAQ100":"NQ=F","BTCUSD":"BTC-USD"}
SETTINGS={
  "GBPJPY":(0.01,0.25),
  "GOLD":(0.005,0.50),
  "NASDAQ100":(0.005,0.50),
  "BTCUSD":(0.01,0.50),
}
RULES={
 "equal_fixed":{"initial":{m:0.25 for m in MARKETS},"winner_weight":None,"profit_lock":False},
 "gbp_anchor_fixed":{"initial":{"GBPJPY":0.40,"GOLD":0.20,"NASDAQ100":0.20,"BTCUSD":0.20},"winner_weight":None,"profit_lock":False},
 "equal_adaptive60":{"initial":{m:0.25 for m in MARKETS},"winner_weight":0.60,"profit_lock":False},
 "equal_adaptive70":{"initial":{m:0.25 for m in MARKETS},"winner_weight":0.70,"profit_lock":False},
 "equal_adaptive60_lock":{"initial":{m:0.25 for m in MARKETS},"winner_weight":0.60,"profit_lock":True},
 "equal_adaptive70_lock":{"initial":{m:0.25 for m in MARKETS},"winner_weight":0.70,"profit_lock":True},
}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise RuntimeError("REDIRECT_NOT_ALLOWED")

def fetch(symbol):
    enc=urllib.parse.quote(symbol,safe="")
    url=(f"https://{HOST}/v8/finance/chart/{enc}?range={RANGE}&interval={INTERVAL}"
         "&includePrePost=false&events=div%2Csplits")
    opener=urllib.request.build_opener(
        urllib.request.ProxyHandler({}),NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Accept":"application/json"})
    with opener.open(req,timeout=TIMEOUT) as resp:
        body=resp.read(MAX_BYTES+1)
    if len(body)>MAX_BYTES: raise RuntimeError("BODY_TOO_LARGE")
    return json.loads(body)

def parse(payload):
    res=(payload.get("chart") or {}).get("result") or []
    if not res: raise RuntimeError("NO_RESULT")
    r=res[0]; ts=r.get("timestamp") or []
    q=((r.get("indicators") or {}).get("quote") or [{}])[0]
    out=[]
    for t,o,h,l,c in zip(ts,q.get("open") or [],q.get("high") or [],q.get("low") or [],q.get("close") or []):
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

def windows(bars):
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

def run(days,rule):
    reserve=0.; active=START; alloc=dict(rule["initial"])
    for d in days:
        mults={m:sleeve(d[m],1.0,*SETTINGS[m]) for m in MARKETS}
        active=sum(active*alloc[m]*mults[m] for m in MARKETS)
        total=reserve+active
        if total>=TARGET: return TARGET
        if rule["profit_lock"] and total>=15_000. and reserve<5_000.:
            reserve=5_000.; active=max(0.,total-reserve)
        if active<=0: break
        ww=rule["winner_weight"]
        if ww is not None:
            winner=max(mults,key=mults.get)
            rest=(1.-ww)/(len(MARKETS)-1)
            alloc={m:(ww if m==winner else rest) for m in MARKETS}
    return reserve+active

def summarize(rows):
    vals=[r["final_yen"] for r in rows]; s=sorted(vals); n=len(s)
    if not n:return {"windows":0}
    med=s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2
    return {"windows":n,
      "target_hits":sum(v>=TARGET for v in vals),
      "target_rate_pct":round(100*sum(v>=TARGET for v in vals)/n,4),
      "below_5000":sum(v<FLOOR for v in vals),
      "below_5000_rate_pct":round(100*sum(v<FLOOR for v in vals)/n,4),
      "at_least_10000_rate_pct":round(100*sum(v>=START for v in vals)/n,4),
      "median_final_yen":round(med,2),
      "best_final_yen":round(max(s),2),"worst_final_yen":round(min(s),2)}

def main():
    bars={m:parse(fetch(sym)) for m,sym in MARKETS.items()}
    wins=windows(bars)
    result={}
    for name,rule in RULES.items():
        rows=[{"start":st.isoformat(),"final_yen":round(run(days,rule),2)} for st,days in wins]
        yearly={}
        for r in rows: yearly.setdefault(r["start"][:4],[]).append(r)
        result[name]={"overall":summarize(rows),"by_year":{y:summarize(v) for y,v in sorted(yearly.items())}}
    return {
      "paper_only":True,
      "model":"pre-registered four-market generic bounded-risk screening",
      "execution_warning":"generic research model; not a verified executable broker product",
      "cutoff_excluded_from":CUT.isoformat(),
      "interval":INTERVAL,"sma_equivalent_hours":{"fast":6,"slow":18},
      "settings":{m:{"distance":SETTINGS[m][0],"risk":SETTINGS[m][1]} for m in MARKETS},
      "non_overlapping_windows":len(wins),
      "rules":result,
    }

if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
