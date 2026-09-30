"""Half-risk NK225 mini-option strangle check.

Fixed rule:
- One OTM call + one OTM put, same nearest maturity 2-7 calendar days away.
- Each leg actual closing premium >= 10 JPY.
- Combined premium <= 50 JPY, so max purchase cost <= 5,000 JPY.
- Remaining cash (>=5,000 JPY) stays untouched.
- Choose the pair spending the most of the 50 JPY budget, ties by total strike distance.
- Track same two option codes for up to 7 calendar days using actual JPX closes.

Research only. Daily closing prices do not guarantee executable fills.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-jpx-half-risk-strangle/1.0"
PRODUCT="NK225MWE"
START=10_000.0; TARGET=50_000.0; FLOOR=5_000.0
MIN_LEG=10.0; MAX_COMBINED=50.0; MULT=100.0

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
        options={}; u=None
        for r in rows:
            if len(r)<17 or r[0].strip()!=PRODUCT: continue
            strike=num(r[3]); uu=num(r[15]); maturity=r[2].strip()
            if uu is not None:u=uu
            for side,ci,pi in (("put",5,6),("call",10,11)):
                code=r[ci].strip(); p=num(r[pi])
                if code and p is not None and p>0:
                    options[code]={"code":code,"side":side,"premium":p,
                                   "strike":strike,"maturity":maturity}
        daily[day]={"underlying":u,"options":options}
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
        calls=[o for o in opts if o["maturity"]==ms and o["side"]=="call" and
               o["premium"]>=MIN_LEG and o["strike"] is not None and o["strike"]>=u]
        puts=[o for o in opts if o["maturity"]==ms and o["side"]=="put" and
              o["premium"]>=MIN_LEG and o["strike"] is not None and o["strike"]<=u]
        pairs=[]
        for c in calls:
            for p in puts:
                total=c["premium"]+p["premium"]
                if total<=MAX_COMBINED:
                    dist=abs(c["strike"]-u)+abs(p["strike"]-u)
                    pairs.append((total,-dist,c,p))
        if pairs:
            pairs.sort(key=lambda x:(x[0],x[1]),reverse=True)
            total,_,c,p=pairs[0]
            return {"maturity":ms,"call":c,"put":p,"combined":total}
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
        pair=choose(day,daily[day])
        if not pair:continue
        cost=pair["combined"]*MULT; cash=START-cost
        if cash<FLOOR:continue
        deadline=day+timedelta(days=7); marks=[]
        for d in dates:
            if d<=day or d>deadline:continue
            ob=daily[d]["options"]
            c=ob.get(pair["call"]["code"]); p=ob.get(pair["put"]["code"])
            if c and p:
                marks.append((d,cash+(c["premium"]+p["premium"])*MULT))
        if not marks:continue
        best=max(marks,key=lambda x:x[1]); last=marks[-1]
        rows.append({
          "entry_date":day.strftime("%Y%m%d"),"maturity":pair["maturity"],
          "underlying":daily[day]["underlying"],
          "entry_cost_yen":round(cost,2),"cash_left_yen":round(cash,2),
          "call_code":pair["call"]["code"],"call_premium":pair["call"]["premium"],
          "call_strike":pair["call"]["strike"],
          "put_code":pair["put"]["code"],"put_premium":pair["put"]["premium"],
          "put_strike":pair["put"]["strike"],
          "best_date":best[0].strftime("%Y%m%d"),"best_value_yen":round(best[1],2),
          "target_hit":best[1]>=TARGET,
          "final_date":last[0].strftime("%Y%m%d"),"final_value_yen":round(last[1],2),
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
      "rule":{"same_maturity":True,"dte_days":[2,7],"min_leg_premium":MIN_LEG,
              "max_combined_premium":MAX_COMBINED,"max_cost_yen":MAX_COMBINED*MULT,
              "minimum_cash_left_yen":FLOOR},
      "all":summarize(rows),"first_half":summarize(first),
      "second_half":summarize(second),"non_overlapping":summarize(non),
      "rows":rows
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
