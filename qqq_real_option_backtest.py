"""Real-price QQQ options EOD backtest using public 2025 historical chains.

Entry = option ask at EOD. Exit valuation = later bid on the same contract.
Buys the maximum whole number of contracts affordable with JPY10,000 converted
at a fixed USDJPY reference. Goal is total account >= JPY30,000 within 7 days.

Data source (public research dataset):
https://github.com/anahatsingh-ui/options-dataset-hist
"""
from __future__ import annotations
import json, math, os, urllib.request
from pathlib import Path
import pandas as pd

USDJPY=158.2
START_JPY=10_000.0
TARGET_JPY=30_000.0
START_USD=START_JPY/USDJPY
TARGET_USD=TARGET_JPY/USDJPY
BASE="https://raw.githubusercontent.com/anahatsingh-ui/options-dataset-hist/main/qqq"
OPT_URL=f"{BASE}/options_2025.parquet"
UND_URL=f"{BASE}/underlying_prices.parquet"
CACHE=Path("/tmp/qqq_real_options")
CACHE.mkdir(exist_ok=True)

def dl(url,name):
    p=CACHE/name
    if not p.exists():
        urllib.request.urlretrieve(url,p)
    return p

def load():
    opt=pd.read_parquet(dl(OPT_URL,"options_2025.parquet"))
    und=pd.read_parquet(dl(UND_URL,"underlying_prices.parquet"))
    opt["date"]=pd.to_datetime(opt["date"]).dt.normalize()
    opt["expiration"]=pd.to_datetime(opt["expiration"]).dt.normalize()
    return opt,und

def underlying_series(opt,und):
    # Prefer separate underlying file, but tolerate schema differences.
    cols={c.lower():c for c in und.columns}
    dcol=cols.get("date")
    pcol=next((cols[k] for k in ("close","adj_close","price","underlying_price","underlying") if k in cols),None)
    if dcol and pcol:
        s=und[[dcol,pcol]].copy()
        s[dcol]=pd.to_datetime(s[dcol]).dt.normalize()
        return s.dropna().drop_duplicates(dcol).set_index(dcol)[pcol].astype(float).sort_index()
    # fallback: derive spot proxy from near-ATM option rows if dataset carries it
    for c in ("underlying_price","underlying","stock_price"):
        if c in opt.columns:
            return opt.groupby("date")[c].median().astype(float).sort_index()
    raise RuntimeError(f"Cannot identify underlying close columns: {list(und.columns)}")

def contract_col(df):
    for c in ("contract_id","contract","option_symbol","symbol"):
        if c in df.columns and c!="symbol":
            return c
    if "contract_id" in df.columns:return "contract_id"
    raise RuntimeError("contract id column not found")

def simulate(opt,spot,lookback,target_delta,target_dte,mode):
    cid=contract_col(opt)
    rows=[]
    dates=sorted(set(opt["date"]))
    bydate={d:g for d,g in opt.groupby("date")}
    history={}
    for c,g in opt.groupby(cid):
        history[c]=g.sort_values("date")[["date","bid","ask","expiration"]]
    for d in dates:
        if d not in spot.index: continue
        loc=spot.index.get_indexer([d])[0]
        if loc<lookback: continue
        prev=spot.iloc[loc-lookback]
        now=spot.loc[d]
        if not (prev>0 and now>0): continue
        ret=now/prev-1
        right="call" if ret>=0 else "put"
        if mode=="contrarian": right="put" if right=="call" else "call"
        g=bydate[d].copy()
        g["dte"]=(g["expiration"]-d).dt.days
        g=g[(g["dte"]>=1)&(g["dte"]<=7)]
        tcol="type" if "type" in g.columns else ("right" if "right" in g.columns else None)
        if not tcol: raise RuntimeError("option type column not found")
        vals=g[tcol].astype(str).str.lower()
        want=vals.str.startswith("c") if right=="call" else vals.str.startswith("p")
        g=g[want]
        g=g[pd.to_numeric(g["ask"],errors="coerce")>0]
        g=g[pd.to_numeric(g["bid"],errors="coerce")>=0]
        if g.empty: continue
        g["dte_gap"]=(g["dte"]-target_dte).abs()
        if "delta" in g.columns:
            ad=pd.to_numeric(g["delta"],errors="coerce").abs()
            g["delta_gap"]=(ad-target_delta).abs()
        else:
            # delta-free fallback: select cheapest affordable option near target DTE
            g["delta_gap"]=0.0
        g["ask_num"]=pd.to_numeric(g["ask"],errors="coerce")
        g=g[g["ask_num"]*100<=START_USD]
        if g.empty: continue
        pick=g.sort_values(["dte_gap","delta_gap","ask_num"]).iloc[0]
        ask=float(pick["ask_num"])
        n=int(START_USD//(ask*100))
        if n<1: continue
        cash=START_USD-n*ask*100
        h=history[pick[cid]]
        end=min(pd.Timestamp(pick["expiration"]),d+pd.Timedelta(days=7))
        f=h[(h["date"]>d)&(h["date"]<=end)].copy()
        if f.empty:
            rows.append((d,False,n,ask,right,float(ret)))
            continue
        bids=pd.to_numeric(f["bid"],errors="coerce").fillna(0.0)
        acct=cash+n*100*bids
        hit=bool((acct>=TARGET_USD).any())
        rows.append((d,hit,n,ask,right,float(ret)))
    return rows

def score(rows):
    n=len(rows)
    return {"trades":n,"hits":sum(r[1] for r in rows),
            "hit_pct":round(100*sum(r[1] for r in rows)/n,2) if n else 0}

def main():
    opt,und=load()
    spot=underlying_series(opt,und)
    allres=[]
    for lb in (1,2,3,5,10):
      for delta in (0.05,0.10,0.15,0.20,0.25,0.30,0.40,0.50):
       for dte in (1,2,3,4,5,7):
        for mode in ("momentum","contrarian"):
          rows=simulate(opt,spot,lb,delta,dte,mode)
          if len(rows)<40: continue
          cut=len(rows)//2
          tr=score(rows[:cut]); ho=score(rows[cut:])
          if tr["trades"]<20 or ho["trades"]<20: continue
          allres.append({"lookback":lb,"target_delta":delta,"target_dte":dte,"mode":mode,
                         "train":tr,"holdout":ho})
    # Selection is by train only; holdout is then inspected.
    allres.sort(key=lambda x:(x["train"]["hit_pct"],x["train"]["trades"]),reverse=True)
    selected=allres[:30]
    robust=[x for x in allres if x["train"]["hit_pct"]>=80 and x["holdout"]["hit_pct"]>=80]
    best_hold=max(allres,key=lambda x:x["holdout"]["hit_pct"]) if allres else None
    print(json.dumps({
      "objective":"JPY10000 to JPY30000 within 7 days",
      "pricing":"buy at EOD ask, value/exit at later EOD bid, max whole contracts affordable",
      "year":2025,
      "robust_80pct":robust[:20],
      "top_selected_by_train":selected,
      "best_holdout_diagnostic_only":best_hold,
      "note":"EOD data misses intraday touches; historical result is not a future probability."
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
