"""Measure convexity of ultra-cheap NK225 mini options.

Actual JPX daily closing premiums only.
Entry observations:
- NK225 mini options (NK225MWE)
- actual premium 10-30 JPY (=1,000-3,000 JPY per contract)
- OTM only
- 2-7 calendar days to maturity
For each observation, track the same option code for up to 7 calendar days
and record the maximum later actual closing premium.

Research only. This measures historical convexity, not a trading rule.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-ultracheap-options/1.0"
PRODUCT="NK225MWE"
P_MIN=10.0
P_MAX=30.0

def get(url,accept):
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Accept":accept})
    with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=20) as resp:
        return resp.read(8_000_000)

def dec(body):
    for enc in ("utf-8-sig","shift_jis","cp932"):
        try:return body.decode(enc)
        except UnicodeDecodeError:pass
    return body.decode("utf-8","replace")

def num(s):
    try:return float((s or "").strip())
    except:return None

def load():
    listing=json.loads(get(JSON_URL,"application/json").decode("utf-8","replace"))
    daily={}
    for item in sorted(listing.get("TableDatas") or [],key=lambda x:x.get("TradeDate","")):
        ds=str(item.get("TradeDate","")); path=item.get("File")
        if not ds or not path:continue
        day=datetime.strptime(ds,"%Y%m%d").date()
        rows=list(csv.reader(io.StringIO(dec(get(urllib.parse.urljoin(BASE,path),"text/csv,*/*")))))
        opts={}; u=None
        for r in rows:
            if len(r)<17 or r[0].strip()!=PRODUCT:continue
            strike=num(r[3]); uu=num(r[15]); maturity=r[2].strip()
            if uu is not None:u=uu
            for side,ci,pi in (("put",5,6),("call",10,11)):
                code=r[ci].strip(); p=num(r[pi])
                if code and p is not None and p>0:
                    opts[code]={"code":code,"side":side,"premium":p,"strike":strike,"maturity":maturity}
        daily[day]={"underlying":u,"options":opts}
    return daily

def main():
    daily=load(); dates=sorted(daily); rows=[]
    for day in dates:
        u=daily[day]["underlying"]
        if u is None:continue
        for o in daily[day]["options"].values():
            p=o["premium"]
            if not(P_MIN<=p<=P_MAX) or o["strike"] is None:continue
            if o["side"]=="call" and o["strike"]<u:continue
            if o["side"]=="put" and o["strike"]>u:continue
            try:md=datetime.strptime(o["maturity"],"%Y%m%d").date()
            except:continue
            dte=(md-day).days
            if not(2<=dte<=7):continue
            vals=[]
            for d in dates:
                if d<=day or d>day+timedelta(days=7):continue
                x=daily[d]["options"].get(o["code"])
                if x:vals.append((d,x["premium"]))
            if not vals:continue
            bd,bp=max(vals,key=lambda x:x[1])
            rows.append({
              "entry_date":day.strftime("%Y%m%d"),"side":o["side"],"code":o["code"],
              "maturity":o["maturity"],"strike":o["strike"],"underlying":u,
              "entry_premium":p,"entry_cost_yen":p*100,
              "best_date":bd.strftime("%Y%m%d"),"best_premium":bp,
              "best_value_yen":bp*100,"max_multiple":bp/p
            })
    n=len(rows)
    def rate(t):
        return round(100*sum(r["max_multiple"]>=t for r in rows)/n,4) if n else 0
    by_side={}
    for side in ("call","put"):
        xs=[r for r in rows if r["side"]==side]
        by_side[side]={
          "n":len(xs),
          "10x":sum(r["max_multiple"]>=10 for r in xs),
          "20x":sum(r["max_multiple"]>=20 for r in xs),
          "40x":sum(r["max_multiple"]>=40 for r in xs)
        }
    by_date={}
    for r in rows:
        d=r["entry_date"]
        x=by_date.setdefault(d,{"n":0,"max_multiple":0.0,"count_10x":0,"count_20x":0,"count_40x":0})
        x["n"]+=1
        x["max_multiple"]=max(x["max_multiple"],r["max_multiple"])
        x["count_10x"]+=r["max_multiple"]>=10
        x["count_20x"]+=r["max_multiple"]>=20
        x["count_40x"]+=r["max_multiple"]>=40
    print(json.dumps({
      "paper_only":True,
      "source":"JPX actual daily NK225 mini-option closes",
      "entry_premium_range_yen":[P_MIN,P_MAX],
      "entry_cost_range_yen":[P_MIN*100,P_MAX*100],
      "eligible_observations":n,
      "hit_rates_pct":{"5x":rate(5),"10x":rate(10),"20x":rate(20),"30x":rate(30),"40x":rate(40)},
      "by_side":by_side,
      "dates_with_10x":sum(v["count_10x"]>0 for v in by_date.values()),
      "dates_with_20x":sum(v["count_20x"]>0 for v in by_date.values()),
      "dates_with_40x":sum(v["count_40x"]>0 for v in by_date.values()),
      "top_dates":sorted(
          [{"date":d,**v} for d,v in by_date.items()],
          key=lambda x:x["max_multiple"],reverse=True
      )[:20],
      "top_examples":sorted(rows,key=lambda x:x["max_multiple"],reverse=True)[:30]
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
