"""Full-risk one-side basket with 5x account take-profit.

Risk tolerance: total loss allowed.

For each eligible business day:
- Direction uses only PRIOR business-day move:
  momentum or contrarian. Put-only/call-only are included as baselines.
- Eligible NK225 mini options: OTM, premium 10-30 JPY, DTE 2-7 days.
- Spend up to the full 10,000 JPY account on a basket of up to 4 different
  strikes on the chosen side.
- Prefer max number of legs, then closest total moneyness, then higher spend.
- Quantity is one contract per selected strike first; if cash remains, add
  extra contracts round-robin from closest OTM outward until no eligible unit fits.
- At each later daily close up to 7 calendar days, mark the whole basket.
- If marked account equity reaches >=50,000 JPY, exit everything at that close
  and record 50,000+ as a target hit.

Research only. Daily closes do not guarantee executable fills.
"""
from __future__ import annotations
import csv, io, itertools, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-full-risk-basket/1.0"
PRODUCT="NK225MWE"
START=10_000.0
TARGET=50_000.0
P_MIN=10.0
P_MAX=30.0
MULT=100.0
MAX_LEGS=4
RULES=("contrarian","momentum","put_only","call_only")

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

def direction(rule,daily,dates,i):
    if rule=="put_only":return "put"
    if rule=="call_only":return "call"
    if i<2:return None
    p1=daily[dates[i-1]]["underlying"]
    p2=daily[dates[i-2]]["underlying"]
    if p1 is None or p2 is None or p1==p2:return None
    up=p1>p2
    return ("call" if up else "put") if rule=="momentum" else ("put" if up else "call")

def candidates(day,book,side):
    u=book["underlying"]
    if u is None:return []
    xs=[]
    for o in book["options"].values():
        if o["side"]!=side or o["strike"] is None or not(P_MIN<=o["premium"]<=P_MAX):continue
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
        xs.append((m,o))
    xs.sort(key=lambda x:(x[0],x[1]["premium"]))
    return xs

def build_basket(day,book,side):
    xs=candidates(day,book,side)
    if not xs:return None
    # First take up to four nearest OTM strikes that can each fit once.
    selected=[]
    cash=START
    for m,o in xs:
        cost=o["premium"]*MULT
        if cost<=cash and len(selected)<MAX_LEGS:
            selected.append({"m":m,"o":o,"qty":1})
            cash-=cost
        if len(selected)>=MAX_LEGS:break
    if not selected:return None
    # Reinvest remaining cash round-robin across selected strikes, closest first.
    progress=True
    while progress:
        progress=False
        for leg in selected:
            cost=leg["o"]["premium"]*MULT
            if cost<=cash:
                leg["qty"]+=1
                cash-=cost
                progress=True
    return {"legs":selected,"cash":cash,"spent":START-cash}

def run_entry(rule,daily,dates,i):
    day=dates[i]
    side=direction(rule,daily,dates,i)
    if not side:return None
    basket=build_basket(day,daily[day],side)
    if not basket:return None
    marks=[]
    for d in dates:
        if d<=day or d>day+timedelta(days=7):continue
        ob=daily[d]["options"]
        value=basket["cash"]
        for leg in basket["legs"]:
            x=ob.get(leg["o"]["code"])
            if x:value+=x["premium"]*MULT*leg["qty"]
        marks.append((d,value))
        if value>=TARGET:
            break
    if not marks:return None
    best=max(marks,key=lambda x:x[1]); last=marks[-1]
    return {
      "entry_date":day.strftime("%Y%m%d"),"rule":rule,"side":side,
      "spent_yen":round(basket["spent"],2),"cash_left_yen":round(basket["cash"],2),
      "legs":[{"code":x["o"]["code"],"premium":x["o"]["premium"],
               "strike":x["o"]["strike"],"maturity":x["o"]["maturity"],
               "qty":x["qty"]} for x in basket["legs"]],
      "best_date":best[0].strftime("%Y%m%d"),"best_value_yen":round(best[1],2),
      "target_hit":best[1]>=TARGET,
      "exit_date":last[0].strftime("%Y%m%d"),
      "exit_value_yen":round(last[1],2)
    }

def summarize(rows):
    n=len(rows)
    if not n:return {"entries":0}
    exits=sorted(r["exit_value_yen"] for r in rows)
    return {
      "entries":n,
      "target_hits":sum(r["target_hit"] for r in rows),
      "target_rate_pct":round(100*sum(r["target_hit"] for r in rows)/n,4),
      "best_at_least_20000_rate_pct":round(100*sum(r["best_value_yen"]>=20000 for r in rows)/n,4),
      "exit_zero_rate_pct":round(100*sum(r["exit_value_yen"]==0 for r in rows)/n,4),
      "exit_below_5000_rate_pct":round(100*sum(r["exit_value_yen"]<5000 for r in rows)/n,4),
      "median_exit_yen":round(exits[n//2] if n%2 else (exits[n//2-1]+exits[n//2])/2,2),
      "best_value_yen":round(max(r["best_value_yen"] for r in rows),2),
      "worst_exit_yen":round(min(exits),2)
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
              "premium_range_yen":[P_MIN,P_MAX],"dte_days":[2,7],
              "max_distinct_strikes":MAX_LEGS,
              "target_exit_yen":TARGET,
              "direction_uses_prior_business_day_only":True},
      "results":results
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
