"""Segment full-risk put baskets by DTE and premium band.

Descriptive research on JPX actual NK225 mini-option closes.
Full loss of 10,000 JPY is allowed. Exit at first later daily close where
basket account value reaches >=50,000 JPY.

Six pre-defined variants:
- DTE 2-4 / 5-7 / 2-7
- premium 10-20 / 21-30 JPY
All variants are PUT-only, OTM, up to 4 distinct strikes, full-account basket.
No parameter optimization inside a variant.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-put-segments/1.0"
PRODUCT="NK225MWE"
START=10_000.0
TARGET=50_000.0
MULT=100.0
MAX_LEGS=4
VARIANTS=(
 ("dte2_4_p10_20",2,4,10.0,20.0),
 ("dte2_4_p21_30",2,4,21.0,30.0),
 ("dte5_7_p10_20",5,7,10.0,20.0),
 ("dte5_7_p21_30",5,7,21.0,30.0),
 ("dte2_7_p10_20",2,7,10.0,20.0),
 ("dte2_7_p21_30",2,7,21.0,30.0),
)

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
            code=r[5].strip(); p=num(r[6])
            if code and p is not None and p>0:
                opts[code]={"code":code,"premium":p,"strike":strike,"maturity":maturity}
        daily[day]={"underlying":u,"options":opts}
    return daily

def build(day,book,dmin,dmax,pmin,pmax):
    u=book["underlying"]
    if u is None:return None
    xs=[]
    for o in book["options"].values():
        if o["strike"] is None or not(pmin<=o["premium"]<=pmax):continue
        if o["strike"]>u:continue
        m=u/o["strike"]-1.0
        try:md=datetime.strptime(o["maturity"],"%Y%m%d").date()
        except:continue
        dte=(md-day).days
        if not(dmin<=dte<=dmax):continue
        xs.append((m,o))
    xs.sort(key=lambda x:(x[0],x[1]["premium"]))
    if not xs:return None

    chosen=[]
    cash=START
    for m,o in xs:
        cost=o["premium"]*MULT
        if cost<=cash and len(chosen)<MAX_LEGS:
            chosen.append({"m":m,"o":o,"qty":1}); cash-=cost
        if len(chosen)>=MAX_LEGS:break
    if not chosen:return None

    progress=True
    while progress:
        progress=False
        for leg in chosen:
            cost=leg["o"]["premium"]*MULT
            if cost<=cash:
                leg["qty"]+=1; cash-=cost; progress=True
    return {"legs":chosen,"cash":cash,"spent":START-cash}

def run(day,basket,daily,dates):
    marks=[]
    for d in dates:
        if d<=day or d>day+timedelta(days=7):continue
        ob=daily[d]["options"]
        value=basket["cash"]
        for leg in basket["legs"]:
            x=ob.get(leg["o"]["code"])
            if x:value+=x["premium"]*MULT*leg["qty"]
        marks.append((d,value))
        if value>=TARGET:break
    if not marks:return None
    best=max(marks,key=lambda x:x[1]); last=marks[-1]
    return {
      "entry_date":day.strftime("%Y%m%d"),
      "spent_yen":round(basket["spent"],2),"cash_left_yen":round(basket["cash"],2),
      "legs":[{"code":x["o"]["code"],"premium":x["o"]["premium"],
               "strike":x["o"]["strike"],"maturity":x["o"]["maturity"],
               "qty":x["qty"]} for x in basket["legs"]],
      "best_date":best[0].strftime("%Y%m%d"),"best_value_yen":round(best[1],2),
      "target_hit":best[1]>=TARGET,
      "exit_date":last[0].strftime("%Y%m%d"),"exit_value_yen":round(last[1],2)
    }

def summarize(rows):
    n=len(rows)
    if not n:return {"entries":0}
    exits=sorted(r["exit_value_yen"] for r in rows)
    return {"entries":n,
      "target_hits":sum(r["target_hit"] for r in rows),
      "target_rate_pct":round(100*sum(r["target_hit"] for r in rows)/n,4),
      "exit_zero_rate_pct":round(100*sum(r["exit_value_yen"]==0 for r in rows)/n,4),
      "exit_below_5000_rate_pct":round(100*sum(r["exit_value_yen"]<5000 for r in rows)/n,4),
      "median_exit_yen":round(exits[n//2] if n%2 else (exits[n//2-1]+exits[n//2])/2,2),
      "best_value_yen":round(max(r["best_value_yen"] for r in rows),2),
      "worst_exit_yen":round(min(exits),2)}

def main():
    daily=load(); dates=sorted(daily)
    out={}
    for name,dmin,dmax,pmin,pmax in VARIANTS:
        rows=[]
        for day in dates:
            basket=build(day,daily[day],dmin,dmax,pmin,pmax)
            if not basket:continue
            r=run(day,basket,daily,dates)
            if r:rows.append(r)
        split=len(rows)//2
        non=[]; nxt=None
        for r in rows:
            d=datetime.strptime(r["entry_date"],"%Y%m%d").date()
            if nxt is None or d>=nxt:
                non.append(r); nxt=d+timedelta(days=7)
        out[name]={
          "params":{"dte":[dmin,dmax],"premium":[pmin,pmax]},
          "all":summarize(rows),
          "first_half":summarize(rows[:split]),
          "second_half":summarize(rows[split:]),
          "non_overlapping":summarize(non),
          "hits":[r for r in rows if r["target_hit"]]
        }
    print(json.dumps({
      "paper_only":True,
      "source":"JPX actual daily NK225 mini-option closes",
      "start_yen":START,"target_yen":TARGET,
      "variants":out
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
