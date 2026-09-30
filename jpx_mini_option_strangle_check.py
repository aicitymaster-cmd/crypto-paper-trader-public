"""Actual-price Nikkei 225 Mini Options two-leg strangle screening.

For each JPX business day, choose at most one deterministic OTM call+put pair:
- same nearest maturity 2-7 calendar days away
- call strike >= underlying, put strike <= underlying
- each actual close >= 20 JPY
- combined premium <= 100 JPY (<=10,000 JPY total cost)
- among valid pairs for the nearest maturity, spend as much of the 100 JPY
  budget as possible; ties prefer strikes closer to the underlying.

Tracks later dates up to 7 calendar days where BOTH option codes again have
actual closing premiums. Reports the best combined marked value. This is an
exploratory screen using actual daily closes, not an executable recommendation.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-jpx-strangle-research/1.0"
PRODUCT="NK225MWE"
MIN_LEG=20.0
MAX_COMBINED=100.0
CONTRACT_MULTIPLIER=100.0
START=10_000.0
TARGET=50_000.0

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
        m={}
        underlying=None
        for r in rows:
            if len(r)<17 or r[0].strip()!=PRODUCT:continue
            strike=num(r[3]); u=num(r[15]); maturity=r[2].strip()
            if u is not None: underlying=u
            for side,ci,pi in (("put",5,6),("call",10,11)):
                code=r[ci].strip(); p=num(r[pi])
                if code and p is not None and p>0:
                    m[code]={"code":code,"side":side,"premium":p,"strike":strike,
                             "maturity":maturity,"underlying":u}
        daily[day]={"underlying":underlying,"options":m}
    return daily

def choose(day,book):
    u=book["underlying"]
    if u is None:return None
    opts=list(book["options"].values())
    mats=sorted(set(o["maturity"] for o in opts if len(o["maturity"])==8))
    valid_mats=[]
    for ms in mats:
        try:md=datetime.strptime(ms,"%Y%m%d").date()
        except:continue
        dd=(md-day).days
        if 2<=dd<=7:valid_mats.append((md,ms))
    for md,ms in valid_mats:
        calls=[o for o in opts if o["maturity"]==ms and o["side"]=="call" and
               o["premium"]>=MIN_LEG and o["strike"] is not None and o["strike"]>=u]
        puts=[o for o in opts if o["maturity"]==ms and o["side"]=="put" and
              o["premium"]>=MIN_LEG and o["strike"] is not None and o["strike"]<=u]
        pairs=[]
        for c in calls:
            for p in puts:
                total=c["premium"]+p["premium"]
                if total<=MAX_COMBINED:
                    distance=abs(c["strike"]-u)+abs(p["strike"]-u)
                    pairs.append((total,-distance,c,p))
        if pairs:
            pairs.sort(key=lambda x:(x[0],x[1]),reverse=True)
            total,_,c,p=pairs[0]
            return {"maturity":ms,"call":c,"put":p,"combined_premium":total}
    return None

def main():
    daily=load(); dates=sorted(daily)
    campaigns=[]
    for day in dates:
        pair=choose(day,daily[day])
        if not pair:continue
        cost=pair["combined_premium"]*CONTRACT_MULTIPLIER
        cash=START-cost
        if cash<0:continue
        deadline=day+timedelta(days=7)
        marks=[]
        for d in dates:
            if d<=day or d>deadline:continue
            ob=daily[d]["options"]
            c=ob.get(pair["call"]["code"]); p=ob.get(pair["put"]["code"])
            if not c or not p:continue
            value=cash+(c["premium"]+p["premium"])*CONTRACT_MULTIPLIER
            marks.append({"date":d.strftime("%Y%m%d"),"value_yen":value,
                          "call_premium":c["premium"],"put_premium":p["premium"]})
        if not marks:continue
        best=max(marks,key=lambda x:x["value_yen"])
        last=marks[-1]
        campaigns.append({
          "entry_date":day.strftime("%Y%m%d"),
          "maturity":pair["maturity"],
          "underlying":daily[day]["underlying"],
          "call_code":pair["call"]["code"],"call_strike":pair["call"]["strike"],
          "call_entry_premium":pair["call"]["premium"],
          "put_code":pair["put"]["code"],"put_strike":pair["put"]["strike"],
          "put_entry_premium":pair["put"]["premium"],
          "entry_cost_yen":round(cost,2),"cash_left_yen":round(cash,2),
          "best_common_close_date":best["date"],
          "best_portfolio_value_yen":round(best["value_yen"],2),
          "best_multiple_on_start":round(best["value_yen"]/START,4),
          "last_common_close_date":last["date"],
          "last_common_close_value_yen":round(last["value_yen"],2),
        })
    n=len(campaigns)
    def rate(pred):
        return round(100*sum(pred(x) for x in campaigns)/n,4) if n else 0
    top=sorted(campaigns,key=lambda x:x["best_portfolio_value_yen"],reverse=True)[:25]
    return {
      "paper_only":True,
      "source":"JPX actual daily mini-option closing premiums",
      "rule":"nearest 2-7d maturity OTM call+put, each >=20 premium, combined <=100 premium",
      "campaigns":n,
      "target_50000_hit_campaigns":sum(x["best_portfolio_value_yen"]>=TARGET for x in campaigns),
      "target_50000_hit_rate_pct":rate(lambda x:x["best_portfolio_value_yen"]>=TARGET),
      "best_at_least_20000_rate_pct":rate(lambda x:x["best_portfolio_value_yen"]>=20_000),
      "last_common_close_below_5000_rate_pct":rate(lambda x:x["last_common_close_value_yen"]<5_000),
      "median_last_common_close_yen":(
        sorted(x["last_common_close_value_yen"] for x in campaigns)[n//2] if n else None
      ),
      "top_campaigns":top,
    }

if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,sort_keys=True))
