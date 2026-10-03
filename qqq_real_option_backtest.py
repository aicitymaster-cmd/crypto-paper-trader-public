"""Real-price QQQ options EOD backtest using public 2025 historical chains.

Entry = EOD ask. Exit/target = later EOD bid on the same contract.
Maximum whole contracts are bought with JPY10,000 (fixed USDJPY reference).
Goal: total account >= JPY30,000 within 7 calendar days.

Public dataset:
https://github.com/anahatsingh-ui/options-dataset-hist
"""
from __future__ import annotations
import json, urllib.request
from pathlib import Path
import pandas as pd

USDJPY=158.2
START_USD=10_000.0/USDJPY
TARGET_USD=30_000.0/USDJPY
BASE="https://raw.githubusercontent.com/anahatsingh-ui/options-dataset-hist/main/qqq"
CACHE=Path("/tmp/qqq_real_options"); CACHE.mkdir(exist_ok=True)

def dl(url,name):
    p=CACHE/name
    if not p.exists(): urllib.request.urlretrieve(url,p)
    return p

def load():
    opt=pd.read_parquet(dl(f"{BASE}/options_2025.parquet","options_2025.parquet"))
    und=pd.read_parquet(dl(f"{BASE}/underlying_prices.parquet","underlying_prices.parquet"))
    opt["date"]=pd.to_datetime(opt["date"]).dt.normalize()
    opt["expiration"]=pd.to_datetime(opt["expiration"]).dt.normalize()
    for c in ("ask","bid","delta","strike"):
        if c in opt.columns: opt[c]=pd.to_numeric(opt[c],errors="coerce")
    return opt,und

def get_spot(opt,und):
    cols={c.lower():c for c in und.columns}
    dcol=cols.get("date")
    pcol=next((cols[k] for k in ("close","adj_close","price","underlying_price","underlying") if k in cols),None)
    if dcol and pcol:
        x=und[[dcol,pcol]].copy()
        x[dcol]=pd.to_datetime(x[dcol]).dt.normalize()
        return x.dropna().drop_duplicates(dcol).set_index(dcol)[pcol].astype(float).sort_index()
    raise RuntimeError(f"underlying schema unsupported: {list(und.columns)}")

def add_future_max_bid(opt):
    cid="contract_id"
    if cid not in opt.columns: raise RuntimeError("contract_id missing")
    opt=opt.sort_values([cid,"date"]).copy()
    out=pd.Series(index=opt.index,dtype=float)
    for _,g in opt.groupby(cid,sort=False):
        idx=g.index.to_list(); dates=g["date"].to_list(); bids=g["bid"].fillna(0).to_list()
        n=len(g)
        for i in range(n):
            end=dates[i]+pd.Timedelta(days=7)
            mx=0.0
            j=i+1
            while j<n and dates[j]<=end:
                if bids[j]>mx: mx=float(bids[j])
                j+=1
            out.loc[idx[i]]=mx
    opt["future_max_bid_7d"]=out
    return opt

def prepare_dates(opt,spot):
    bydate={}
    for d,g in opt.groupby("date"):
        if d not in spot.index: continue
        z=g.copy()
        z["dte"]=(z["expiration"]-d).dt.days
        z=z[(z["dte"]>=1)&(z["dte"]<=7)&(z["ask"]>0)&(z["bid"]>=0)]
        z=z[z["ask"]*100<=START_USD]
        if not z.empty: bydate[d]=z
    return bydate

def score_config(bydate,spot,lb,tdelta,tdte,mode):
    rows=[]
    sidx=spot.index
    for d,g0 in bydate.items():
        try: loc=sidx.get_loc(d)
        except KeyError: continue
        if isinstance(loc,slice) or loc<lb: continue
        ret=float(spot.iloc[loc]/spot.iloc[loc-lb]-1)
        right="call" if ret>=0 else "put"
        if mode=="contrarian": right="put" if right=="call" else "call"
        vals=g0["type"].astype(str).str.lower()
        g=g0[vals.str.startswith("c" if right=="call" else "p")].copy()
        if g.empty: continue
        g["dte_gap"]=(g["dte"]-tdte).abs()
        g["delta_gap"]=(g["delta"].abs()-tdelta).abs() if "delta" in g.columns else 0.0
        p=g.sort_values(["dte_gap","delta_gap","ask"]).iloc[0]
        ask=float(p["ask"]); mx=float(p["future_max_bid_7d"])
        n=int(START_USD//(ask*100))
        if n<1: continue
        cash=START_USD-n*ask*100
        hit=(cash+n*100*mx)>=TARGET_USD
        rows.append(hit)
    n=len(rows); cut=n//2
    def sc(xs):
        m=len(xs); h=sum(xs)
        return {"trades":m,"hits":h,"hit_pct":round(100*h/m,2) if m else 0}
    return sc(rows[:cut]),sc(rows[cut:])

def main():
    opt,und=load()
    spot=get_spot(opt,und)
    opt=add_future_max_bid(opt)
    bydate=prepare_dates(opt,spot)
    res=[]
    for lb in (1,3,5):
      for delta in (0.05,0.10,0.20,0.30,0.40):
       for dte in (1,2,4,7):
        for mode in ("momentum","contrarian"):
          tr,ho=score_config(bydate,spot,lb,delta,dte,mode)
          if tr["trades"]>=20 and ho["trades"]>=20:
            res.append({"lookback":lb,"target_delta":delta,"target_dte":dte,"mode":mode,
                        "train":tr,"holdout":ho})
    res.sort(key=lambda x:(x["train"]["hit_pct"],x["train"]["trades"]),reverse=True)
    robust=[x for x in res if x["train"]["hit_pct"]>=80 and x["holdout"]["hit_pct"]>=80]
    best_hold=sorted(res,key=lambda x:x["holdout"]["hit_pct"],reverse=True)[:10]
    print(json.dumps({
      "objective":"JPY10000 to JPY30000 within 7 days",
      "pricing":"EOD ask entry / later EOD bid target; maximum affordable whole contracts",
      "year":2025,
      "robust_80pct":robust[:20],
      "top_selected_by_train":res[:20],
      "best_holdout_diagnostic_only":best_hold,
      "limitations":"EOD misses intraday target touches; fixed USDJPY; public historical dataset.",
      "future_probability":False
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__": main()
