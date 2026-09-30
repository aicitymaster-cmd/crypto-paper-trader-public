"""Seven-day profit-recycling campaign for ultra-cheap NK225 mini options.

Exploratory research using JPX actual daily closing premiums.

Frozen mechanics:
- Start 10,000 JPY.
- One new OTM option per business day at most.
- Eligible premium 10-15 JPY (=1,000-1,500 JPY), DTE 2-7 days.
- Direction: contrarian to the current day's NK225 close move vs prior business day
  (up day -> put, down day -> call). Entry is modelled at that day's published close.
- Sell any open option at the first later daily close where premium >= 5x entry premium.
  Sale is at the actual published close, not capped at 5x.
- If cash + marked holdings ever reaches >=15,000 JPY, permanently protect 5,000 JPY.
- Protected cash is never reused.
- After protection, new purchases use only unprotected cash.
- Before protection, cumulative initial-premium spending may not exceed 5,000 JPY.
- After a profitable sale, realised profit may be recycled into later purchases.
- Success if total marked equity reaches >=50,000 JPY within the 7-day campaign.

Daily closes do not guarantee executable fills.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-profit-recycle/1.0"
PRODUCT="NK225MWE"
START=10_000.0
TARGET=50_000.0
FLOOR=5_000.0
P_MIN=10.0
P_MAX=15.0
MULT=100.0
INITIAL_RISK_CAP=10_000.0
PROTECT_TRIGGER=1_000_000_000.0
PROTECT_AMOUNT=0.0
TAKE_MULTIPLE=5.0

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

def choose(day,book,side):
    u=book["underlying"]
    if u is None:return None
    xs=[]
    for o in book["options"].values():
        if o["side"]!=side or o["strike"] is None or not(P_MIN<=o["premium"]<=P_MAX):continue
        if side=="call":
            if o["strike"]<u:continue
            m=o["strike"]/u-1.0
        else:
            if o["strike"]>u:continue
            m=u/o["strike"]-1.0
        try:md=datetime.strptime(o["maturity"],"%Y%m%d").date()
        except:continue
        dte=(md-day).days
        if not(2<=dte<=7):continue
        xs.append((o["premium"],m,dte,o))
    if not xs:return None
    xs.sort(key=lambda x:(x[0],x[1],x[2]))
    return xs[0][3]

def mark(day,daily,cash,protected,holdings):
    ob=daily[day]["options"]
    total=cash+protected
    for h in holdings:
        x=ob.get(h["code"])
        if x:total+=x["premium"]*MULT
    return total

def run_campaign(daily,dates,start_idx):
    start_day=dates[start_idx]
    end_day=start_day+timedelta(days=7)
    campaign=[(i,d) for i,d in enumerate(dates) if start_day<=d<end_day]
    if not campaign:return None
    cash=START
    protected=0.0
    holdings=[]
    initial_spent=0.0
    trades=[]
    best=START
    best_day=start_day
    target=False

    for i,day in campaign:
        ob=daily[day]["options"]

        # First, realise winners at actual current close.
        still=[]
        for h in holdings:
            x=ob.get(h["code"])
            if x and x["premium"]>=TAKE_MULTIPLE*h["entry_premium"]:
                proceeds=x["premium"]*MULT
                cash+=proceeds
                trades.append({"type":"sell","date":day.strftime("%Y%m%d"),
                               "code":h["code"],"premium":x["premium"],
                               "proceeds_yen":proceeds,
                               "multiple":round(x["premium"]/h["entry_premium"],4)})
            else:
                still.append(h)
        holdings=still

        eq=mark(day,daily,cash,protected,holdings)
        if protected<PROTECT_AMOUNT and eq>=PROTECT_TRIGGER and cash>=PROTECT_AMOUNT:
            protected=PROTECT_AMOUNT
            cash-=PROTECT_AMOUNT
            trades.append({"type":"protect","date":day.strftime("%Y%m%d"),
                           "amount_yen":PROTECT_AMOUNT})

        # Contrarian side from current close vs previous business-day close.
        side=None
        if i>=1:
            cur=daily[day]["underlying"]
            prev=daily[dates[i-1]]["underlying"]
            if cur is not None and prev is not None and cur!=prev:
                side="put" if cur>prev else "call"

        if side:
            o=choose(day,daily[day],side)
            if o:
                cost=o["premium"]*MULT
                can_use_initial=(protected>0 or initial_spent+cost<=INITIAL_RISK_CAP)
                if can_use_initial and cash>=cost:
                    cash-=cost
                    if protected==0:initial_spent+=cost
                    holdings.append({"code":o["code"],"entry_premium":o["premium"],
                                     "side":side,"entry_date":day})
                    trades.append({"type":"buy","date":day.strftime("%Y%m%d"),
                                   "side":side,"code":o["code"],"premium":o["premium"],
                                   "cost_yen":cost})

        eq=mark(day,daily,cash,protected,holdings)
        if eq>best:
            best=eq; best_day=day
        if eq>=TARGET:
            target=True
            break

    last_day=campaign[-1][1]
    final=mark(last_day,daily,cash,protected,holdings)
    return {"start":start_day.strftime("%Y%m%d"),"end":last_day.strftime("%Y%m%d"),
            "best_value_yen":round(best,2),"best_date":best_day.strftime("%Y%m%d"),
            "target_hit":target,"final_value_yen":round(final,2),
            "protected_yen":round(protected,2),"trades":trades}

def summarize(rows):
    n=len(rows)
    if not n:return {"campaigns":0}
    finals=sorted(r["final_value_yen"] for r in rows)
    return {"campaigns":n,
      "target_hits":sum(r["target_hit"] for r in rows),
      "target_rate_pct":round(100*sum(r["target_hit"] for r in rows)/n,4),
      "best_at_least_20000_rate_pct":round(100*sum(r["best_value_yen"]>=20000 for r in rows)/n,4),
      "final_below_5000_rate_pct":round(100*sum(r["final_value_yen"]<FLOOR for r in rows)/n,4),
      "final_at_least_10000_rate_pct":round(100*sum(r["final_value_yen"]>=START for r in rows)/n,4),
      "median_final_yen":round(finals[n//2] if n%2 else (finals[n//2-1]+finals[n//2])/2,2),
      "best_value_yen":round(max(r["best_value_yen"] for r in rows),2),
      "worst_final_yen":round(min(finals),2)}

def main():
    daily=load(); dates=sorted(daily)
    rows=[]
    for i,day in enumerate(dates):
        if day+timedelta(days=7)>dates[-1]+timedelta(days=1):continue
        r=run_campaign(daily,dates,i)
        if r:rows.append(r)
    split=len(rows)//2
    non=[]; nxt=None
    for r in rows:
        d=datetime.strptime(r["start"],"%Y%m%d").date()
        if nxt is None or d>=nxt:
            non.append(r); nxt=d+timedelta(days=7)
    print(json.dumps({
      "paper_only":True,
      "source":"JPX actual daily NK225 mini-option closes",
      "rule":{"campaign_days":7,"entry_premium_yen":[P_MIN,P_MAX],
              "initial_risk_cap_yen":INITIAL_RISK_CAP,
              "take_profit_multiple":TAKE_MULTIPLE,
              "protect_trigger_yen":None,
              "protect_amount_yen":0.0,
              "direction":"contrarian current close move"},
      "rolling":summarize(rows),
      "first_half":summarize(rows[:split]),
      "second_half":summarize(rows[split:]),
      "non_overlapping":summarize(non),
      "top_campaigns":sorted(rows,key=lambda x:x["best_value_yen"],reverse=True)[:12]
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
