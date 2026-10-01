"""Time-window holdout test for USDJPY momentum6h binary feasibility.

Discovery:
- Use only 2024 and 2025 observations.
- Same frozen empirical 20%-tail model and momentum6h signal.
- Compare UTC 2-hour block start hours.
- Select the single start hour with highest discovery hit rate, requiring >=100 observations.

Validation:
- Apply that exact UTC start hour to 2026 only.
- No retuning on 2026.

This is NOT historical broker pricing. It excludes spread, strike grid and execution.
"""
from __future__ import annotations
import json, math, ssl, urllib.parse, urllib.request
from datetime import datetime, timezone

HOST="query1.finance.yahoo.com"
UA="crypto-paper-trader-public-binary-hour-holdout/1.0"
SYMBOL="JPY=X"
INTERVAL="1h"
RANGE="730d"
BLOCK_BARS=2
LOOKBACK_BLOCKS=12*20

def fetch():
    enc=urllib.parse.quote(SYMBOL,safe="")
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
    return [(int(t),float(c)) for t,c in zip(ts,cc) if c is not None]

def qtile(vals,q):
    xs=sorted(vals)
    p=(len(xs)-1)*q
    lo=int(math.floor(p)); hi=int(math.ceil(p))
    if lo==hi:return xs[lo]
    return xs[lo]+(xs[hi]-xs[lo])*(p-lo)

def blocks(s):
    out=[]
    for i in range(0,len(s)-BLOCK_BARS,BLOCK_BARS):
        a=s[i]; b=s[i+BLOCK_BARS]
        if not(6900<=b[0]-a[0]<=7500):continue
        dt=datetime.fromtimestamp(a[0],tz=timezone.utc)
        out.append({"ts":a[0],"year":dt.year,"hour":dt.hour,
                    "start":a[1],"end":b[1],"ret":b[1]/a[1]-1.0})
    return out

def observations(bs):
    rows=[]
    for i in range(max(LOOKBACK_BLOCKS,3),len(bs)):
        hist=[x["ret"] for x in bs[i-LOOKBACK_BLOCKS:i]]
        lo=qtile(hist,0.20); hi=qtile(hist,0.80)
        prior6=bs[i-1]["end"]/bs[i-3]["start"]-1.0
        if prior6==0:continue
        upper=prior6>0
        r=bs[i]["ret"]
        hit=(r>=hi) if upper else (r<=lo)
        rows.append({"year":bs[i]["year"],"hour":bs[i]["hour"],"hit":hit})
    return rows

def summ(xs):
    n=len(xs)
    if not n:return {"n":0}
    h=sum(x["hit"] for x in xs)
    return {"n":n,"hits":h,"hit_rate_pct":round(100*h/n,4),
            "idealized_5x_mean_multiple":round(5*h/n,4)}

def main():
    rows=observations(blocks(series(fetch())))
    discovery=[x for x in rows if x["year"] in (2024,2025)]
    validation=[x for x in rows if x["year"]==2026]
    by_hour={}
    for h in sorted(set(x["hour"] for x in discovery)):
        xs=[x for x in discovery if x["hour"]==h]
        by_hour[str(h)]=summ(xs)
    eligible=[(h,v) for h,v in by_hour.items() if v["n"]>=100]
    eligible.sort(key=lambda kv:(-kv[1]["hit_rate_pct"],-kv[1]["n"],int(kv[0])))
    best_hour=int(eligible[0][0]) if eligible else None
    val=[x for x in validation if x["hour"]==best_hour] if best_hour is not None else []
    dis=[x for x in discovery if x["hour"]==best_hour] if best_hour is not None else []
    print(json.dumps({
      "paper_only":True,
      "model":"USDJPY momentum6h, 20%-tail, time-window discovery/2026 holdout",
      "required_break_even_hit_rate_pct_before_costs":20.0,
      "discovery_2024_2025_by_utc_hour":by_hour,
      "selected_utc_hour":best_hour,
      "selected_discovery":summ(dis),
      "validation_2026":summ(val),
      "warning":"not broker quotes; excludes spread, strike grid and execution"
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
