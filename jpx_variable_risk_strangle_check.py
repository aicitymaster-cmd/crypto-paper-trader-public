"""4-7 DTE, ~6% OTM ultra-cheap NK225 mini-option strangle.

Fixed structural rule:
- Keep at least 5,000 JPY cash.
- Buy exactly one OTM call + one OTM put when both are available.
- Same maturity, 4-7 calendar days away.
- Each actual premium 10-30 JPY (=1,000-3,000 JPY).
- Combined premium <=50 JPY (=<=5,000 JPY).
- On each side choose the contract whose absolute OTM moneyness is closest to 6%.
- If multiple maturities qualify, choose the one whose DTE is closest to 5 days,
  then smaller total moneyness error, then higher spend.
- Track the same two option codes for up to 7 calendar days using actual JPX closes.

Research only. Daily closes do not guarantee executable fills.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-6pct-strangle/1.0"
PRODUCT="NK225MWE"
START=10_000.0
TARGET=50_000.0
FLOOR=5_000.0
P_MIN=10.0
P_MAX=30.0
MAX_COMBINED=50.0
TARGET_M=0.06
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

def choose(day,book):
    u=book["underlying"]
    if u is None:return None
    by_mat={}
    for o in book["options"].values():
        if o["strike"] is None or not(P_MIN<=o["premium"]<=P_MAX):continue
        try:md=datetime.strptime(o["maturity"],"%Y%m%d").date()
        except:continue
        dte=(md-day).days
        if not(4<=dte<=7):continue
        if o["side"]=="call":
            if o["strike"]<u:continue
            m=o["strike"]/u-1.0
        else:
            if o["strike"]>u:continue
            m=u/o["strike"]-1.0
        by_mat.setdefault(o["maturity"],{"dte":dte,"call":[],"put":[]})[o["side"]].append((abs(m-TARGET_M),m,o))
    pairs=[]
    for ms,g in by_mat.items():
        if not g["call"] or not g["put"]:continue
        g["call"].sort(key=lambda x:(x[0],x[1],x[2]["premium"]))
        g["put"].sort(key=lambda x:(x[0],x[1],x[2]["premium"]))
        # Consider a few nearest-to-target candidates per side so budget can bind.
        for ce,cm,c in g["call"][:5]:
            for pe,pm,p in g["put"][:5]:
                total=c["premium"]+p["premium"]
                if total>MAX_COMBINED:continue
                error=ce+pe
                pairs.append((abs(g["dte"]-5),error,-total,ms,g["dte"],c,p,cm,pm))
    if not pairs:return None
    pairs.sort(key=lambda x:(x[0],x[1],x[2]))
    _,error,neg_total,ms,dte,c,p,cm,pm=pairs[0]
    return {"maturity":ms,"dte":dte,"call":c,"put":p,
            "call_m":cm,"put_m":pm,"combined":-neg_total,"error":error}

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
      "worst_final_yen":round(min(finals),2)
    }

def main():
    daily=load(); dates=sorted(daily); rows=[]
    for day in dates:
        sel=choose(day,daily[day])
        if not sel:continue
        cost=sel["combined"]*MULT
        cash=START-cost
        if cash<FLOOR:continue
        marks=[]
        for d in dates:
            if d<=day or d>day+timedelta(days=7):continue
            ob=daily[d]["options"]
            c=ob.get(sel["call"]["code"]); p=ob.get(sel["put"]["code"])
            value=cash
            if c:value+=c["premium"]*MULT
            if p:value+=p["premium"]*MULT
            marks.append((d,value))
        if not marks:continue
        best=max(marks,key=lambda x:x[1]); last=marks[-1]
        rows.append({
          "entry_date":day.strftime("%Y%m%d"),"maturity":sel["maturity"],"dte":sel["dte"],
          "entry_cost_yen":round(cost,2),"cash_left_yen":round(cash,2),
          "call":{"code":sel["call"]["code"],"premium":sel["call"]["premium"],
                  "strike":sel["call"]["strike"],"moneyness_pct":round(sel["call_m"]*100,4)},
          "put":{"code":sel["put"]["code"],"premium":sel["put"]["premium"],
                 "strike":sel["put"]["strike"],"moneyness_pct":round(sel["put_m"]*100,4)},
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
      "rule":{"cash_floor_yen":FLOOR,"max_option_cost_yen":MAX_COMBINED*MULT,
              "leg_premium_range":[P_MIN,P_MAX],"same_maturity":True,
              "dte_days":[4,7],"target_otm_pct":TARGET_M*100},
      "all":summarize(rows),"first_half":summarize(first),
      "second_half":summarize(second),"non_overlapping":summarize(non),
      "rows":rows
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
