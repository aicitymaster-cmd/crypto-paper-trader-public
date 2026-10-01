"""Read-only Tuesday signal for the frozen NK225 mini-option candidate.

No orders, no authentication, no broker access.
Downloads the latest JPX theoretical-price daily-file listing, uses the newest
available business-day CSV, and only emits a candidate if that trading date is
Tuesday.

Frozen candidate:
- PUT only
- OTM
- DTE 2-4 calendar days
- actual premium 10-30 JPY
- up to 4 distinct strikes
- deploy up to 10,000 JPY
- add extra contracts round-robin while cash permits

Output is research only and does not place any trade.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-tuesday-signal/1.0"
PRODUCT="NK225MWE"
START=10_000.0
P_MIN=10.0
P_MAX=30.0
DTE_MIN=2
DTE_MAX=4
MULT=100.0
MAX_LEGS=4

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

def latest_file():
    listing=json.loads(get(JSON_URL,"application/json").decode("utf-8","replace"))
    rows=listing.get("TableDatas") or []
    if not rows:raise RuntimeError("NO_JPX_LISTING")
    item=max(rows,key=lambda x:str(x.get("TradeDate","")))
    ds=str(item.get("TradeDate",""))
    path=item.get("File")
    if not ds or not path:raise RuntimeError("BAD_JPX_LISTING_ROW")
    return datetime.strptime(ds,"%Y%m%d").date(),urllib.parse.urljoin(BASE,path)

def load(day,url):
    rows=list(csv.reader(io.StringIO(dec(get(url,"text/csv,*/*")))))
    opts={}; u=None
    for r in rows:
        if len(r)<17 or r[0].strip()!=PRODUCT:continue
        strike=num(r[3]); uu=num(r[15]); maturity=r[2].strip()
        if uu is not None:u=uu
        code=r[5].strip(); p=num(r[6])
        if code and p is not None and p>0:
            opts[code]={"code":code,"premium":p,"strike":strike,"maturity":maturity}
    if u is None:raise RuntimeError("NO_UNDERLYING")
    return {"underlying":u,"options":opts}

def build(day,book):
    u=book["underlying"]
    xs=[]
    for o in book["options"].values():
        if o["strike"] is None or not(P_MIN<=o["premium"]<=P_MAX):continue
        if o["strike"]>u:continue
        m=u/o["strike"]-1.0
        try:md=datetime.strptime(o["maturity"],"%Y%m%d").date()
        except:continue
        dte=(md-day).days
        if not(DTE_MIN<=dte<=DTE_MAX):continue
        xs.append((m,o))
    xs.sort(key=lambda x:(x[0],x[1]["premium"]))
    if not xs:return None
    chosen=[]; cash=START
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

def main():
    day,url=latest_file()
    result={
      "paper_only":True,
      "trade_date":day.isoformat(),
      "weekday":day.strftime("%A"),
      "source":url,
      "frozen_rule":{"side":"put","dte":[DTE_MIN,DTE_MAX],
                     "premium":[P_MIN,P_MAX],"max_distinct_strikes":MAX_LEGS,
                     "budget_yen":START}
    }
    if day.weekday()!=1:
        result["signal"]="NO_SIGNAL_NOT_TUESDAY"
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return
    book=load(day,url)
    basket=build(day,book)
    if not basket:
        result["signal"]="NO_ELIGIBLE_BASKET"
    else:
        result["signal"]="PAPER_CANDIDATE"
        result["underlying"]=book["underlying"]
        result["spent_yen"]=round(basket["spent"],2)
        result["cash_left_yen"]=round(basket["cash"],2)
        result["legs"]=[{
            "code":x["o"]["code"],
            "premium":x["o"]["premium"],
            "unit_cost_yen":x["o"]["premium"]*MULT,
            "strike":x["o"]["strike"],
            "maturity":x["o"]["maturity"],
            "qty":x["qty"]
        } for x in basket["legs"]]
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
