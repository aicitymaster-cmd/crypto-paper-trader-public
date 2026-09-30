"""PAPER-only cross-market 7-day backtest utilities."""
from __future__ import annotations
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

@dataclass(frozen=True)
class Bar:
    ts: datetime
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None

    def ohlc(self):
        o = self.close if self.open is None else self.open
        h = self.close if self.high is None else self.high
        l = self.close if self.low is None else self.low
        return o, h, l, self.close

@dataclass(frozen=True)
class Result:
    final_yen: float
    return_pct: float
    max_dd_pct: float
    trades: int
    wins: int
    ruined: bool
    target_hit: bool

def load_csv(path: str | Path) -> list[Bar]:
    rows=[]
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader=csv.DictReader(fh); names={n.lower():n for n in (reader.fieldnames or [])}
        tk=names.get("date") or names.get("timestamp") or names.get("time")
        ck=names.get("close"); ok=names.get("open"); hk=names.get("high"); lk=names.get("low")
        if not tk or not ck: raise ValueError("CSV requires Date/Timestamp and Close columns")
        def val(row,key,default):
            if not key or not row.get(key,"").strip(): return default
            return float(row[key])
        for row in reader:
            raw=row[tk].strip().replace("Z","+00:00"); ts=datetime.fromisoformat(raw)
            if ts.tzinfo is None: ts=ts.replace(tzinfo=timezone.utc)
            c=float(row[ck])
            rows.append(Bar(ts.astimezone(timezone.utc),c,val(row,ok,c),val(row,hk,c),val(row,lk,c)))
    rows.sort(key=lambda x:x.ts); return rows

def _sma(v,n): return sum(v[-n:])/n

def run_window(bars,start_yen=10_000.0,leverage=1.0,spread_bps=2.0,fee_bps=0.0,
               fast=12,slow=36,stop_pct=0.01,take_pct=0.03,target_yen=200_000.0,ruin_yen=1_000.0):
    if leverage<=0 or slow<=fast or len(bars)<=slow: raise ValueError("invalid parameters or insufficient bars")
    equity=float(start_yen); peak=equity; max_dd=0.; pos=0; entry=0.; entry_equity=equity
    trades=wins=0; target_hit=False; cost=(spread_bps+2*fee_bps)/10000.
    for i in range(slow,len(bars)):
        closes=[b.close for b in bars[:i+1]]; bar=bars[i]; price=bar.close
        if price<=0: continue
        signal=1 if _sma(closes,fast)>_sma(closes,slow) else -1
        if pos:
            _,high,low,_=bar.ohlc()
            adverse=(low/entry-1) if pos==1 else (entry/high-1)
            favorable=(high/entry-1) if pos==1 else (entry/low-1)
            exit_raw=None
            if adverse<=-stop_pct: exit_raw=-stop_pct
            elif favorable>=take_pct: exit_raw=take_pct
            elif signal!=pos: exit_raw=pos*(price/entry-1)
            adverse_mark=max(0.,entry_equity*(1+adverse*leverage-leverage*cost))
            peak=max(peak,adverse_mark); max_dd=max(max_dd,(peak-adverse_mark)/peak if peak else 0)
            if adverse_mark<=ruin_yen:
                equity=adverse_mark; trades+=1; pos=0; break
            close_raw=pos*(price/entry-1)
            marked=max(0.,entry_equity*(1+close_raw*leverage-leverage*cost))
            peak=max(peak,marked); max_dd=max(max_dd,(peak-marked)/peak if peak else 0)
            target_hit |= marked>=target_yen
            if exit_raw is not None:
                pnl=entry_equity*(exit_raw*leverage-leverage*cost); equity=max(0.,entry_equity+pnl)
                trades+=1; wins+=pnl>0; pos=0; peak=max(peak,equity)
                max_dd=max(max_dd,(peak-equity)/peak if peak else 0); target_hit |= equity>=target_yen
        if not pos and equity>ruin_yen:
            pos=signal; entry=price; entry_equity=equity
    if pos and equity>ruin_yen:
        raw=pos*(bars[-1].close/entry-1); pnl=entry_equity*(raw*leverage-leverage*cost)
        equity=max(0.,entry_equity+pnl); trades+=1; wins+=pnl>0; peak=max(peak,equity)
        max_dd=max(max_dd,(peak-equity)/peak if peak else 0); target_hit |= equity>=target_yen
    return Result(round(equity,2),round((equity/start_yen-1)*100,4),round(max_dd*100,4),
                  trades,wins,equity<=ruin_yen,target_hit)

def rolling_7d(bars,**kwargs):
    if not bars:return []
    out=[]; cursor=bars[0].ts; end=bars[-1].ts
    while cursor+timedelta(days=7)<=end:
        stop=cursor+timedelta(days=7); chunk=[b for b in bars if cursor<=b.ts<stop]
        if len(chunk)>kwargs.get("slow",36):out.append(run_window(chunk,**kwargs))
        cursor=stop
    return out

def summarize(results):
    if not results:return {"windows":0}
    finals=sorted(r.final_yen for r in results); n=len(finals)
    median=finals[n//2] if n%2 else (finals[n//2-1]+finals[n//2])/2
    return {"windows":n,"target_hits":sum(r.target_hit for r in results),"ruins":sum(r.ruined for r in results),
            "median_final_yen":round(median,2),"best_final_yen":round(max(finals),2),
            "worst_final_yen":round(min(finals),2),"avg_max_dd_pct":round(sum(r.max_dd_pct for r in results)/n,4)}
