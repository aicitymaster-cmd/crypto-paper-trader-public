"""Measure actual Nikkei 225 Mini Options convexity from JPX daily premium closes.

Uses the 50 business days currently published by JPX. Entry candidates are
NK225MWE mini options with an actual closing premium between 50 and 100 JPY,
equivalent to 5,000-10,000 JPY per contract (premium x 100 JPY).

For each entry observation, tracks the same option code for up to 7 calendar
days and records the maximum later actual closing premium. This uses daily
closes only, not intraday highs. Research only; no trading action.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-jpx-mini-option-research/1.0"
TIMEOUT=20
MAX_BYTES=8_000_000
PRODUCT="NK225MWE"
ENTRY_MIN=50.0
ENTRY_MAX=100.0

def get(url,accept):
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Accept":accept})
    with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=TIMEOUT) as resp:
        body=resp.read(MAX_BYTES+1)
    if len(body)>MAX_BYTES: raise RuntimeError("BODY_TOO_LARGE")
    return body

def decode_csv(body):
    for enc in ("utf-8-sig","shift_jis","cp932"):
        try:return body.decode(enc)
        except UnicodeDecodeError:pass
    return body.decode("utf-8","replace")

def fnum(s):
    s=(s or "").strip()
    if not s:return None
    try:return float(s)
    except ValueError:return None

def main():
    listing=json.loads(get(JSON_URL,"application/json").decode("utf-8","replace"))
    table=listing.get("TableDatas") or []
    daily={}
    stats={"files":0,"mini_rows":0,"actual_close_points":0}
    for item in sorted(table,key=lambda x:x.get("TradeDate","")):
        ds=str(item.get("TradeDate",""))
        path=item.get("File")
        if not ds or not path:continue
        day=datetime.strptime(ds,"%Y%m%d").date()
        rows=list(csv.reader(io.StringIO(decode_csv(get(urllib.parse.urljoin(BASE,path),"text/csv,*/*")))))
        stats["files"]+=1
        daymap={}
        for r in rows:
            if len(r)<17 or r[0].strip()!=PRODUCT:continue
            stats["mini_rows"]+=1
            maturity=r[2].strip()
            strike=fnum(r[3])
            underlying=fnum(r[15])
            for side,code_i,close_i in (("put",5,6),("call",10,11)):
                code=r[code_i].strip()
                close=fnum(r[close_i])
                if not code or close is None or close<=0:continue
                stats["actual_close_points"]+=1
                daymap[code]={
                    "date":ds,"side":side,"code":code,"maturity":maturity,
                    "strike":strike,"premium":close,"underlying":underlying,
                }
        daily[day]=daymap

    dates=sorted(daily)
    entries=[]
    for day in dates:
        for code,e in daily[day].items():
            p=e["premium"]
            if not (ENTRY_MIN<=p<=ENTRY_MAX):continue
            deadline=day+timedelta(days=7)
            future=[]
            for d in dates:
                if d<=day or d>deadline:continue
                x=daily[d].get(code)
                if x:future.append(x)
            if not future:continue
            best=max(future,key=lambda x:x["premium"])
            mult=best["premium"]/p
            entries.append({
              "entry_date":e["date"],"side":e["side"],"code":code,
              "maturity":e["maturity"],"strike":e["strike"],
              "underlying_entry":e["underlying"],
              "entry_premium":round(p,4),
              "entry_cost_yen":round(p*100,2),
              "best_date":best["date"],
              "best_premium":round(best["premium"],4),
              "best_value_yen":round(best["premium"]*100,2),
              "max_multiple":round(mult,4),
            })

    n=len(entries)
    def rate(th):
        return round(100*sum(x["max_multiple"]>=th for x in entries)/n,4) if n else 0
    by_side={}
    for side in ("call","put"):
        xs=[x for x in entries if x["side"]==side]
        by_side[side]={
          "entries":len(xs),
          "hit_2x":sum(x["max_multiple"]>=2 for x in xs),
          "hit_5x":sum(x["max_multiple"]>=5 for x in xs),
          "hit_9x":sum(x["max_multiple"]>=9 for x in xs),
        }
    top=sorted(entries,key=lambda x:x["max_multiple"],reverse=True)[:40]
    return {
      "paper_only":True,
      "source":"JPX official option theoretical-price daily files",
      "product":PRODUCT,
      "entry_premium_range_yen":[ENTRY_MIN,ENTRY_MAX],
      "entry_cost_range_yen":[ENTRY_MIN*100,ENTRY_MAX*100],
      "lookahead_calendar_days":7,
      "uses_actual_daily_closing_premiums_only":True,
      "stats":stats,
      "eligible_entry_observations":n,
      "hit_rates_pct":{"2x":rate(2),"3x":rate(3),"5x":rate(5),"9x":rate(9),"10x":rate(10)},
      "by_side":by_side,
      "top_examples":top,
    }

if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
