"""Scheduled-event NK225 mini-option strangle check using JPX actual closes.

Event entry dates are pre-specified from official calendars, independent of
market outcomes:
- FOMC: 2026-07-29, 2026-09-16 (Japan close before US decision)
- BOJ: 2026-07-30, 2026-09-17 (business-day close before meeting decision day)
- US Employment Situation: 2026-08-07, 2026-09-04 (Japan close before 08:30 ET release)
- US CPI: 2026-08-12, 2026-09-11 (Japan close before 08:30 ET release)

Rule: nearest maturity 2-7 calendar days away, OTM call+put, each premium >=10,
combined premium <=100 JPY (= <=10,000 JPY for one mini-option contract each).
Choose the pair spending the most of the budget, ties by total strike distance.
Track later actual daily closes for up to 7 calendar days.

Research only. Closing prices do not guarantee executable fills.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-jpx-event-strangle/1.0"
PRODUCT="NK225MWE"
START=10_000.0; TARGET=50_000.0; FLOOR=5_000.0
EVENTS={
 "20260729":"FOMC",
 "20260730":"BOJ",
 "20260807":"US_EMPLOYMENT",
 "20260812":"US_CPI",
 "20260904":"US_EMPLOYMENT",
 "20260911":"US_CPI",
 "20260916":"FOMC",
 "20260917":"BOJ",
}

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
    for md,ms in mats:
        calls=[o for o in opts if o["maturity"]==ms and o["side"]=="call" and
               o["premium"]>=10 and o["strike"] is not None and o["strike"]>=u]
        puts=[o for o in opts if o["maturity"]==ms and o["side"]=="put" and
              o["premium"]>=10 and o["strike"] is not None and o["strike"]<=u]
        pairs=[]
        for c in calls:
            for p in puts:
                total=c["premium"]+p["premium"]
                if total<=100:
                    dist=abs(c["strike"]-u)+abs(p["strike"]-u)
                    pairs.append((total,-dist,c,p))
        if pairs:
            pairs.sort(key=lambda x:(x[0],x[1]),reverse=True)
            total,_,c,p=pairs[0]
            return {"maturity":ms,"call":c,"put":p,"combined_premium":total}
    return None

def main():
    daily=load(); dates=sorted(daily); campaigns=[]
    missing=[]
    for ds,label in EVENTS.items():
        day=datetime.strptime(ds,"%Y%m%d").date()
        if day not in daily:
            missing.append({"date":ds,"event":label,"reason":"NO_JPX_FILE"}); continue
        pair=choose(day,daily[day])
        if not pair:
            missing.append({"date":ds,"event":label,"reason":"NO_PAIR_UNDER_100"}); continue
        cost=pair["combined_premium"]*100.0
        cash=START-cost
        deadline=day+timedelta(days=7)
        marks=[]
        for d in dates:
            if d<=day or d>deadline:continue
            ob=daily[d]["options"]
            c=ob.get(pair["call"]["code"]); p=ob.get(pair["put"]["code"])
            if c and p:
                val=cash+(c["premium"]+p["premium"])*100.0
                marks.append({"date":d.strftime("%Y%m%d"),"value_yen":val})
        if not marks:
            missing.append({"date":ds,"event":label,"reason":"NO_LATER_COMMON_CLOSE"}); continue
        best=max(marks,key=lambda x:x["value_yen"]); last=marks[-1]
        campaigns.append({
          "entry_date":ds,"event":label,"maturity":pair["maturity"],
          "underlying":daily[day]["underlying"],
          "call_code":pair["call"]["code"],"call_strike":pair["call"]["strike"],
          "call_entry_premium":pair["call"]["premium"],
          "put_code":pair["put"]["code"],"put_strike":pair["put"]["strike"],
          "put_entry_premium":pair["put"]["premium"],
          "entry_cost_yen":round(cost,2),"cash_left_yen":round(cash,2),
          "best_date":best["date"],"best_value_yen":round(best["value_yen"],2),
          "target_hit":best["value_yen"]>=TARGET,
          "final_date":last["date"],"final_value_yen":round(last["value_yen"],2),
        })
    n=len(campaigns)
    finals=sorted(x["final_value_yen"] for x in campaigns)
    return {
      "paper_only":True,
      "source":"JPX actual daily NK225 mini-option closes",
      "scheduled_events_requested":len(EVENTS),
      "campaigns":n,
      "missing":missing,
      "target_hits":sum(x["target_hit"] for x in campaigns),
      "target_rate_pct":round(100*sum(x["target_hit"] for x in campaigns)/n,4) if n else 0,
      "best_at_least_20000_rate_pct":round(100*sum(x["best_value_yen"]>=20000 for x in campaigns)/n,4) if n else 0,
      "final_below_5000_rate_pct":round(100*sum(x["final_value_yen"]<FLOOR for x in campaigns)/n,4) if n else 0,
      "median_final_yen":round(finals[n//2] if n%2 else (finals[n//2-1]+finals[n//2])/2,2) if n else None,
      "campaign_rows":campaigns,
    }

if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
