"""Four-block chronological stability check for the frozen GOLD filter."""
from __future__ import annotations
import json
from gold_filter_holdout import fetch, parse, candidates, summ, run, STOPS

def main():
    bars=parse(fetch()); c=candidates(bars)
    start,end=bars[0].ts,bars[-1].ts
    span=(end-start)/4
    blocks=[]
    for i in range(4):
        a=start+span*i
        b=end if i==3 else start+span*(i+1)
        blocks.append((a,b,[x for x in c if a<=x[0]<b]))
    cases={}
    for st in STOPS:
        rows=[]
        for i,(a,b,items) in enumerate(blocks,1):
            rows.append({"block":i,"start":a.isoformat(),"end":b.isoformat(),"summary":summ(run(items,st))})
        rates=[x["summary"]["target_rate_pct"] for x in rows if x["summary"]["windows"]]
        cases[str(st)]={"blocks":rows,"min_block_rate_pct":min(rates) if rates else 0,
                        "max_block_rate_pct":max(rates) if rates else 0}
    print(json.dumps({"paper_only":True,"cases":cases,
      "warning":"small block samples; use as stability check only, not future probability"},ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
