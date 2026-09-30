"""Symmetric ultra-cheap NK225 mini-option basket.

Fixed rule:
- Keep at least 5,000 JPY cash.
- Spend at most 5,000 JPY on a basket of ultra-cheap OTM mini options.
- Same nearest maturity 2-7 calendar days away.
- Eligible leg premium 10-20 JPY (=1,000-2,000 JPY).
- Hold 1-2 calls and 1-2 puts; total premium <=50 JPY.
- Prefer the maximum number of legs, then smaller combined moneyness,
  then spending more of the budget.
- Track all selected option codes for up to 7 calendar days using later
  actual JPX closing premiums. If a leg disappears, mark it at zero thereafter.

Research only. Daily closes do not guarantee executable fills.
"""
from __future__ import annotations
import csv, io, itertools, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-ultracheap-basket/1.0"
PRODUCT="NK225MWE"
START=10_000.0
TARGET=50_000.0
FLOOR=5_000.0
MAX_PREMIUM=50.0
P_MIN=10.0
P_MAX=20.0
MULT=100.0

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
        if not ds or not path: continue
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
                    opts[code]={"code":code,"side":side,"premium":p,
                                "strike":strike,"maturity":maturity}
        daily[day]={"underlying":u,"options":opts}
    return daily

def choose(day,book):
    u=book["underlying"]
    if u is None:return None
    opts=list(book["options"].values())
    mats=[]
    for ms in sorted(set(o["maturity"] for o in opts)):
        try:md=datetime.strptime(ms,"%Y%m%d").date()
        except:continue
        dd=(md-day).days
        if 2<=dd<=7:mats.append((md,ms))
    for _,ms in mats:
        calls=[]; puts=[]
        for o in opts:
            if o["maturity"]!=ms or o["strike"] is None or not(P_MIN<=o["premium"]<=P_MAX):continue
            if o["side"]=="call" and o["strike"]>=u:
                m=o["strike"]/u-1.0
                calls.append((m,o))
            elif o["side"]=="put" and o["strike"]<=u:
                m=u/o["strike"]-1.0
                puts.append((m,o))
        calls.sort(key=lambda x:x[0]); puts.sort(key=lambda x:x[0])
        calls=calls[:8]; puts=puts[:8]
        candidates=[]
        for nc in (1,2):
            for np in (1,2):
                if len(calls)<nc or len(puts)<np:continue
                for cs in itertools.combinations(calls,nc):
                    for ps in itertools.combinations(puts,np):
                        legs=[x[1] for x in cs]+[x[1] for x in ps]
                        total=sum(x["premium"] for x in legs)
                        if total>MAX_PREMIUM:continue
                        distance=sum(x[0] for x in cs)+sum(x[0] for x in ps)
                        candidates.append((-len(legs),distance,-total,legs,ms))
        if candidates:
            candidates.sort(key=lambda x:(x[0],x[1],x[2]))
            _,distance,neg_total,legs,ms=candidates[0]
            return {"maturity":ms,"legs":legs,"combined":-neg_total,"distance":distance}
    return None

def summarize(rows):
    n=len(rows)
    if not n:return {"campaigns":0}
    finals=sorted(r["final_value_yen"] for r in rows)
    return {
      "campaigns":n,
      "target_hits":sum(r["target_hit"] for r in rows),
      "target_rate_pct":round(100*sum(r["target_hit"] for r in rows)/n,4),
      "best_at_least_20000_rate_pct":round(100*sum(r["best_value_yen"]>=20000 for r in rows)/n,4),
      "final_below_5000_rate_pct":round(100*sum(r["final_value_yen"]<FLOOR for r in rows)/n,4),
      "final_at_least_10000_rate_pct":round(100*sum(r["final_value_yen"]>=START for r in rows)/n,4),
      "median_final_yen":round(finals[n//2] if n%2 else (finals[n//2-1]+finals[n//2])/2,2),
      "best_value_yen":round(max(r["best_value_yen"] for r in rows),2),
      "worst_final_yen":round(min(finals),2),
    }

def main():
    daily=load(); dates=sorted(daily); rows=[]
    for day in dates:
        sel=choose(day,daily[day])
        if not sel:continue
        cost=sel["combined"]*MULT
        cash=START-cost
        if cash<FLOOR:continue
        deadline=day+timedelta(days=7)
        marks=[]
        for d in dates:
            if d<=day or d>deadline:continue
            ob=daily[d]["options"]
            value=cash
            for leg in sel["legs"]:
                x=ob.get(leg["code"])
                if x:value+=x["premium"]*MULT
            marks.append((d,value))
        if not marks:continue
        best=max(marks,key=lambda x:x[1]); last=marks[-1]
        rows.append({
          "entry_date":day.strftime("%Y%m%d"),"maturity":sel["maturity"],
          "entry_cost_yen":round(cost,2),"cash_left_yen":round(cash,2),
          "leg_count":len(sel["legs"]),
          "legs":[{"side":x["side"],"code":x["code"],"premium":x["premium"],"strike":x["strike"]} for x in sel["legs"]],
          "best_date":best[0].strftime("%Y%m%d"),"best_value_yen":round(best[1],2),
          "target_hit":best[1]>=TARGET,
          "final_date":last[0].strftime("%Y%m%d"),"final_value_yen":round(last[1],2)
        })
    split=len(dates)//2
    first_dates=set(dates[:split]); second_dates=set(dates[split:])
    first=[r for r in rows if datetime.strptime(r["entry_date"],"%Y%m%d").date() in first_dates]
    second=[r for r in rows if datetime.strptime(r["entry_date"],"%Y%m%d").date() in second_dates]
    non=[]; next_allowed=None
    for r in rows:
        d=datetime.strptime(r["entry_date"],"%Y%m%d").date()
        if next_allowed is None or d>=next_allowed:
            non.append(r); next_allowed=d+timedelta(days=7)
    print(json.dumps({
      "paper_only":True,
      "source":"JPX actual daily NK225 mini-option closes",
      "rule":{"cash_floor_yen":FLOOR,"max_option_cost_yen":MAX_PREMIUM*MULT,
              "leg_premium_range":[P_MIN,P_MAX],"calls":[1,2],"puts":[1,2],
              "same_nearest_maturity":True,"dte_days":[2,7]},
      "all":summarize(rows),"first_half":summarize(first),
      "second_half":summarize(second),"non_overlapping":summarize(non),
      "rows":rows
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
