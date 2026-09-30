"""Longer JPX archive validation for the focused full-risk put basket.

Uses direct JPX daily CSV archive URLs from 2026-01-01 through 2026-09-30.
The strategy is frozen BEFORE this longer validation:
- PUT only
- OTM
- DTE 2-4 calendar days
- actual premium 10-30 JPY
- up to 4 distinct strikes
- deploy up to full 10,000 JPY
- exit at first later daily close where account >=50,000 JPY
- otherwise mark through 7 calendar days

Important evaluation split:
- 2026-01-01 through 2026-06-30: older holdout, not used in strategy discovery
- 2026-07-01 through 2026-09-30: discovery-era / previously inspected period

Research only. Daily closes do not guarantee executable fills.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

BASE="https://www.jpx.co.jp/automation/markets/derivatives/option-price/files/"
UA="crypto-paper-trader-public-long-archive-put/1.0"
PRODUCT="NK225MWE"
START=10_000.0
TARGET=50_000.0
P_MIN=10.0
P_MAX=30.0
DTE_MIN=2
DTE_MAX=4
MULT=100.0
MAX_LEGS=4
START_DATE=date(2026,1,1)
END_DATE=date(2026,9,30)
HOLDOUT_END=date(2026,6,30)

def weekdays(a,b):
    d=a
    while d<=b:
        if d.weekday()<5:
            yield d
        d+=timedelta(days=1)

def fetch_day(day):
    ds=day.strftime("%Y%m%d")
    url=f"{BASE}ose{ds}tp.csv"
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Accept":"text/csv,*/*"})
    try:
        with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=15) as resp:
            body=resp.read(8_000_000)
        return day,body,None
    except urllib.error.HTTPError as e:
        if e.code==404:return day,None,"404"
        return day,None,f"HTTP_{e.code}"
    except Exception as e:
        return day,None,f"{type(e).__name__}:{e}"

def dec(body):
    for enc in ("utf-8-sig","shift_jis","cp932"):
        try:return body.decode(enc)
        except UnicodeDecodeError:pass
    return body.decode("utf-8","replace")

def num(s):
    try:return float((s or "").strip())
    except:return None

def parse(day,body):
    rows=list(csv.reader(io.StringIO(dec(body))))
    opts={}; u=None
    for r in rows:
        if len(r)<17 or r[0].strip()!=PRODUCT:continue
        strike=num(r[3]); uu=num(r[15]); maturity=r[2].strip()
        if uu is not None:u=uu
        code=r[5].strip(); p=num(r[6])
        if code and p is not None and p>0:
            opts[code]={"code":code,"premium":p,"strike":strike,"maturity":maturity}
    if u is None or not opts:return None
    return {"underlying":u,"options":opts}

def load():
    daily={}
    errors={}
    days=list(weekdays(START_DATE,END_DATE))
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs={ex.submit(fetch_day,d):d for d in days}
        for fut in as_completed(futs):
            day,body,err=fut.result()
            if body:
                parsed=parse(day,body)
                if parsed:daily[day]=parsed
                else:errors[day.isoformat()]="NO_MINI_DATA"
            elif err!="404":
                errors[day.isoformat()]=err
    return daily,errors

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
    return {"entry_date":day.strftime("%Y%m%d"),
      "spent_yen":round(basket["spent"],2),"cash_left_yen":round(basket["cash"],2),
      "legs":[{"code":x["o"]["code"],"premium":x["o"]["premium"],
               "strike":x["o"]["strike"],"maturity":x["o"]["maturity"],
               "qty":x["qty"]} for x in basket["legs"]],
      "best_date":best[0].strftime("%Y%m%d"),"best_value_yen":round(best[1],2),
      "target_hit":best[1]>=TARGET,
      "exit_date":last[0].strftime("%Y%m%d"),"exit_value_yen":round(last[1],2)}

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

def nonoverlap(rows):
    out=[]; nxt=None
    for r in rows:
        d=datetime.strptime(r["entry_date"],"%Y%m%d").date()
        if nxt is None or d>=nxt:
            out.append(r); nxt=d+timedelta(days=7)
    return out

def main():
    daily,errors=load()
    dates=sorted(daily)
    rows=[]
    for day in dates:
        b=build(day,daily[day])
        if not b:continue
        r=run(day,b,daily,dates)
        if r:rows.append(r)
    hold=[r for r in rows if datetime.strptime(r["entry_date"],"%Y%m%d").date()<=HOLDOUT_END]
    disc=[r for r in rows if datetime.strptime(r["entry_date"],"%Y%m%d").date()>HOLDOUT_END]
    years={}
    weekday_groups={str(i):[] for i in range(5)}
    expiry_weekday_groups={str(i):[] for i in range(5)}
    for r in rows:
        m=r["entry_date"][:6]
        years.setdefault(m,[]).append(r)
        ed=datetime.strptime(r["entry_date"],"%Y%m%d").date()
        weekday_groups[str(ed.weekday())].append(r)
        if r["legs"]:
            md=datetime.strptime(r["legs"][0]["maturity"],"%Y%m%d").date()
            expiry_weekday_groups[str(md.weekday())].append(r)
    mon_tue=[r for r in rows if datetime.strptime(r["entry_date"],"%Y%m%d").date().weekday() in (0,1)]
    hold_mon_tue=[r for r in hold if datetime.strptime(r["entry_date"],"%Y%m%d").date().weekday() in (0,1)]
    hold_weekday_groups={str(i):[] for i in range(5)}
    disc_weekday_groups={str(i):[] for i in range(5)}
    for r in hold:
        d=datetime.strptime(r["entry_date"],"%Y%m%d").date()
        hold_weekday_groups[str(d.weekday())].append(r)
    for r in disc:
        d=datetime.strptime(r["entry_date"],"%Y%m%d").date()
        disc_weekday_groups[str(d.weekday())].append(r)
    print(json.dumps({
      "paper_only":True,
      "source":"JPX direct daily CSV archive",
      "archive_start":START_DATE.isoformat(),"archive_end":END_DATE.isoformat(),
      "loaded_business_days":len(dates),"non404_errors":errors,
      "rule":{"side":"put","dte":[DTE_MIN,DTE_MAX],"premium":[P_MIN,P_MAX],
              "max_distinct_strikes":MAX_LEGS,"start_yen":START,
              "target_exit_yen":TARGET,"full_loss_allowed":True},
      "older_holdout_jan_jun":summarize(hold),
      "older_holdout_nonoverlap":summarize(nonoverlap(hold)),
      "discovery_era_jul_sep":summarize(disc),
      "all_jan_sep":summarize(rows),
      "all_nonoverlap":summarize(nonoverlap(rows)),
      "by_month":{m:summarize(v) for m,v in sorted(years.items())},
      "by_entry_weekday":{"0_mon":summarize(weekday_groups["0"]),
                          "1_tue":summarize(weekday_groups["1"]),
                          "2_wed":summarize(weekday_groups["2"]),
                          "3_thu":summarize(weekday_groups["3"]),
                          "4_fri":summarize(weekday_groups["4"])},
      "by_expiry_weekday":{"0_mon":summarize(expiry_weekday_groups["0"]),
                           "1_tue":summarize(expiry_weekday_groups["1"]),
                           "2_wed":summarize(expiry_weekday_groups["2"]),
                           "3_thu":summarize(expiry_weekday_groups["3"]),
                           "4_fri":summarize(expiry_weekday_groups["4"])},
      "entry_mon_or_tue":summarize(mon_tue),
      "holdout_jan_jun_entry_mon_or_tue":summarize(hold_mon_tue),
      "holdout_jan_jun_by_weekday":{"0_mon":summarize(hold_weekday_groups["0"]),
                                    "1_tue":summarize(hold_weekday_groups["1"]),
                                    "2_wed":summarize(hold_weekday_groups["2"])},
      "discovery_jul_sep_by_weekday":{"0_mon":summarize(disc_weekday_groups["0"]),
                                      "1_tue":summarize(disc_weekday_groups["1"]),
                                      "2_wed":summarize(disc_weekday_groups["2"])},
      "holdout_hits":[r for r in hold if r["target_hit"]],
      "all_hits":[r for r in rows if r["target_hit"]]
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
