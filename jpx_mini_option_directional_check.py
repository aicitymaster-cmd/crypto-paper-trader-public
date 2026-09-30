"""No-lookahead directional Nikkei 225 Mini Options screen.

Fixed rule:
- Direction uses ONLY underlying closes through the previous business day:
  prior close vs the close three business days earlier. Up -> call, down -> put.
- Entry at current day's actual option closing premium.
- Nearest maturity 2-7 calendar days away.
- OTM option on chosen side with actual premium 50-100 JPY; choose premium
  closest to 75 JPY, tie by strike closest to underlying.
- One contract only; unused part of 10,000 JPY stays cash.
- Track same option's later actual daily closes for up to 7 calendar days.

Exploratory research only. Daily closes do not guarantee executable fills.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-jpx-directional/1.0"
PRODUCT="NK225MWE"
START=10_000.0; TARGET=50_000.0
P_MIN=50.0; P_MAX=100.0; P_TARGET=75.0

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
    candidates=[]
    for o in book["options"].values():
        if o["side"]!=side or o["strike"] is None:continue
        if not (P_MIN<=o["premium"]<=P_MAX):continue
        if side=="call" and o["strike"]<u:continue
        if side=="put" and o["strike"]>u:continue
        try:md=datetime.strptime(o["maturity"],"%Y%m%d").date()
        except:continue
        dd=(md-day).days
        if not (2<=dd<=7):continue
        candidates.append((md,abs(o["premium"]-P_TARGET),abs(o["strike"]-u),o))
    if not candidates:return None
    nearest=min(x[0] for x in candidates)
    same=[x for x in candidates if x[0]==nearest]
    same.sort(key=lambda x:(x[1],x[2]))
    return same[0][3]

def summarize(rows):
    n=len(rows)
    if not n:return {"entries":0}
    finals=sorted(x["final_value_yen"] for x in rows)
    return {
      "entries":n,
      "target_hits":sum(x["target_hit"] for x in rows),
      "target_rate_pct":round(100*sum(x["target_hit"] for x in rows)/n,4),
      "best_at_least_20000_rate_pct":round(100*sum(x["best_value_yen"]>=20_000 for x in rows)/n,4),
      "final_below_5000_rate_pct":round(100*sum(x["final_value_yen"]<5_000 for x in rows)/n,4),
      "final_at_least_10000_rate_pct":round(100*sum(x["final_value_yen"]>=10_000 for x in rows)/n,4),
      "median_final_yen":round(finals[n//2] if n%2 else (finals[n//2-1]+finals[n//2])/2,2),
      "best_value_yen":round(max(x["best_value_yen"] for x in rows),2),
      "worst_final_yen":round(min(finals),2),
    }

def main():
    daily=load(); dates=sorted(daily)
    rows=[]
    for i,day in enumerate(dates):
        if i<3:continue
        # Strict no-lookahead signal: previous close vs three business days before it.
        prev=daily[dates[i-1]]["underlying"]
        old=daily[dates[i-3]]["underlying"]
        if prev is None or old is None or prev==old:continue
        side="call" if prev>old else "put"
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
                marks.append({"date":d,"value":cash+x["premium"]*100.0,
                              "premium":x["premium"]})
        if not marks:continue
        best=max(marks,key=lambda x:x["value"])
        last=marks[-1]
        rows.append({
          "entry_date":day.strftime("%Y%m%d"),"signal_side":side,
          "signal_prev_underlying":prev,"signal_old_underlying":old,
          "underlying_entry":daily[day]["underlying"],
          "code":o["code"],"maturity":o["maturity"],"strike":o["strike"],
          "entry_premium":o["premium"],"entry_cost_yen":round(cost,2),
          "cash_left_yen":round(cash,2),
          "best_date":best["date"].strftime("%Y%m%d"),
          "best_value_yen":round(best["value"],2),
          "target_hit":best["value"]>=TARGET,
          "final_date":last["date"].strftime("%Y%m%d"),
          "final_value_yen":round(last["value"],2),
        })
    n=len(rows); split=n//2
    first=rows[:split]; second=rows[split:]
    # Deterministic non-overlap subset: after taking one entry, skip entry dates
    # until seven calendar days have elapsed.
    non=[]; next_allowed=None
    for r in rows:
        d=datetime.strptime(r["entry_date"],"%Y%m%d").date()
        if next_allowed is None or d>=next_allowed:
            non.append(r); next_allowed=d+timedelta(days=7)
    return {
      "paper_only":True,
      "source":"JPX actual daily mini-option closing premiums",
      "rule":"prior 3-business-day momentum -> one OTM call/put, nearest 2-7d maturity, premium closest to 75 within 50-100",
      "all_entries":summarize(rows),
      "first_half":summarize(first),
      "second_half":summarize(second),
      "non_overlapping_entries":summarize(non),
      "rows":rows,
    }

if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
