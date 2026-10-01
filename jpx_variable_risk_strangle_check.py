"""Idealized 20-point-equivalent FX binary feasibility screen.

Purpose:
Estimate whether simple, no-lookahead signals can beat the ~20% hit rate
required by an all-in 5x binary structure.

This is NOT a reconstruction of IG quotes. It uses public Yahoo 5-minute FX
bars and defines a "20-point-equivalent" rare event empirically:
- Split each FX series into sequential 2-hour blocks.
- At each block start, use only the prior 20 trading days of completed 2-hour
  returns to estimate the 80th and 20th percentile thresholds.
- Upper event: next 2h return >= trailing 80th percentile.
- Lower event: next 2h return <= trailing 20th percentile.
Thus each side is calibrated to roughly a 20% unconditional event before
signal filtering.

Pre-registered signals:
- momentum6h: prior 6h return >0 -> upper, <0 -> lower
- contrarian6h: prior 6h return >0 -> lower, <0 -> upper
- momentum2h: prior 2h return >0 -> upper, <0 -> lower
- contrarian2h: prior 2h return >0 -> lower, <0 -> upper

Markets: USDJPY, GBPJPY, EURJPY.
Research only. No broker quote, spread, slippage, or execution model.
"""
from __future__ import annotations
import json, math, ssl, statistics, urllib.parse, urllib.request
from datetime import datetime, timezone

HOST="query1.finance.yahoo.com"
UA="crypto-paper-trader-public-binary-feasibility/1.0"
MARKETS={"USDJPY":"JPY=X","GBPJPY":"GBPJPY=X","EURJPY":"EURJPY=X"}
INTERVAL="5m"
RANGE="60d"
BLOCK_BARS=24  # 2 hours at 5m
LOOKBACK_BLOCKS=12*20  # ~20 trading days
SIGNALS=("momentum6h","contrarian6h","momentum2h","contrarian2h")

def fetch(symbol):
    enc=urllib.parse.quote(symbol,safe="")
    url=(f"https://{HOST}/v8/finance/chart/{enc}"
         f"?range={RANGE}&interval={INTERVAL}&includePrePost=false&events=div%2Csplits")
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Accept":"application/json"})
    with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=20) as resp:
        return json.loads(resp.read(10_000_000))

def closes(payload):
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
    pos=(len(xs)-1)*q
    lo=int(math.floor(pos)); hi=int(math.ceil(pos))
    if lo==hi:return xs[lo]
    return xs[lo]+(xs[hi]-xs[lo])*(pos-lo)

def block_returns(series):
    # Use consecutive observed bars; gaps create longer effective periods, so
    # reject blocks whose elapsed time is far from 2h.
    out=[]
    for i in range(0,len(series)-BLOCK_BARS,BLOCK_BARS):
        a=series[i]; b=series[i+BLOCK_BARS]
        elapsed=b[0]-a[0]
        if not (6900<=elapsed<=7500):continue
        out.append({"start_ts":a[0],"start":a[1],"end":b[1],"ret":b[1]/a[1]-1.0})
    return out

def decide(signal, blocks, i):
    if "6h" in signal:
        n=3
    else:
        n=1
    if i<n:return None
    prior=1.0
    start=blocks[i-n]["start"]
    end=blocks[i-1]["end"]
    r=end/start-1.0
    if r==0:return None
    momentum=signal.startswith("momentum")
    if momentum:
        return "upper" if r>0 else "lower"
    return "lower" if r>0 else "upper"

def evaluate(blocks,signal):
    rows=[]
    for i in range(LOOKBACK_BLOCKS,len(blocks)):
        hist=[x["ret"] for x in blocks[i-LOOKBACK_BLOCKS:i]]
        lo=quantile(hist,0.20); hi=quantile(hist,0.80)
        side=decide(signal,blocks,i)
        if side is None:continue
        r=blocks[i]["ret"]
        hit=(r>=hi) if side=="upper" else (r<=lo)
        rows.append({
          "ts":blocks[i]["start_ts"],"side":side,"ret":r,
          "threshold":hi if side=="upper" else lo,"hit":hit
        })
    n=len(rows)
    if not n:return {"trades":0}
    split=n//2
    def s(xs):
        m=len(xs)
        if not m:return {"trades":0}
        hits=sum(x["hit"] for x in xs)
        return {"trades":m,"hits":hits,
                "hit_rate_pct":round(100*hits/m,4),
                "idealized_all_in_5x_mean_multiple":round(5*hits/m,4)}
    return {"all":s(rows),"first_half":s(rows[:split]),"second_half":s(rows[split:])}

def main():
    result={}
    for name,sym in MARKETS.items():
        bs=block_returns(closes(fetch(sym)))
        result[name]={"blocks":len(bs),
                      "signals":{sig:evaluate(bs,sig) for sig in SIGNALS}}
    print(json.dumps({
      "paper_only":True,
      "model":"empirical 20-percent-tail binary feasibility, not broker quotes",
      "required_break_even_hit_rate_pct_before_costs":20.0,
      "markets":result
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
