"""Full-concentration one-shot NK225 mini-option research.

Risk tolerance: total loss of the 10,000 JPY account is allowed.

For each eligible JPX business day:
- Direction uses only the PRIOR business-day move (day -1 vs day -2).
- Four pre-registered rules: momentum, contrarian, put_only, call_only.
- Choose one OTM NK225 mini option with actual premium 10-30 JPY
  (=1,000-3,000 JPY per contract), DTE 2-7 calendar days.
- Selection within a side: lowest premium first, then closest OTM strike.
- Spend as much of the 10,000 JPY account as possible on multiple contracts
  of that single option. Unused remainder stays cash.
- Track the same option for up to 7 calendar days using later actual JPX closes.
- Success if marked account value reaches >=50,000 JPY at a later daily close.

Research only. Daily closes do not guarantee executable fills.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-full-concentration/1.0"
PRODUCT="NK225MWE"
START=10_000.0
TARGET=50_000.0
P_MIN=10.0
P_MAX=30.0
MULT=100.0
RULES=("momentum","contrarian","put_only","call_only")

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
                    opts[code]={"code":code,"side":side,"premium":p,
                                "strike":strike,"maturity":maturity}
        daily[day]={"underlying":u,"options":opts}
    return daily

def choose(day,book,side):
    u=book["underlying"]
    if u is None:return None
    xs=[]
    for o in book["options"].values():
        if o["side"]!=side or o["strike"] is None or not(P_MIN<=o["premium"]<=P_MAX):
            continue
        if side=="call":
            if o["strike"]<u:continue
            m=o["strike"]/u-1.0
        else:
            if o["strike"]>u:continue
            m=u/o["strike"]-1.0
        try:md=datetime.strptime(o["maturity"],"%Y%m%d").date()
        except:continue
        dte=(md-day).days
        if not(2<=dte<=7):continue
        xs.append((o["premium"],m,dte,o))
    if not xs:return None
    xs.sort(key=lambda x:(x[0],x[1],x[2]))
    return xs[0][3]

def direction(rule,daily,dates,i):
    if rule=="put_only":return "put"
    if rule=="call_only":return "call"
    if i<2:return None
    p1=daily[dates[i-1]]["underlying"]
    p2=daily[dates[i-2]]["underlying"]
    if p1 is None or p2 is None or p1==p2:return None
    up=p1>p2
    if rule=="momentum":
        return "call" if up else "put"
    return "put" if up else "call"

def run_entry(rule,daily,dates,i):
    day=dates[i]
    side=direction(rule,daily,dates,i)
    if not side:return None
    o=choose(day,daily[day],side)
    if not o:return None
    unit_cost=o["premium"]*MULT
    qty=int(START//unit_cost)
    if qty<1:return None
    spent=qty*unit_cost
    cash=START-spent
    marks=[]
    for d in dates:
        if d<=day or d>day+timedelta(days=7):continue
        x=daily[d]["options"].get(o["code"])
        value=cash+(x["premium"]*MULT*qty if x else 0.0)
        marks.append((d,value,(x["premium"] if x else 0.0)))
    if not marks:return None
    best=max(marks,key=lambda x:x[1])
    last=marks[-1]
    return {
      "entry_date":day.strftime("%Y%m%d"),"rule":rule,"side":side,
      "code":o["code"],"maturity":o["maturity"],"strike":o["strike"],
      "entry_premium":o["premium"],"unit_cost_yen":unit_cost,"qty":qty,
      "spent_yen":spent,"cash_left_yen":cash,
      "best_date":best[0].strftime("%Y%m%d"),"best_premium":best[2],
      "best_value_yen":round(best[1],2),"target_hit":best[1]>=TARGET,
      "final_date":last[0].strftime("%Y%m%d"),"final_value_yen":round(last[1],2)
    }

def summarize(rows):
    n=len(rows)
    if not n:return {"entries":0}
    finals=sorted(r["final_value_yen"] for r in rows)
    return {
      "entries":n,
      "target_hits":sum(r["target_hit"] for r in rows),
      "target_rate_pct":round(100*sum(r["target_hit"] for r in rows)/n,4),
      "best_at_least_20000_rate_pct":round(100*sum(r["best_value_yen"]>=20000 for r in rows)/n,4),
      "final_zero_rate_pct":round(100*sum(r["final_value_yen"]==0 for r in rows)/n,4),
      "final_below_5000_rate_pct":round(100*sum(r["final_value_yen"]<5000 for r in rows)/n,4),
      "median_final_yen":round(finals[n//2] if n%2 else (finals[n//2-1]+finals[n//2])/2,2),
      "best_value_yen":round(max(r["best_value_yen"] for r in rows),2),
      "worst_final_yen":round(min(finals),2)
    }

def main():
    daily=load(); dates=sorted(daily)
    results={}
    for rule in RULES:
        rows=[]
        for i in range(len(dates)):
            r=run_entry(rule,daily,dates,i)
            if r:rows.append(r)
        split=len(rows)//2
        non=[]; nxt=None
        for r in rows:
            d=datetime.strptime(r["entry_date"],"%Y%m%d").date()
            if nxt is None or d>=nxt:
                non.append(r); nxt=d+timedelta(days=7)
        results[rule]={
          "all":summarize(rows),
          "first_half":summarize(rows[:split]),
          "second_half":summarize(rows[split:]),
          "non_overlapping":summarize(non),
          "top_entries":sorted(rows,key=lambda x:x["best_value_yen"],reverse=True)[:12]
        }
    print(json.dumps({
      "paper_only":True,
      "source":"JPX actual daily NK225 mini-option closes",
      "rule":{"start_yen":START,"full_loss_allowed":True,
              "premium_range_yen":[P_MIN,P_MAX],
              "unit_cost_yen":[P_MIN*MULT,P_MAX*MULT],
              "dte_days":[2,7],"single_option_multi_contract":True,
              "direction_uses_prior_business_day_only":True},
      "results":results
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
