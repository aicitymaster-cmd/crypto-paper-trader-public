"""Independent candidate-B screen: CALL-only, non-Tuesday.

Pre-registered variants only:
- Monday, DTE 2-4
- Monday, DTE 5-7
- Wednesday, DTE 2-4
- Wednesday, DTE 5-7

Common mechanics:
- NK225 mini CALL only, OTM
- premium 10-30 JPY
- up to 4 distinct strikes
- deploy up to 10,000 JPY
- exit at first later daily close where account >=50,000 JPY
- otherwise mark through 7 calendar days

Archive: 2025-12-01 through 2026-09-30.
For robustness, results are shown for:
- early period: 2025-12 through 2026-04
- later period: 2026-05 through 2026-09

Research only. Daily closes do not guarantee executable fills.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

BASE="https://www.jpx.co.jp/automation/markets/derivatives/option-price/files/"
UA="crypto-paper-trader-public-candidate-b-call/1.0"
PRODUCT="NK225MWE"
START=10_000.0
TARGET=50_000.0
P_MIN=10.0
P_MAX=30.0
MULT=100.0
MAX_LEGS=4
START_DATE=date(2025,12,1)
END_DATE=date(2026,9,30)
LATE_START=date(2026,5,1)
VARIANTS=(
 ("mon_dte2_4",0,2,4),
 ("mon_dte5_7",0,5,7),
 ("wed_dte2_4",2,2,4),
 ("wed_dte5_7",2,5,7),
)

def weekdays(a,b):
    d=a
    while d<=b:
        if d.weekday()<5: yield d
        d+=timedelta(days=1)

def fetch_day(day):
    ds=day.strftime("%Y%m%d")
    url=f"{BASE}ose{ds}tp.csv"
    req=urllib.request.Request(url,method="GET",headers={"User-Agent":UA,"Accept":"text/csv,*/*"})
    try:
        with urllib.request.urlopen(req,context=ssl.create_default_context(),timeout=15) as resp:
            return day,resp.read(8_000_000),None
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

def parse(body):
    rows=list(csv.reader(io.StringIO(dec(body))))
    opts={}; u=None
    for r in rows:
        if len(r)<17 or r[0].strip()!=PRODUCT:continue
        strike=num(r[3]); uu=num(r[15]); maturity=r[2].strip()
        if uu is not None:u=uu
        code=r[10].strip(); p=num(r[11])
        if code and p is not None and p>0:
            opts[code]={"code":code,"premium":p,"strike":strike,"maturity":maturity}
    if u is None or not opts:return None
    return {"underlying":u,"options":opts}

def load():
    daily={}; errors={}
    days=list(weekdays(START_DATE,END_DATE))
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(fetch_day,d) for d in days]
        for fut in as_completed(futs):
            day,body,err=fut.result()
            if body:
                p=parse(body)
                if p:daily[day]=p
            elif err!="404":
                errors[day.isoformat()]=err
    return daily,errors

def build(day,book,dmin,dmax):
    u=book["underlying"]; xs=[]
    for o in book["options"].values():
        if o["strike"] is None or not(P_MIN<=o["premium"]<=P_MAX):continue
        if o["strike"]<u:continue
        m=o["strike"]/u-1.0
        try:md=datetime.strptime(o["maturity"],"%Y%m%d").date()
        except:continue
        dte=(md-day).days
        if not(dmin<=dte<=dmax):continue
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

def run(day,b,daily,dates):
    marks=[]
    for d in dates:
        if d<=day or d>day+timedelta(days=7):continue
        ob=daily[d]["options"]
        value=b["cash"]
        for leg in b["legs"]:
            x=ob.get(leg["o"]["code"])
            if x:value+=x["premium"]*MULT*leg["qty"]
        marks.append((d,value))
        if value>=TARGET:break
    if not marks:return None
    best=max(marks,key=lambda x:x[1]); last=marks[-1]
    return {
      "entry_date":day.strftime("%Y%m%d"),
      "best_value_yen":round(best[1],2),
      "target_hit":best[1]>=TARGET,
      "exit_value_yen":round(last[1],2),
      "spent_yen":round(b["spent"],2),
      "cash_left_yen":round(b["cash"],2)
    }

def summarize(rows):
    n=len(rows)
    if not n:return {"entries":0}
    exits=sorted(r["exit_value_yen"] for r in rows)
    return {
      "entries":n,
      "target_hits":sum(r["target_hit"] for r in rows),
      "target_rate_pct":round(100*sum(r["target_hit"] for r in rows)/n,4),
      "exit_zero_rate_pct":round(100*sum(r["exit_value_yen"]==0 for r in rows)/n,4),
      "exit_below_5000_rate_pct":round(100*sum(r["exit_value_yen"]<5000 for r in rows)/n,4),
      "median_exit_yen":round(exits[n//2] if n%2 else (exits[n//2-1]+exits[n//2])/2,2),
      "best_value_yen":round(max(r["best_value_yen"] for r in rows),2),
      "worst_exit_yen":round(min(exits),2)
    }

def main():
    daily,errors=load(); dates=sorted(daily)
    out={}
    for name,wd,dmin,dmax in VARIANTS:
        rows=[]
        for day in dates:
            if day.weekday()!=wd:continue
            b=build(day,daily[day],dmin,dmax)
            if not b:continue
            r=run(day,b,daily,dates)
            if r:rows.append(r)
        early=[r for r in rows if datetime.strptime(r["entry_date"],"%Y%m%d").date()<LATE_START]
        late=[r for r in rows if datetime.strptime(r["entry_date"],"%Y%m%d").date()>=LATE_START]
        out[name]={
          "params":{"weekday":wd,"dte":[dmin,dmax],"side":"call","premium":[P_MIN,P_MAX]},
          "all":summarize(rows),
          "early_dec_apr":summarize(early),
          "late_may_sep":summarize(late),
          "hits":[r for r in rows if r["target_hit"]]
        }
    print(json.dumps({
      "paper_only":True,
      "source":"JPX direct daily CSV archive",
      "loaded_business_days":len(dates),
      "non404_errors":errors,
      "candidate_b_variants":out
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
