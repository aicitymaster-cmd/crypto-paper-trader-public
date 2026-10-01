"""Read-only Thursday/Friday candidate-B signal.

No orders, no auth, no broker access.

Frozen candidate B:
- Thursday: CALL, DTE 6 (next Wednesday)
- Friday: CALL, DTE 5 or 7 (next Wednesday or next Friday)
- OTM
- actual premium 10-30 JPY
- up to 4 distinct strikes
- budget 10,000 JPY

Research only. Daily closing data do not guarantee executable fills.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-thufri-signal/2.0"
PRODUCT="NK225MWE"
START=10_000.0
P_MIN=10.0
P_MAX=30.0
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
    if not rows: raise RuntimeError("NO_JPX_LISTING")
    item=max(rows,key=lambda x:str(x.get("TradeDate","")))
    ds=str(item.get("TradeDate",""))
    path=item.get("File")
    if not ds or not path: raise RuntimeError("BAD_JPX_LISTING_ROW")
    return datetime.strptime(ds,"%Y%m%d").date(),urllib.parse.urljoin(BASE,path)

def load(url):
    rows=list(csv.reader(io.StringIO(dec(get(url,"text/csv,*/*")))))
    calls={}; u=None
    for r in rows:
        if len(r)<17 or r[0].strip()!=PRODUCT:continue
        strike=num(r[3]); uu=num(r[15]); maturity=r[2].strip()
        if uu is not None:u=uu
        code=r[10].strip(); p=num(r[11])
        if code and p is not None and p>0:
            calls[code]={"code":code,"premium":p,"strike":strike,"maturity":maturity}
    if u is None: raise RuntimeError("NO_UNDERLYING")
    return {"underlying":u,"call":calls}

def build(day,book,allowed_dtes):
    u=book["underlying"]
    xs=[]
    for o in book["call"].values():
        if o["strike"] is None or not(P_MIN<=o["premium"]<=P_MAX):continue
        if o["strike"]<u:continue
        m=o["strike"]/u-1.0
        try:md=datetime.strptime(o["maturity"],"%Y%m%d").date()
        except:continue
        if (md-day).days not in allowed_dtes:continue
        xs.append((m,o))
    xs.sort(key=lambda x:(x[0],x[1]["premium"]))
    if not xs:return None
    chosen=[]; cash=START
    for m,o in xs:
        cost=o["premium"]*MULT
        if cost<=cash and len(chosen)<MAX_LEGS:
            chosen.append({"o":o,"qty":1}); cash-=cost
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
    out={"paper_only":True,"trade_date":day.isoformat(),
         "weekday":day.strftime("%A"),"source":url}

    if day.weekday()==3:
        allowed={6}
        expiry_note="next Wednesday"
    elif day.weekday()==4:
        allowed={5,7}
        expiry_note="next Wednesday or next Friday"
    else:
        out["signal"]="NO_SIGNAL_NOT_THU_OR_FRI"
        print(json.dumps(out,ensure_ascii=False,sort_keys=True))
        return

    book=load(url)
    basket=build(day,book,allowed)
    out["frozen_rule"]={
        "side":"call",
        "allowed_dte":sorted(allowed),
        "expiry":expiry_note,
        "premium":[P_MIN,P_MAX],
        "max_distinct_strikes":MAX_LEGS,
        "budget_yen":START
    }

    if not basket:
        out["signal"]="NO_ELIGIBLE_BASKET"
    else:
        out["signal"]="PAPER_CANDIDATE"
        out["underlying"]=book["underlying"]
        out["spent_yen"]=round(basket["spent"],2)
        out["cash_left_yen"]=round(basket["cash"],2)
        out["legs"]=[{
            "code":x["o"]["code"],
            "strike":x["o"]["strike"],
            "maturity":x["o"]["maturity"],
            "premium":x["o"]["premium"],
            "unit_cost_yen":x["o"]["premium"]*MULT,
            "qty":x["qty"]
        } for x in basket["legs"]]

    print(json.dumps(out,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
