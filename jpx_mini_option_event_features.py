"""Extract pre-event features for cheap NK225 mini options.

Discovery uses only the first half of the currently published JPX business days.
The second half is reserved for later validation. Outcomes are used only to
label discovery examples, never as input features.
"""
from __future__ import annotations
import csv, io, json, ssl, urllib.parse, urllib.request, statistics
from datetime import datetime, timedelta

BASE="https://www.jpx.co.jp"
JSON_URL=BASE+"/automation/markets/derivatives/option-price/json/option_theoretical_price.json"
UA="crypto-paper-trader-public-jpx-event-features/1.0"
PRODUCT="NK225MWE"
P_MIN=50.0; P_MAX=100.0

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
        options={}; underlying=None; base_iv=None
        for r in rows:
            if len(r)<17 or r[0].strip()!=PRODUCT:continue
            strike=num(r[3]); u=num(r[15]); biv=num(r[16]); maturity=r[2].strip()
            if u is not None: underlying=u
            if biv is not None: base_iv=biv
            for side,ci,pi in (("put",5,6),("call",10,11)):
                code=r[ci].strip(); p=num(r[pi])
                if code and p is not None and p>0:
                    options[code]={"code":code,"side":side,"premium":p,"strike":strike,"maturity":maturity}
        daily[day]={"underlying":underlying,"base_iv":base_iv,"options":options}
    return daily

def ret(a,b):
    if a is None or b is None or b==0:return None
    return a/b-1.0

def med(vals):
    vals=[x for x in vals if x is not None]
    return round(statistics.median(vals),6) if vals else None

def main():
    daily=load(); dates=sorted(daily)
    split=len(dates)//2
    discovery_dates=set(dates[:split])
    rows=[]
    for i,day in enumerate(dates):
        if day not in discovery_dates or i<3:continue
        u=daily[day]["underlying"]
        p1=daily[dates[i-1]]["underlying"]
        p2=daily[dates[i-2]]["underlying"]
        p3=daily[dates[i-3]]["underlying"]
        prev_iv=daily[dates[i-1]]["base_iv"]
        if None in (u,p1,p2,p3):continue
        for o in daily[day]["options"].values():
            if not (P_MIN<=o["premium"]<=P_MAX):continue
            try: md=datetime.strptime(o["maturity"],"%Y%m%d").date()
            except: continue
            dte=(md-day).days
            if not (2<=dte<=14):continue
            # OTM only.
            if o["side"]=="call" and o["strike"]<u:continue
            if o["side"]=="put" and o["strike"]>u:continue
            deadline=day+timedelta(days=7)
            future=[]
            for d in dates:
                if d<=day or d>deadline:continue
                x=daily[d]["options"].get(o["code"])
                if x:future.append(x["premium"])
            if not future:continue
            best=max(future)
            mult=best/o["premium"]
            moneyness=(o["strike"]/u-1.0) if o["side"]=="call" else (u/o["strike"]-1.0)
            rows.append({
              "entry_date":day.strftime("%Y%m%d"),"side":o["side"],
              "premium":o["premium"],"multiple":round(mult,4),
              "winner_5x":mult>=5.0,"winner_9x":mult>=9.0,
              "prev1_ret":ret(p1,p2),"prev2_ret":ret(p1,p3),
              "abs_prev1_ret":abs(ret(p1,p2)),"abs_prev2_ret":abs(ret(p1,p3)),
              "entry_gap_from_prev":ret(u,p1),
              "prev_base_iv":prev_iv,"dte":dte,
              "moneyness_abs":abs(moneyness),
            })
    winners=[r for r in rows if r["winner_5x"]]
    losers=[r for r in rows if not r["winner_5x"]]
    def summary(xs):
        return {
          "n":len(xs),
          "unique_dates":len(set(x["entry_date"] for x in xs)),
          "median_prev1_ret":med([x["prev1_ret"] for x in xs]),
          "median_abs_prev1_ret":med([x["abs_prev1_ret"] for x in xs]),
          "median_prev2_ret":med([x["prev2_ret"] for x in xs]),
          "median_abs_prev2_ret":med([x["abs_prev2_ret"] for x in xs]),
          "median_entry_gap_from_prev":med([x["entry_gap_from_prev"] for x in xs]),
          "median_prev_base_iv":med([x["prev_base_iv"] for x in xs]),
          "median_dte":med([x["dte"] for x in xs]),
          "median_moneyness_abs":med([x["moneyness_abs"] for x in xs]),
        }
    by_date={}
    for r in winners:
        by_date.setdefault(r["entry_date"],[]).append(r)
    top_dates=[]
    for d,xs in sorted(by_date.items()):
        top_dates.append({"date":d,"winner_count":len(xs),"max_multiple":max(x["multiple"] for x in xs),
                          "features":{k:xs[0][k] for k in ("prev1_ret","prev2_ret","abs_prev1_ret","abs_prev2_ret","entry_gap_from_prev","prev_base_iv")}})
    print(json.dumps({
      "paper_only":True,
      "discovery_business_days":len(discovery_dates),
      "reserved_validation_business_days":len(dates)-len(discovery_dates),
      "eligible_discovery_options":len(rows),
      "winner_5x_summary":summary(winners),
      "nonwinner_summary":summary(losers),
      "winner_dates":top_dates,
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
