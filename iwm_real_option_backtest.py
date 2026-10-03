"""Real-price IWM EOD options backtest on public 2025 option chains.

Entry = EOD ask. Target valuation = later EOD bid for the same contract.
Buys max whole contracts affordable with JPY10,000 at fixed USDJPY.
Goal: account >= JPY30,000 within 7 calendar days.
"""
from __future__ import annotations
import json, urllib.request
from pathlib import Path
import duckdb, pandas as pd

USDJPY=158.2
START_USD=10_000.0/USDJPY
TARGET_USD=30_000.0/USDJPY
BASE="https://raw.githubusercontent.com/anahatsingh-ui/options-dataset-hist/main/iwm"
CACHE=Path("/tmp/iwm_real_options"); CACHE.mkdir(exist_ok=True)

def dl(url,name):
    p=CACHE/name
    if not p.exists(): urllib.request.urlretrieve(url,p)
    return str(p)

def load_entry_table():
    op=dl(f"{BASE}/options_2025.parquet","options_2025.parquet")
    und=dl(f"{BASE}/underlying_prices.parquet","underlying_prices.parquet")
    con=duckdb.connect()
    # Keep only contracts that could actually be bought with the starting account
    # and whose expiry is within the user's 7-day horizon. Then compute the best
    # later EOD bid within 7 calendar days using the same contract_id.
    q=f"""
    WITH b AS (
      SELECT
        contract_id,
        CAST(date AS TIMESTAMP) AS d,
        CAST(expiration AS TIMESTAMP) AS exp,
        type,
        CAST(strike AS DOUBLE) AS strike,
        CAST(delta AS DOUBLE) AS delta,
        CAST(bid AS DOUBLE) AS bid,
        CAST(ask AS DOUBLE) AS ask,
        MAX(CAST(bid AS DOUBLE)) OVER (
          PARTITION BY contract_id
          ORDER BY CAST(date AS TIMESTAMP)
          RANGE BETWEEN INTERVAL 1 DAY FOLLOWING AND INTERVAL 7 DAY FOLLOWING
        ) AS future_max_bid_7d
      FROM read_parquet('{op}')
    )
    SELECT
      contract_id,d,exp,type,strike,delta,bid,ask,
      date_diff('day', d, exp) AS dte,
      COALESCE(future_max_bid_7d,0.0) AS future_max_bid_7d
    FROM b
    WHERE date_diff('day', d, exp) BETWEEN 1 AND 7
      AND ask > 0
      AND ask * 100 <= {START_USD}
      AND bid >= 0
    """
    ent=con.execute(q).df()
    u=con.execute(f"SELECT * FROM read_parquet('{und}')").df()
    return ent,u

def spot_series(u):
    cols={c.lower():c for c in u.columns}
    d=cols.get("date")
    p=next((cols[k] for k in ("close","adj_close","price","underlying_price","underlying") if k in cols),None)
    if not d or not p: raise RuntimeError(f"underlying schema unsupported: {list(u.columns)}")
    x=u[[d,p]].copy(); x[d]=pd.to_datetime(x[d]).dt.normalize()
    return x.dropna().drop_duplicates(d).set_index(d)[p].astype(float).sort_index()

def score_config(bydate,spot,lb,tdelta,tdte,mode):
    hits=[]
    idx=spot.index
    for d,g0 in bydate.items():
        ts=pd.Timestamp(d)
        if ts not in idx: continue
        loc=idx.get_loc(ts)
        if not isinstance(loc,int) or loc<lb: continue
        ret=float(spot.iloc[loc]/spot.iloc[loc-lb]-1)
        right="call" if ret>=0 else "put"
        if mode=="contrarian": right="put" if right=="call" else "call"
        vals=g0["type"].astype(str).str.lower()
        g=g0[vals.str.startswith("c" if right=="call" else "p")].copy()
        if g.empty: continue
        g["dte_gap"]=(g["dte"]-tdte).abs()
        g["delta_gap"]=(pd.to_numeric(g["delta"],errors="coerce").abs()-tdelta).abs()
        g=g.dropna(subset=["ask","future_max_bid_7d","delta_gap"])
        if g.empty: continue
        p=g.sort_values(["dte_gap","delta_gap","ask"]).iloc[0]
        ask=float(p["ask"]); mx=float(p["future_max_bid_7d"])
        n=int(START_USD//(ask*100))
        if n<1: continue
        cash=START_USD-n*ask*100
        hits.append((cash+n*100*mx)>=TARGET_USD)
    n=len(hits); cut=n//2
    def sc(xs):
        m=len(xs); h=sum(xs)
        return {"trades":m,"hits":h,"hit_pct":round(100*h/m,2) if m else 0}
    return sc(hits[:cut]),sc(hits[cut:])

def main():
    ent,u=load_entry_table()
    ent["d"]=pd.to_datetime(ent["d"]).dt.normalize()
    bydate={d:g for d,g in ent.groupby("d")}
    spot=spot_series(u)
    res=[]
    for lb in (1,3,5):
      for delta in (0.05,0.10,0.20,0.30,0.40):
       for dte in (1,2,4,7):
        for mode in ("momentum","contrarian"):
          tr,ho=score_config(bydate,spot,lb,delta,dte,mode)
          if tr["trades"]>=20 and ho["trades"]>=20:
            res.append({"lookback":lb,"target_delta":delta,"target_dte":dte,
                        "mode":mode,"train":tr,"holdout":ho})
    res.sort(key=lambda x:(x["train"]["hit_pct"],x["train"]["trades"]),reverse=True)
    robust=[x for x in res if x["train"]["hit_pct"]>=80 and x["holdout"]["hit_pct"]>=80]
    best_hold=sorted(res,key=lambda x:x["holdout"]["hit_pct"],reverse=True)[:10]
    print(json.dumps({
      "objective":"JPY10000 to JPY30000 within 7 days",
      "pricing":"EOD ask entry / later EOD bid target / max affordable whole contracts",
      "year":2025,
      "eligible_entry_rows":len(ent),
      "robust_80pct":robust[:20],
      "top_selected_by_train":res[:20],
      "best_holdout_diagnostic_only":best_hold,
      "limitations":"EOD misses intraday target touches; fixed USDJPY; public historical dataset.",
      "future_probability":False
    },ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
