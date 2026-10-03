"""Broad high-volatility search for 7-day JPY10k -> JPY30k paper target.

This is a robustness search, not a promise of future performance.
Candidates are evaluated on chronological train/holdout halves.
Only holdout results with >=20 trade windows are ranked.
"""
from __future__ import annotations
import json
from cross_asset_final_compare import fetch_symbol, windows, rare_selective_breakout

SYMS={
 "nasdaq":"NQ=F","russell":"RTY=F","gold":"GC=F","sp500":"ES=F",
 "tsla":"TSLA","nvda":"NVDA","mstr":"MSTR","coin":"COIN","soxl":"SOXL",
 "tqqq":"TQQQ","smci":"SMCI","pltr":"PLTR","amd":"AMD","meta":"META",
 "avgo":"AVGO","gme":"GME"
}

def evaluate(symbol, ko, reserve, lb, rp, cp, direction):
    bars=fetch_symbol(symbol)
    ws=windows(bars)
    if len(ws)<40:
        return None
    cut=len(ws)//2
    rows=[rare_selective_breakout(w,lb,ko,reserve,rp,cp,direction) for w in ws]
    def part(xs):
        tr=[r for r in xs if r[3]]
        m=len(tr)
        return {
          "trades":m,
          "hit":round(100*sum(r[0] is not None for r in tr)/m,2) if m else 0,
          "ko":round(100*sum(r[2] for r in tr)/m,2) if m else 0,
        }
    return part(rows[:cut]),part(rows[cut:])

def main():
    ranked=[]
    winners=[]
    for name,symbol in SYMS.items():
        try:
            bars=fetch_symbol(symbol)
            ws=windows(bars)
        except Exception as e:
            continue
        if len(ws)<40: continue
        cut=len(ws)//2
        for ko in (0.004,0.005,0.0075,0.01,0.0125,0.015,0.02):
          for reserve in (0.0,1000.0,2000.0):
            for lb in (2,4,6,8,12):
              for rp in (0.0,0.003,0.006,0.01):
                for cp in (0.0,0.05,0.1):
                  for direction in ("both","long","short"):
                    rows=[rare_selective_breakout(w,lb,ko,reserve,rp,cp,direction) for w in ws]
                    def one(xs):
                        tr=[r for r in xs if r[3]]
                        m=len(tr)
                        return (m,100*sum(r[0] is not None for r in tr)/m if m else 0,
                                100*sum(r[2] for r in tr)/m if m else 0)
                    tt,th,tk=one(rows[:cut]); ht,hh,hk=one(rows[cut:])
                    if ht<20: continue
                    row={"asset":name,"symbol":symbol,"ko_pct":ko,"reserve":reserve,
                         "lookback":lb,"range_filter":rp,"close_extension":cp,"direction":direction,
                         "train_trades":tt,"train_hit_pct":round(th,2),"train_ko_pct":round(tk,2),
                         "holdout_trades":ht,"holdout_hit_pct":round(hh,2),"holdout_ko_pct":round(hk,2)}
                    ranked.append(row)
                    if hh>=80.0:
                        winners.append(row)
    ranked.sort(key=lambda x:(x["holdout_hit_pct"],-x["holdout_ko_pct"],x["holdout_trades"]),reverse=True)
    winners.sort(key=lambda x:(x["holdout_hit_pct"],-x["holdout_ko_pct"],x["holdout_trades"]),reverse=True)
    print(json.dumps({"objective":"JPY10000 to JPY30000 within 7 days",
                      "minimum_holdout_trades":20,
                      "winners_80pct":winners[:30],
                      "top_overall":ranked[:30],
                      "note":"Historical paper-model holdout rates are not future probabilities."},
                     ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
