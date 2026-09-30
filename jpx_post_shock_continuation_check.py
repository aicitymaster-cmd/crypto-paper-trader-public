"""Post-shock continuation test for NK225 mini options.

Fixed rule, no lookahead:
- If previous business day's NK225 underlying move vs prior business day is
  >= +1.5%, buy one OTM call next business day.
- If <= -1.5%, buy one OTM put next business day.
- DTE 2-7 calendar days.
- OTM moneyness <= 6%.
- Actual closing premium 50-100 JPY; choose closest to 75 JPY, tie by moneyness.
- One contract, unused cash stays in the 10,000 JPY portfolio.
- Track later actual daily closes for up to 7 calendar days.

Research only. Uses JPX actual daily closing premiums; closing prices do not
guarantee executable fills.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-jpx-post-shock/1.0"
PRODUCT="NK225MWE"
START=10_000.0; TARGET=50_000.0; FLOOR=5_000.0
SHOCK=0.015; P_MIN=50.; P_MAX=100.; P_TARGET=75.; MAX_M=0.06

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
            if uu is not None: u=uu
            for side,ci,pi in (("put",5,6),("call",10,11)):
                code=r[ci].strip(); p=num(r[pi])
                if code and p is not None and p>0:
                    options[code]={"code":code,"side":side,"premium":p,"strike":strike,"maturity":maturity}
        daily[day]={"underlying":u,"options":options}
    return daily

def choose(day,book,side):
    u=book["underlying"]
    if u is None:return None
    xs=[]
    for o in book["options"].values():
        if o["side"]!=side or o["strike"] is None or not(P_MIN<=o["premium"]<=P_MAX): continue
        if side=="call":
            if o["strike"]<u: continue
            m=o["strike"]/u-1
        else:
            if o["strike"]>u: continue
            m=u/o["strike"]-1
        if not(0<=m<=MAX_M): continue
        try: md=datetime.strptime(o["maturity"],"%Y%m%d").date()
        except: continue
        dte=(md-day).days
        if not(2<=dte<=7): continue
        xs.append((abs(o["premium"]-P_TARGET),m,dte,o))
    if not xs:return None
    xs.sort(key=lambda x:(x[0],x[1],x[2]))
    return xs[0][3]

def summarize(rows):
    n=len(rows)
    if not n:return {"entries":0}
    finals=sorted(r["final_value_yen"] for r in rows)
    return {
      "entries":n,
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
    for i,day in enumerate(dates):
        if i<2: continue
        p1=daily[dates[i-1]]["underlying"]; p2=daily[dates[i-2]]["underlying"]
        if p1 is None or p2 is None or p2<=0: continue
        move=p1/p2-1
        if move>=SHOCK: side="call"
        elif move<=-SHOCK: side="put"
        else: continue
        o=choose(day,daily[day],side)
        if not o: continue
        cost=o["premium"]*100.; cash=START-cost
        if cash<0:continue
        deadline=day+timedelta(days=7); marks=[]
        for d in dates:
            if d<=day or d>deadline:continue
            x=daily[d]["options"].get(o["code"])
            if x: marks.append((d,cash+x["premium"]*100.))
        if not marks:continue
        best=max(marks,key=lambda x:x[1]); last=marks[-1]
        rows.append({
          "entry_date":day.strftime("%Y%m%d"),"signal_prev_day_pct":round(move*100,4),"side":side,
          "code":o["code"],"maturity":o["maturity"],"strike":o["strike"],
          "entry_premium":o["premium"],"entry_cost_yen":round(cost,2),"cash_left_yen":round(cash,2),
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
      "rule":{"previous_day_shock_abs_pct":SHOCK*100,"direction":"continuation",
              "premium_range":[P_MIN,P_MAX],"premium_target":P_TARGET,
              "dte_days":[2,7],"max_otm_pct":MAX_M*100},
      "all":summarize(rows),"first_half":summarize(first),
      "second_half":summarize(second),"non_overlapping":summarize(non),
      "rows":rows
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
