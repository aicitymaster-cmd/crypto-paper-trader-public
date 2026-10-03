"""Optimistic percentage-based KO upper-bound search.

Deliberately favorable assumptions: zero spread, zero premium, zero financing, no slippage.
If 80% is absent even here, adding real costs would not improve it.
"""
from __future__ import annotations
import json
from cross_asset_final_compare import fetch_symbol, windows, hit_day

START=10000.0
TARGET=30000.0
SYMS={"nasdaq":"NQ=F","russell":"RTY=F","gold":"GC=F","sp500":"ES=F",
      "tsla":"TSLA","nvda":"NVDA","mstr":"MSTR","coin":"COIN","soxl":"SOXL",
      "tqqq":"TQQQ","smci":"SMCI","pltr":"PLTR","amd":"AMD","gme":"GME"}

def run(chunk,ko_pct,lb,rp,ext,direction):
    eq=START; i=max(2,lb); hit=None; stopped=False; traded=False
    while i<len(chunk)-1 and eq>0 and hit is None:
        hist=chunk[i-lb:i]
        hh=max(b.high for b in hist); ll=min(b.low for b in hist); prev=hist[-1].close
        rng=(hh-ll)/prev if prev else 0
        cur=chunk[i]
        if rng<rp or hh<=ll: i+=1; continue
        pos=(cur.close-ll)/(hh-ll)
        longb=cur.close>hh and pos>=1+ext
        shortb=cur.close<ll and pos<=-ext
        if direction=="long": shortb=False
        if direction=="short": longb=False
        if not(longb or shortb): i+=1; continue
        traded=True; sig=1 if longb else -1; entry=cur.close
        # zero-cost optimistic sizing: KO move wipes the sleeve exactly
        notional=eq/ko_pct
        j=i+1
        while j<len(chunk):
            b=chunk[j]; high=b.high; low=b.low; c=b.close
            adverse=(entry-low)/entry if sig==1 else (high-entry)/entry
            favorable=(high-entry)/entry if sig==1 else (entry-low)/entry
            if adverse>=ko_pct:
                eq=0; stopped=True; i=j+1; break
            if eq+notional*favorable>=TARGET:
                eq=TARGET; hit=hit_day(chunk[0].ts,b.ts); break
            if (sig==1 and c<hh) or (sig==-1 and c>ll):
                raw=(c-entry)/entry if sig==1 else (entry-c)/entry
                eq=max(0,eq+notional*raw); i=j+1; break
            j+=1
        else:
            b=chunk[-1]; raw=(b.close-entry)/entry if sig==1 else (entry-b.close)/entry
            eq=max(0,eq+notional*raw); i=len(chunk)
    return hit,stopped,traded

def main():
    rows=[]
    for name,sym in SYMS.items():
        try: ws=windows(fetch_symbol(sym))
        except Exception: continue
        if len(ws)<40: continue
        cut=len(ws)//2
        for ko in (0.001,0.0015,0.002,0.003,0.004,0.005,0.0075,0.01,0.015,0.02):
          for lb in (1,2,4,6,8,12):
            for rp in (0.0,0.003,0.006,0.01):
              for ext in (0.0,0.05,0.1):
                for direction in ("both","long","short"):
                    rr=[run(w,ko,lb,rp,ext,direction) for w in ws]
                    def score(xs):
                        t=[r for r in xs if r[2]]; n=len(t)
                        return n,(100*sum(r[0] is not None for r in t)/n if n else 0),(100*sum(r[1] for r in t)/n if n else 0)
                    tn,th,tk=score(rr[:cut]); hn,hh,hk=score(rr[cut:])
                    if hn<20: continue
                    rows.append({"asset":name,"ko_pct":ko,"lookback":lb,"range_filter":rp,
                                 "extension":ext,"direction":direction,
                                 "train_trades":tn,"train_hit":round(th,2),"train_stop":round(tk,2),
                                 "holdout_trades":hn,"holdout_hit":round(hh,2),"holdout_stop":round(hk,2)})
    rows.sort(key=lambda x:(x["holdout_hit"],-x["holdout_stop"],x["holdout_trades"]),reverse=True)
    print(json.dumps({"winners":[r for r in rows if r["holdout_hit"]>=80][:30],
                      "top":rows[:30],
                      "assumption":"optimistic zero-cost percentage KO upper bound",
                      "objective":"JPY10k->JPY30k within 7d, holdout>=20 trades"},
                     ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
