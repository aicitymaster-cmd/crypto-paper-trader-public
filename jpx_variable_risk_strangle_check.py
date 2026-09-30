"""Sequential 7-day ultra-cheap NK225 mini-option campaign.

Research only. Uses JPX actual daily closing premiums.

Account rules:
- Start 10,000 JPY.
- Across each 7-calendar-day campaign, spend at most 5,000 JPY total premium.
- Buy at most one new option per JPX business day.
- Eligible contract: NK225 mini option, OTM, premium 10-15 JPY
  (=1,000-1,500 JPY), nearest maturity 2-7 calendar days away.
- Unspent cash remains cash.
- Existing holdings are marked at later actual JPX closes; missing/expired legs
  are valued at zero.
- A campaign succeeds if marked account equity reaches >=50,000 JPY at a daily close.

Three rules are pre-registered and compared without parameter tuning:
1) contrarian: previous underlying day up -> buy put; down -> buy call
2) momentum: previous underlying day up -> buy call; down -> buy put
3) alternating: alternate call/put by number of purchases, starting call

Selection inside a side: choose the cheapest eligible contract; tie -> closest
OTM strike. Daily closing prices do not guarantee executable fills.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-sequential-campaign/1.0"
PRODUCT="NK225MWE"
START=10_000.0
TARGET=50_000.0
FLOOR=5_000.0
TOTAL_RISK_BUDGET=5_000.0
P_MIN=10.0
P_MAX=15.0
MULT=100.0
RULES=("contrarian","momentum","alternating")

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
    cands=[]
    for o in book["options"].values():
        if o["side"]!=side or o["strike"] is None or not(P_MIN<=o["premium"]<=P_MAX):
            continue
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
        cands.append((o["premium"],m,dte,o))
    if not cands:return None
    cands.sort(key=lambda x:(x[0],x[1],x[2]))
    return cands[0][3]

def side_for(rule,daily,dates,i,purchase_count):
    if rule=="alternating":
        return "call" if purchase_count%2==0 else "put"
    if i<1:return None
    prev=daily[dates[i-1]]["underlying"]
    cur=daily[dates[i]]["underlying"]
    # At the current day's close, only prior-day-to-current close is known.
    # Entry is modelled at this same published close, so this is an end-of-day
    # research convention rather than an intraday executable signal.
    if prev is None or cur is None or prev==cur:return None
    up=cur>prev
    if rule=="momentum":
        return "call" if up else "put"
    return "put" if up else "call"

def marked_value(day,daily,cash,holdings):
    total=cash
    ob=daily[day]["options"]
    for h in holdings:
        x=ob.get(h["code"])
        if x:
            total+=x["premium"]*MULT
    return total

def run_campaign(rule,daily,dates,start_idx):
    start_day=dates[start_idx]
    end_day=start_day+timedelta(days=7)
    cash=START
    spent=0.0
    holdings=[]
    purchases=[]
    best=START
    best_day=start_day
    target_hit=False
    campaign_days=[(i,d) for i,d in enumerate(dates) if start_day<=d<end_day]
    for i,day in campaign_days:
        side=side_for(rule,daily,dates,i,len(purchases))
        if side:
            o=choose(day,daily[day],side)
            if o:
                cost=o["premium"]*MULT
                if spent+cost<=TOTAL_RISK_BUDGET and cash>=cost:
                    cash-=cost
                    spent+=cost
                    holdings.append({"code":o["code"],"side":side})
                    purchases.append({
                      "date":day.strftime("%Y%m%d"),"side":side,"code":o["code"],
                      "premium":o["premium"],"cost_yen":cost,"strike":o["strike"],
                      "maturity":o["maturity"]
                    })
        eq=marked_value(day,daily,cash,holdings)
        if eq>best:
            best=eq; best_day=day
        if eq>=TARGET:
            target_hit=True
            break
    last_day=campaign_days[-1][1] if campaign_days else start_day
    final=marked_value(last_day,daily,cash,holdings)
    return {
      "start":start_day.strftime("%Y%m%d"),
      "end":last_day.strftime("%Y%m%d"),
      "rule":rule,
      "spent_yen":round(spent,2),
      "purchases":purchases,
      "best_value_yen":round(best,2),
      "best_date":best_day.strftime("%Y%m%d"),
      "target_hit":target_hit,
      "final_value_yen":round(final,2)
    }

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
    daily=load(); dates=sorted(daily)
    all_rows={}
    for rule in RULES:
        rolling=[]
        for i,day in enumerate(dates):
            if day+timedelta(days=7)>dates[-1]+timedelta(days=1):
                continue
            rolling.append(run_campaign(rule,daily,dates,i))
        non=[]
        next_allowed=None
        for r in rolling:
            d=datetime.strptime(r["start"],"%Y%m%d").date()
            if next_allowed is None or d>=next_allowed:
                non.append(r)
                next_allowed=d+timedelta(days=7)
        split=len(rolling)//2
        all_rows[rule]={
          "rolling":summarize(rolling),
          "first_half":summarize(rolling[:split]),
          "second_half":summarize(rolling[split:]),
          "non_overlapping":summarize(non),
          "top_campaigns":sorted(rolling,key=lambda x:x["best_value_yen"],reverse=True)[:10]
        }
    print(json.dumps({
      "paper_only":True,
      "source":"JPX actual daily NK225 mini-option closes",
      "campaign_rule":{
        "calendar_days":7,
        "start_yen":START,
        "total_premium_budget_yen":TOTAL_RISK_BUDGET,
        "max_one_new_contract_per_business_day":True,
        "eligible_premium_yen":[P_MIN,P_MAX],
        "entry_cost_yen":[P_MIN*MULT,P_MAX*MULT],
        "dte_calendar_days":[2,7],
        "rules":list(RULES)
      },
      "results":all_rows
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
