"""Long-horizon validation of frozen FX binary feasibility candidates.

Frozen after 5-minute discovery:
- USDJPY momentum6h
- GBPJPY momentum6h

Uses Yahoo public 1-hour bars over 730 days. Each outcome is a 2-hour return.
A "20-point-equivalent" event is defined empirically using only prior data:
- trailing 20 trading days of completed 2-hour returns
- upper/lower thresholds = 80th/20th percentiles
- prior 6-hour return determines direction (momentum)

This is NOT historical IG pricing. It only tests whether the underlying signal
beats the ~20% hit rate required by a 5x all-in binary before spread/costs.

Robustness:
- chronological thirds
- calendar-year split
- non-overlapping daily first signal (one candidate per UTC day)
"""
from __future__ import annotations
import json, math, ssl, urllib.parse, urllib.request
from datetime import datetime, timezone

HOST="query1.finance.yahoo.com"
UA="crypto-paper-trader-public-binary-long/1.0"
MARKETS={"USDJPY":"JPY=X","GBPJPY":"GBPJPY=X"}
INTERVAL="1h"
RANGE="730d"
BLOCK_BARS=2
LOOKBACK_BLOCKS=12*20

def fetch(symbol):
    enc=urllib.parse.quote(symbol,safe="")
    url=(f"https://{HOST}/v8/finance/chart/{enc}"
         f"?range={RANGE}&interval={INTERVAL}&includePrePost=false&events=div%2Csplits")
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Accept":"application/json"})
    with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=20) as resp:
        return json.loads(resp.read(20_000_000))

def series(payload):
    r=(payload.get("chart") or {}).get("result") or []
    if not r:raise RuntimeError("NO_RESULT")
    r=r[0]; ts=r.get("timestamp") or []
    q=((r.get("indicators") or {}).get("quote") or [{}])[0]
    cc=q.get("close") or []
    out=[]
    for t,c in zip(ts,cc):
        if c is None:continue
        out.append((int(t),float(c)))
    return out

def quantile(vals,q):
    xs=sorted(vals)
    if not xs:return None
    p=(len(xs)-1)*q
    lo=int(math.floor(p)); hi=int(math.ceil(p))
    if lo==hi:return xs[lo]
    return xs[lo]+(xs[hi]-xs[lo])*(p-lo)

def blocks(s):
    out=[]
    for i in range(0,len(s)-BLOCK_BARS,BLOCK_BARS):
        a=s[i]; b=s[i+BLOCK_BARS]
        elapsed=b[0]-a[0]
        if not (6900<=elapsed<=7500):continue
        out.append({"ts":a[0],"start":a[1],"end":b[1],"ret":b[1]/a[1]-1.0})
    return out

def evaluate(bs):
    rows=[]
    for i in range(max(LOOKBACK_BLOCKS,3),len(bs)):
        hist=[x["ret"] for x in bs[i-LOOKBACK_BLOCKS:i]]
        lo=quantile(hist,0.20); hi=quantile(hist,0.80)
        prior6=bs[i-1]["end"]/bs[i-3]["start"]-1.0
        if prior6==0:continue
        side="upper" if prior6>0 else "lower"
        r=bs[i]["ret"]
        hit=(r>=hi) if side=="upper" else (r<=lo)
        dt=datetime.fromtimestamp(bs[i]["ts"],tz=timezone.utc)
        rows.append({"ts":bs[i]["ts"],"date":dt.date().isoformat(),
                     "year":dt.year,"side":side,"hit":hit})
    return rows

def summary(rows):
    n=len(rows)
    if not n:return {"trades":0}
    h=sum(r["hit"] for r in rows)
    return {"trades":n,"hits":h,"hit_rate_pct":round(100*h/n,4),
            "idealized_5x_mean_multiple":round(5*h/n,4)}

def thirds(rows):
    n=len(rows); a=n//3; b=2*n//3
    return {"first":summary(rows[:a]),"middle":summary(rows[a:b]),"last":summary(rows[b:])}

def one_per_day(rows):
    seen=set(); out=[]
    for r in rows:
        if r["date"] in seen:continue
        seen.add(r["date"]); out.append(r)
    return out

def main():
    result={}
    for name,sym in MARKETS.items():
        bs=blocks(series(fetch(sym)))
        rows=evaluate(bs)
        by_year={}
        for r in rows:by_year.setdefault(str(r["year"]),[]).append(r)
        daily=one_per_day(rows)
        result[name]={
          "blocks":len(bs),
          "all":summary(rows),
          "chronological_thirds":thirds(rows),
          "by_year":{y:summary(v) for y,v in sorted(by_year.items())},
          "one_signal_per_utc_day":summary(daily),
          "one_signal_per_utc_day_thirds":thirds(daily)
        }
    print(json.dumps({
      "paper_only":True,
      "model":"long-horizon empirical 20-percent-tail binary feasibility",
      "required_break_even_hit_rate_pct_before_costs":20.0,
      "warning":"not IG historical quotes; excludes broker spread, strike grid and execution",
      "markets":result
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
