"""Frozen event-gated NK225 mini-option validation.

Rule derived once from first-half discovery, then frozen:
- Gate: underlying previous 2-business-day return >= +1.0%.
- Direction: opposite of the most recent 1-business-day return
  (prev day up -> buy put; prev day down -> buy call).
- Current-day entry at actual option close.
- OTM only, moneyness <= 6%, DTE 2-4 calendar days.
- Actual premium 50-100 JPY; choose closest to 75 JPY, tie by moneyness.
- One contract; unused part of 10,000 JPY remains cash.
- Track same contract for up to 7 calendar days using later actual daily closes.

The second half of JPX's 50 published business days is the reserved validation set.
Research only; closing prices do not guarantee executable fills.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-jpx-event-gate/1.0"
PRODUCT="NK225MWE"
START=10_000.0; TARGET=50_000.0; FLOOR=5_000.0
P_MIN=50.0; P_MAX=100.0; P_TARGET=75.0
GATE_2D=0.01
MAX_MONEYNESS=0.06
MIN_DTE=2; MAX_DTE=4

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
        options={}; underlying=None
        for r in rows:
            if len(r)<17 or r[0].strip()!=PRODUCT:continue
            strike=num(r[3]); u=num(r[15]); maturity=r[2].strip()
            if u is not None:underlying=u
            for side,ci,pi in (("put",5,6),("call",10,11)):
                code=r[ci].strip(); p=num(r[pi])
                if code and p is not None and p>0:
                    options[code]={"code":code,"side":side,"premium":p,
                                   "strike":strike,"maturity":maturity}
        daily[day]={"underlying":underlying,"options":options}
    return daily

def choose(day,book,side):
    u=book["underlying"]
    if u is None:return None
    cands=[]
    for o in book["options"].values():
        if o["side"]!=side or o["strike"] is None:continue
        if not (P_MIN<=o["premium"]<=P_MAX):continue
        if side=="call":
            if o["strike"]<u:continue
            m=o["strike"]/u-1.0
        else:
            if o["strike"]>u:continue
            m=u/o["strike"]-1.0
        if m<0 or m>MAX_MONEYNESS:continue
        try:md=datetime.strptime(o["maturity"],"%Y%m%d").date()
        except:continue
        dte=(md-day).days
        if not (MIN_DTE<=dte<=MAX_DTE):continue
        cands.append((abs(o["premium"]-P_TARGET),m,dte,o))
    if not cands:return None
    cands.sort(key=lambda x:(x[0],x[1],x[2]))
    return cands[0][3]

def evaluate(daily,dates,indexes):
    rows=[]
    for i in indexes:
        if i<3:continue
        day=dates[i]
        p1=daily[dates[i-1]]["underlying"]
        p2=daily[dates[i-2]]["underlying"]
        p3=daily[dates[i-3]]["underlying"]
        if None in (p1,p2,p3) or p3<=0 or p2<=0:continue
        two_day=p1/p3-1.0
        one_day=p1/p2-1.0
        if two_day<GATE_2D or one_day==0:continue
        side="put" if one_day>0 else "call"
        o=choose(day,daily[day],side)
        if not o:continue
        cost=o["premium"]*100.0
        if cost>START:continue
        cash=START-cost
        deadline=day+timedelta(days=7)
        marks=[]
        for d in dates:
            if d<=day or d>deadline:continue
            x=daily[d]["options"].get(o["code"])
            if x:
                marks.append((d,cash+x["premium"]*100.0,x["premium"]))
        if not marks:continue
        best=max(marks,key=lambda x:x[1]); last=marks[-1]
        rows.append({
          "entry_date":day.strftime("%Y%m%d"),"side":side,
          "two_day_signal_pct":round(two_day*100,4),
          "one_day_signal_pct":round(one_day*100,4),
          "code":o["code"],"maturity":o["maturity"],"strike":o["strike"],
          "underlying":daily[day]["underlying"],
          "entry_premium":o["premium"],"entry_cost_yen":round(cost,2),
          "cash_left_yen":round(cash,2),
          "best_date":best[0].strftime("%Y%m%d"),
          "best_value_yen":round(best[1],2),
          "target_hit":best[1]>=TARGET,
          "final_date":last[0].strftime("%Y%m%d"),
          "final_value_yen":round(last[1],2),
        })
    return rows

def summary(rows):
    n=len(rows)
    if not n:return {"events":0}
    finals=sorted(r["final_value_yen"] for r in rows)
    return {
      "events":n,
      "target_hits":sum(r["target_hit"] for r in rows),
      "target_rate_pct":round(100*sum(r["target_hit"] for r in rows)/n,4),
      "best_at_least_20000_rate_pct":round(100*sum(r["best_value_yen"]>=20_000 for r in rows)/n,4),
      "final_below_5000_rate_pct":round(100*sum(r["final_value_yen"]<FLOOR for r in rows)/n,4),
      "final_at_least_10000_rate_pct":round(100*sum(r["final_value_yen"]>=START for r in rows)/n,4),
      "median_final_yen":round(finals[n//2] if n%2 else (finals[n//2-1]+finals[n//2])/2,2),
      "best_value_yen":round(max(r["best_value_yen"] for r in rows),2),
      "worst_final_yen":round(min(finals),2),
    }

def main():
    daily=load(); dates=sorted(daily)
    split=len(dates)//2
    train=evaluate(daily,dates,range(0,split))
    valid=evaluate(daily,dates,range(split,len(dates)))
    return {
      "paper_only":True,
      "source":"JPX actual daily NK225 mini-option closes",
      "frozen_rule":{
        "gate_prev_2_business_day_return_pct":1.0,
        "direction":"opposite previous 1-business-day move",
        "dte_calendar_days":[MIN_DTE,MAX_DTE],
        "otm_moneyness_max_pct":MAX_MONEYNESS*100,
        "premium_range_yen":[P_MIN,P_MAX],
        "premium_target_yen":P_TARGET,
        "one_contract":True,
      },
      "discovery_half_check":summary(train),
      "reserved_second_half_validation":summary(valid),
      "validation_rows":valid,
    }

if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
