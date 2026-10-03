from __future__ import annotations
import json
from cross_asset_final_compare import fetch_symbol, windows, rare_selective_breakout

SYMS={"nasdaq":"NQ=F","russell":"RTY=F","gold":"GC=F","tsla":"TSLA","nvda":"NVDA",
      "mstr":"MSTR","coin":"COIN","soxl":"SOXL","tqqq":"TQQQ","smci":"SMCI"}

def score(rows):
    cut=len(rows)//2
    def one(xs):
        tr=[r for r in xs if r[3]]
        m=len(tr)
        return {"trades":m,
                "hit":round(100*sum(r[0] is not None for r in tr)/m,2) if m else 0,
                "ko":round(100*sum(r[2] for r in tr)/m,2) if m else 0}
    return one(rows[:cut]),one(rows[cut:])

def main():
    out=[]
    for name,sym in SYMS.items():
        try: ws=windows(fetch_symbol(sym))
        except Exception: continue
        if len(ws)<40: continue
        for ko in (0.003,0.005,0.0075,0.01,0.0125):
          for reserve in (0.0,2000.0):
            for lb in (2,4,8):
              for rp in (0.0,0.005):
                for cp in (0.0,0.05):
                  for direction in ("both","long","short"):
                    rows=[rare_selective_breakout(w,lb,ko,reserve,rp,cp,direction) for w in ws]
                    tr,ho=score(rows)
                    if ho["trades"]<20: continue
                    out.append({"asset":name,"symbol":sym,"ko_pct":ko,"reserve":reserve,
                                "lookback":lb,"range_filter":rp,"close_extension":cp,
                                "direction":direction,"train":tr,"holdout":ho})
    out.sort(key=lambda x:(x["holdout"]["hit"],-x["holdout"]["ko"],x["holdout"]["trades"]),reverse=True)
    winners=[x for x in out if x["holdout"]["hit"]>=80]
    print(json.dumps({"winners":winners[:20],"top":out[:20],
                      "objective":"10k->30k in <=7d; holdout>=20 trades",
                      "note":"Historical normalized KO proxy; not future probability."},
                     ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
