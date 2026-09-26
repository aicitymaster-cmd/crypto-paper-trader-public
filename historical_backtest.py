"""Focused 30min high-return spot-only PAPER search.

Target under test: JPY 10,000 -> JPY 200,000 in seven days.
Uses symbols that repeatedly contributed to prior profitable 4-hour searches.
No credentials, no account access, no live orders, no leverage, no borrowing.
"""
from __future__ import annotations
import json, math, ssl, statistics, time, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, ROUND_DOWN
from itertools import product
from pathlib import Path

CFG=json.loads(Path(__file__).with_name("paper_campaign_v2.json").read_text())
RISK=CFG["common_risk"]
START=D("10000"); TARGET=D("200000")
FEE=D(RISK["fee_rate_each_side"]); SLIP=D(RISK["slippage_rate_each_side"])
PAIRS=["arb_jpy","grt_jpy","gala_jpy","avax_jpy","op_jpy","sui_jpy","xym_jpy","chz_jpy","btc_jpy","eth_jpy","xrp_jpy","ltc_jpy"]
UA="crypto-paper-focused-5m-search/1.0"

def get_json(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
    ctx=ssl.create_default_context()
    with urllib.request.urlopen(req,timeout=20,context=ctx) as r: obj=json.loads(r.read())
    if obj.get("success")!=1: raise RuntimeError("API_FAILED")
    return obj["data"]

def fetch_day(pair,day):
    try:
        rows=get_json(f"https://public.bitbank.cc/{pair}/candlestick/30min/{day:%Y%m%d}")["candlestick"][0]["ohlcv"]
        return [(int(ts),D(o),D(h),D(l),D(c),D(v)) for o,h,l,c,v,ts in rows]
    except Exception:
        return []

def sma(xs,n): return sum(xs[-n:],D(0))/D(n)

def profile_grid():
    out={}; i=0
    for take,stop,trail,cooldown,max_hold in product(
        (D("0.05"),D("0.08"),D("0.12"),D("0.18")),
        (D("0.008"),D("0.012"),D("0.020"),D("0.030")),
        (D("0.015"),D("0.025"),D("0.040")),
        (12,36),
        (72,144),
    ):
        i+=1
        out[f"f{i:03d}"]={
          "fraction":D("0.95"),"take":take,"stop":stop,"trail":trail,
          "cooldown":cooldown,"max_hold":max_hold,
          "mom12":D("0.008"),"mom36":D("0.015"),"breadth":D("0.50"),
          "loss_limit":D("0.10"),"pause_after_losses":2,"pause_bars":36
        }
    return out

PROFILES=profile_grid()

def new_account():
    return {"cash":START,"positions":{},"last_exit":{},"fees":D(0),
            "sells":0,"wins":0,"peak":START,"max_dd":D(0),
            "loss_streak":0,"pause_until":-1,"symbols_used":[]}

def equity(a,prices):
    return a["cash"]+sum(p["qty"]*prices[s] for s,p in a["positions"].items() if s in prices)

def market_breadth(hist):
    good=up=0
    for h in hist.values():
        if len(h)<36: continue
        closes=[b[4] for b in h]
        good+=1
        if closes[-1]>sma(closes,12)>sma(closes,36): up+=1
    return D(up)/D(good) if good else D(0)

def score_candidate(h,p):
    if len(h)<48:return None
    closes=[b[4] for b in h]; vols=[b[5] for b in h]
    c=closes[-1]
    m12=c/closes[-12]-D(1); m36=c/closes[-36]-D(1)
    trend=c>sma(closes,12)>sma(closes,36)
    volavg=sum(vols[-12:-1],D(0))/D(11)
    vr=vols[-1]/volavg if volavg>0 else D(0)
    one=c/closes[-2]-D(1)
    if not trend or m12<p["mom12"] or m36<p["mom36"] or vr<D("1.05") or one>D("0.12"):
        return None
    return m12*D("2")+m36+min(vr,D("3"))/D("25")

def buy(a,sym,close,ts,index,p):
    if a["positions"] or index<a["pause_until"]:return
    last=a["last_exit"].get(sym)
    if last is not None and ts-last<p["cooldown"]*30*60*1000:return
    px=close*(D(1)+SLIP); budget=a["cash"]*p["fraction"]
    qty=(budget/(px*(D(1)+FEE))).quantize(D("0.00000001"),rounding=ROUND_DOWN)
    if qty<=0:return
    gross=qty*px; fee=gross*FEE; cost=gross+fee
    if cost>a["cash"]:return
    a["cash"]-=cost; a["fees"]+=fee
    a["positions"][sym]={"qty":qty,"entry":px,"cost":cost,"entry_index":index,"peak":px}
    if sym not in a["symbols_used"]:a["symbols_used"].append(sym)

def sell(a,sym,close,ts):
    pos=a["positions"].pop(sym); px=close*(D(1)-SLIP)
    gross=pos["qty"]*px; fee=gross*FEE; net=gross-fee; pnl=net-pos["cost"]
    a["cash"]+=net; a["fees"]+=fee; a["sells"]+=1; a["last_exit"][sym]=ts
    if pnl>0:
        a["wins"]+=1; a["loss_streak"]=0
    else:
        a["loss_streak"]+=1
    return pnl

def run_window(start_day,bars_by_pair,p):
    start=datetime.combine(start_day,datetime.min.time(),tzinfo=timezone.utc)
    end=start+timedelta(days=7); start_ms=int(start.timestamp()*1000); end_ms=int(end.timestamp()*1000)
    warm_ms=int((start-timedelta(days=1)).timestamp()*1000)
    hist={s:[] for s in PAIRS}; by_ts=defaultdict(dict)
    for sym,bars in bars_by_pair.items():
        for b in bars:
            if warm_ms<=b[0]<end_ms:by_ts[b[0]][sym]=b
    a=new_account(); prices={}
    for index,ts in enumerate(sorted(by_ts)):
        row=by_ts[ts]
        for sym,b in row.items():
            hist[sym].append(b); hist[sym]=hist[sym][-180:]; prices[sym]=b[4]
        if ts<start_ms:continue

        for sym in list(a["positions"]):
            if sym not in row:continue
            cur=row[sym][4]; pos=a["positions"][sym]
            pos["peak"]=max(pos["peak"],cur)
            held=index-pos["entry_index"]
            gain=cur/pos["entry"]-D(1)
            trail_hit=(pos["peak"]>=pos["entry"]*(D(1)+D("0.02")) and
                       cur<=pos["peak"]*(D(1)-p["trail"]))
            should=(cur<=pos["entry"]*(D(1)-p["stop"]) or
                    cur>=pos["entry"]*(D(1)+p["take"]) or
                    trail_hit or held>=p["max_hold"])
            if should:
                pnl=sell(a,sym,cur,ts)
                if pnl<=0 and a["loss_streak"]>=p["pause_after_losses"]:
                    a["pause_until"]=index+p["pause_bars"]; a["loss_streak"]=0

        eq=equity(a,prices)
        if eq<=START*(D(1)-p["loss_limit"]):
            continue

        if not a["positions"] and index>=a["pause_until"] and market_breadth(hist)>=p["breadth"]:
            candidates=[]
            for sym in row:
                sc=score_candidate(hist[sym],p)
                if sc is not None:candidates.append((sc,sym,row[sym][4]))
            if candidates:
                _,sym,close=max(candidates)
                buy(a,sym,close,ts,index,p)

        eq=equity(a,prices); a["peak"]=max(a["peak"],eq)
        if a["peak"]>0:a["max_dd"]=max(a["max_dd"],(a["peak"]-eq)/a["peak"])

    last_ts=max(by_ts) if by_ts else end_ms
    for sym in list(a["positions"]):sell(a,sym,prices[sym],last_ts)
    final=a["cash"]
    return {"final_yen":float(final),"return_pct":float((final/START-D(1))*100),
            "closed_trades":a["sells"],"wins":a["wins"],"fees_yen":float(a["fees"]),
            "max_drawdown_pct":float(a["max_dd"]*100),"hit_200k":final>=TARGET,
            "profitable":final>=START,"symbols_used":sorted(a["symbols_used"])}

def main():
    end_day=(datetime.now(timezone.utc)-timedelta(days=1)).date()
    first=end_day-timedelta(days=56)
    bars={s:[] for s in PAIRS}
    d=first
    while d<=end_day:
        for pair in PAIRS:
            rows=fetch_day(pair,d)
            if rows:bars[pair].extend(rows)
            time.sleep(0.02)
        d+=timedelta(days=1)

    starts=[end_day-timedelta(days=55-7*i) for i in range(8)]
    labels=[f"{s.isoformat()}..{(s+timedelta(days=6)).isoformat()}" for s in starts]
    search_ids=(0,1,2,3); validation_ids=(4,5,6,7)
    candidates=[]; best=None; target_hits=0
    for name,p in PROFILES.items():
        wr=[run_window(s,bars,p) for s in starts]
        target_hits+=sum(int(r["hit_200k"]) for r in wr)
        for i,r in enumerate(wr):
            item={"profile":name,"window":labels[i],**r}
            if best is None or r["final_yen"]>best["final_yen"]:best=item
        vals=[wr[i]["return_pct"] for i in validation_ids]
        nonneg=all(wr[i]["profitable"] for i in validation_ids)
        candidates.append({
          "profile":name,
          "settings":{"take_profit":str(p["take"]),"stop_loss":str(p["stop"]),
                      "trail":str(p["trail"]),"cooldown_bars":p["cooldown"],
                      "max_hold_bars":p["max_hold"]},
          "validation_all_nonnegative":nonneg,
          "validation_avg_return_pct":round(statistics.mean(vals),3),
          "validation_median_return_pct":round(statistics.median(vals),3),
          "validation_worst_return_pct":round(min(vals),3),
          "validation_best_return_pct":round(max(vals),3),
          "validation_target_hits":sum(int(wr[i]["hit_200k"]) for i in validation_ids),
          "validation_windows":[wr[i] for i in validation_ids]
        })

    robust=[x for x in candidates if x["validation_all_nonnegative"]]
    ranked=sorted(candidates,key=lambda x:(x["validation_all_nonnegative"],x["validation_target_hits"],x["validation_median_return_pct"],x["validation_worst_return_pct"]),reverse=True)
    result={
      "paper_only":True,"stage":"expanded_30min_high_return",
      "goal":{"start_yen":10000,"target_yen":200000,"days":7},
      "constraints":{"spot_only":True,"leverage":False,"borrowing":False},
      "pairs":PAIRS,"profiles_tested":len(PROFILES),"total_7day_runs":len(PROFILES)*8,
      "windows":labels,"target_hits_all_runs":target_hits,
      "robust_candidates_count":len(robust),
      "best_single_7day_run":best,
      "top_candidates":ranked[:10],
      "historical_spread_available":False,
      "modeled_costs":{"fee_each_side":str(FEE),"slippage_each_side":str(SLIP),"reserve_rate":"0"}
    }
    print(json.dumps(result,ensure_ascii=False))
    Path("historical-backtest-results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
