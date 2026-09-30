"""Check long-horizon public OHLC availability for independent research.

Read-only public Yahoo Chart GETs. No authentication, secrets, or trading.
"""
from __future__ import annotations
import json, ssl, urllib.parse, urllib.request
from datetime import datetime, timezone

HOST="query1.finance.yahoo.com"
INTERVAL="1h"
RANGE="730d"
TIMEOUT=20
MAX_BYTES=12_000_000
UA="crypto-paper-trader-public-long-horizon-readonly/1.0"
MARKETS={
  "GBPJPY":"GBPJPY=X",
  "GOLD":"GC=F",
  "NASDAQ100":"NQ=F",
  "BTCUSD":"BTC-USD",
}

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

def inspect(payload):
    chart=payload.get("chart") or {}
    if chart.get("error"): raise RuntimeError(f"CHART_ERROR:{chart['error']}")
    results=chart.get("result") or []
    if not results: raise RuntimeError("NO_RESULT")
    r=results[0]
    ts=r.get("timestamp") or []
    q=((r.get("indicators") or {}).get("quote") or [{}])[0]
    closes=q.get("close") or []
    valid=[int(t) for t,c in zip(ts,closes) if c is not None]
    if not valid: raise RuntimeError("NO_VALID_BARS")
    first=datetime.fromtimestamp(valid[0],tz=timezone.utc)
    last=datetime.fromtimestamp(valid[-1],tz=timezone.utc)
    return {
      "bars":len(valid),
      "first_ts":first.isoformat(),
      "last_ts":last.isoformat(),
      "calendar_days":round((last-first).total_seconds()/86400,2),
    }

def main():
    out={"paper_only":True,"source":"Yahoo Chart public read-only","range":RANGE,"interval":INTERVAL,
         "markets":{},"failures":{}}
    for name,symbol in MARKETS.items():
        try: out["markets"][name]={"symbol":symbol,**inspect(fetch(symbol))}
        except Exception as e: out["failures"][name]=f"{type(e).__name__}:{e}"
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
