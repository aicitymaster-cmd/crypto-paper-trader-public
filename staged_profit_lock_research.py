"""PAPER-only staged profit-locking research for the frozen GOLD filter.

Compares:
1) stop immediately when total wealth first reaches JPY 50,000;
2) progressively move realized profits to a protected reserve at JPY 20k/30k/40k.

Reserve cash is never re-risked. Milestone withdrawals are applied only after
a trade closes, making this more conservative than assuming perfect intrabar
partial exits. Research only.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from statistics import median

from gold_filter_holdout import (
    fetch, parse, candidates, START, TARGET, LEVERAGE, FAST, SLOW, SPREAD, FEE
)

@dataclass(frozen=True)
class LockResult:
    final_total_yen: float
    reserve_yen: float
    active_yen: float
    target_hit: bool
    zero_active: bool
    trades: int

POLICIES = {
    "target_stop_only": (),
    "lock_20_30_40_light": ((20_000.0, 0.25), (30_000.0, 0.25), (40_000.0, 0.25)),
    "lock_20_30_40_medium": ((20_000.0, 0.50), (30_000.0, 0.25), (40_000.0, 0.25)),
    "lock_20_30_40_heavy": ((20_000.0, 0.50), (30_000.0, 0.50), (40_000.0, 0.50)),
}
STOPS=(0.0075,0.01)

def sma(v,n):
    return sum(v[-n:])/n

def run_lock_window(bars, stop_pct, policy):
    active=float(START); reserve=0.0; pos=0; entry=0.0; entry_active=active
    trades=0; locked=set(); cost=(SPREAD+2*FEE)/10000.0

    def total():
        return active+reserve

    def apply_locks():
        nonlocal active,reserve
        for idx,(threshold,fraction) in enumerate(policy):
            if idx in locked or total()<threshold:
                continue
            # lock a fraction of active capital; never touch existing reserve
            amount=max(0.0,active*fraction)
            reserve+=amount
            active-=amount
            locked.add(idx)

    for i in range(SLOW,len(bars)):
        closes=[b.close for b in bars[:i+1]]
        bar=bars[i]; price=bar.close
        if price<=0: continue
        signal=1 if sma(closes,FAST)>sma(closes,SLOW) else -1

        if pos:
            _,high,low,_=bar.ohlc()
            adverse=(low/entry-1) if pos==1 else (entry/high-1)
            favorable=(high/entry-1) if pos==1 else (entry/low-1)

            # Exact target-stop: if intrabar marked total wealth reaches target,
            # close and end the campaign immediately.
            favorable_active=max(0.0,entry_active*(1+favorable*LEVERAGE-LEVERAGE*cost))
            if reserve+favorable_active>=TARGET:
                needed=max(0.0,TARGET-reserve)
                active=needed
                return LockResult(round(reserve+active,2),round(reserve,2),round(active,2),True,False,trades+1)

            exit_raw=None
            if adverse<=-stop_pct:
                exit_raw=-stop_pct
            elif favorable>=0.08:
                exit_raw=0.08
            elif signal!=pos:
                exit_raw=pos*(price/entry-1)

            if exit_raw is not None:
                pnl=entry_active*(exit_raw*LEVERAGE-LEVERAGE*cost)
                active=max(0.0,entry_active+pnl)
                trades+=1; pos=0
                apply_locks()
                if total()>=TARGET:
                    return LockResult(round(total(),2),round(reserve,2),round(active,2),True,active<=0,trades)

        if not pos and active>0:
            pos=signal; entry=price; entry_active=active

    if pos and active>0:
        raw=pos*(bars[-1].close/entry-1)
        pnl=entry_active*(raw*LEVERAGE-LEVERAGE*cost)
        active=max(0.0,entry_active+pnl); trades+=1
        apply_locks()

    return LockResult(round(active+reserve,2),round(reserve,2),round(active,2),active+reserve>=TARGET,active<=0,trades)

def summarize(rows):
    n=len(rows); finals=[r.final_total_yen for r in rows]
    hits=sum(r.target_hit for r in rows)
    active_zero=sum(r.zero_active for r in rows)
    saved=sum(r.reserve_yen>0 for r in rows)
    ge5=sum(r.final_total_yen>=5_000 for r in rows)
    ge10=sum(r.final_total_yen>=10_000 for r in rows)
    return {
        "windows":n,
        "target_hits":hits,
        "target_rate_pct":round(100*hits/n,4) if n else 0,
        "active_zero_rate_pct":round(100*active_zero/n,4) if n else 0,
        "reserve_positive_rate_pct":round(100*saved/n,4) if n else 0,
        "final_at_least_5000_rate_pct":round(100*ge5/n,4) if n else 0,
        "final_at_least_10000_rate_pct":round(100*ge10/n,4) if n else 0,
        "median_final_yen":round(median(finals),2) if n else 0,
        "best_final_yen":round(max(finals),2) if n else 0,
        "worst_final_yen":round(min(finals),2) if n else 0,
    }

def main():
    bars=parse(fetch()); rows=candidates(bars)
    midpoint=bars[0].ts+(bars[-1].ts-bars[0].ts)/2
    first=[x for x in rows if x[0]<midpoint]
    second=[x for x in rows if x[0]>=midpoint]
    out={}
    for stop in STOPS:
        stop_cases={}
        for name,policy in POLICIES.items():
            all_r=[run_lock_window(chunk,stop,policy) for _,chunk in rows]
            first_r=[run_lock_window(chunk,stop,policy) for _,chunk in first]
            second_r=[run_lock_window(chunk,stop,policy) for _,chunk in second]
            stop_cases[name]={
                "all":summarize(all_r),
                "first_half":summarize(first_r),
                "second_half_holdout":summarize(second_r),
            }
        out[str(stop)]=stop_cases
    print(json.dumps({
        "paper_only":True,
        "policy_note":"reserve is never re-risked; staged locks occur only after realized trade exits; 50k target uses immediate stop",
        "cases":out,
        "warning":"historical leveraged simulation; not broker-executable terms or a future probability guarantee",
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
