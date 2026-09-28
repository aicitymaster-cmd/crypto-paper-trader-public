"""e038 30-minute forward PAPER engine. Public bitbank data only; no credentials or live orders."""
from __future__ import annotations
import json, ssl, urllib.request, hashlib
from datetime import datetime, timezone
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path\n\nSTRATEGY_SPEC="e038-v1|fraction=.95|take=.25|stop=.03|trail=.025|cooldown=36|max_hold=72|mom12=.025|mom36=.05|breadth=.50|min_vr=1.30|loss_limit=.10|pause_after_losses=2|pause_bars=36"\nSTRATEGY_SHA256=hashlib.sha256(STRATEGY_SPEC.encode()).hexdigest()

PAIRS=["arb_jpy","grt_jpy","gala_jpy","avax_jpy","op_jpy","sui_jpy","xym_jpy","chz_jpy","btc_jpy","eth_jpy","xrp_jpy","ltc_jpy"]
START=D("10000"); FEE=D("0.0015"); SLIP=D("0.0005")
P={"fraction":D(".95"),"take":D(".25"),"stop":D(".03"),"trail":D(".025"),"cooldown":36,"max_hold":72,
   "mom12":D(".025"),"mom36":D(".05"),"breadth":D(".50"),"min_vr":D("1.30"),"loss_limit":D(".10"),
   "pause_after_losses":2,"pause_bars":36}
UA="e038-forward-paper/1.0"

def get_json(url):
    if not url.startswith("https://public.bitbank.cc/"): raise RuntimeError("UNAPPROVED_HOST")
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=15,context=ssl.create_default_context()) as r:
        obj=json.loads(r.read(2_000_001))
    if obj.get("success")!=1: raise RuntimeError("BAD_API")
    return obj["data"]

def fetch(pair,now):
    day=now.strftime("%Y%m%d")
    rows=get_json(f"https://public.bitbank.cc/{pair}/candlestick/30min/{day}")["candlestick"][0]["ohlcv"]
    out=[(int(ts),D(o),D(h),D(l),D(c),D(v)) for o,h,l,c,v,ts in rows]
    cutoff=int(now.timestamp()*1000)-20_000
    return [b for b in out if b[0]+1_800_000<=cutoff]

def sma(xs,n): return sum(xs[-n:],D(0))/D(n)
def breadth(hist):
    good=up=0
    for h in hist.values():
        if len(h)<36: continue
        c=[b[4] for b in h]; good+=1; up+=int(c[-1]>sma(c,12)>sma(c,36))
    return D(up)/D(good) if good else D(0)

def score(h):
    if len(h)<48:return None
    c=[b[4] for b in h]; v=[b[5] for b in h]; last=c[-1]
    m12=last/c[-12]-1; m36=last/c[-36]-1; vr=v[-1]/(sum(v[-12:-1],D(0))/11) if sum(v[-12:-1],D(0))>0 else D(0)
    one=last/c[-2]-1
    if not(last>sma(c,12)>sma(c,36)) or m12<P["mom12"] or m36<P["mom36"] or vr<P["min_vr"] or one>D(".12"):return None
    return m12*2+m36+min(vr,D(3))/25

def fresh():
    return {"paper_only":True,"version":1,"cash":"10000","position":None,"last_exit":{},"fees":"0","sells":0,"wins":0,
            "peak":"10000","max_dd":"0","loss_streak":0,"pause_until_ts":0,"last_bar_ts":None,"strategy_id":"e038-v1-fixed","strategy_sha256":STRATEGY_SHA256,"started_at":None,"cycles":0,"fetch_errors":[],"trades":[]}

def main(path):
    now=datetime.now(timezone.utc); state=fresh()
    p=Path(path)
    if p.exists(): state=json.loads(p.read_text())
    if state.get("paper_only") is not True: raise RuntimeError("NOT_PAPER")\n    if state.get("strategy_id")!="e038-v1-fixed" or state.get("strategy_sha256")!=STRATEGY_SHA256: raise RuntimeError("STRATEGY_CHANGED")
    # Fetch enough warmup across today + prior UTC days.
    hist={s:[] for s in PAIRS}
    from datetime import timedelta
    for back in range(5,-1,-1):
        dt=now-timedelta(days=back)
        for s in PAIRS:
            try:
                day=dt.strftime("%Y%m%d")
                rows=get_json(f"https://public.bitbank.cc/{s}/candlestick/30min/{day}")["candlestick"][0]["ohlcv"]
                cutoff=int(now.timestamp()*1000)-20_000
                hist[s].extend([(int(ts),D(o),D(h),D(l),D(c),D(v)) for o,h,l,c,v,ts in rows if int(ts)+1_800_000<=cutoff])
            except Exception as exc: fetch_errors.append({"symbol":s,"day":day,"error":type(exc).__name__})
    latest=max((h[-1][0] for h in hist.values() if h),default=None)
    if latest is not None:
        fresh_symbols=[s for s,h in hist.items() if h and h[-1][0]==latest]
        if len(fresh_symbols)<8: raise RuntimeError("INSUFFICIENT_FRESH_SYMBOLS")\n        hist={s:h for s,h in hist.items() if s in fresh_symbols}
        if int(now.timestamp()*1000)-(latest+1_800_000)>45*60*1000: raise RuntimeError("STALE_MARKET")
    if latest is None: raise RuntimeError("NO_MARKET_DATA")
    if state["last_bar_ts"]==latest:
        print(json.dumps({"paper_only":True,"status":"NO_NEW_BAR","state":state},ensure_ascii=False)); return
    if state["last_bar_ts"] is not None and latest-int(state["last_bar_ts"])!=1_800_000:
        raise RuntimeError("BAR_GAP_DETECTED")
    prices={s:h[-1][4] for s,h in hist.items() if h}
    pos=state["position"]
    if pos:
        sym=pos["symbol"]; cur=prices[sym]; entry=D(pos["entry"]); peak=max(D(pos["peak"]),cur); pos["peak"]=str(peak)
        held=max(0,(latest-int(pos["entry_ts"]))//1_800_000); trail=peak>=entry*D("1.02") and cur<=peak*(1-P["trail"])
        reason="STOP" if cur<=entry*(1-P["stop"]) else "TAKE" if cur>=entry*(1+P["take"]) else "TRAIL" if trail else "MAX_HOLD" if held>=P["max_hold"] else None
        if reason:
            px=cur*(1-SLIP); gross=D(pos["qty"])*px; fee=gross*FEE; net=gross-fee; pnl=net-D(pos["cost"])
            state["cash"]=str(D(state["cash"])+net); state["fees"]=str(D(state["fees"])+fee); state["sells"]+=1; state["wins"]+=int(pnl>0)
            state["loss_streak"]=0 if pnl>0 else state["loss_streak"]+1; state["last_exit"][sym]=latest
            state["trades"].append({"ts":latest,"symbol":sym,"side":"sell","reason":reason,"pnl":str(pnl)})
            state["position"]=None
            if pnl<=0 and state["loss_streak"]>=P["pause_after_losses"]: state["pause_until_ts"]=latest+P["pause_bars"]*1_800_000; state["loss_streak"]=0
    cash=D(state["cash"])
    eq=cash+(D(state["position"]["qty"])*prices[state["position"]["symbol"]] if state["position"] else 0)
    if not state["position"] and latest>=int(state["pause_until_ts"]) and eq>START*(1-P["loss_limit"]) and breadth(hist)>=P["breadth"]:
        cand=[]
        for s,h in hist.items():
            sc=score(h)
            if sc is not None:
                last=state["last_exit"].get(s)
                if last is None or latest-int(last)>=P["cooldown"]*1_800_000: cand.append((sc,s,h[-1][4]))
        if cand:
            _,sym,close=max(cand); px=close*(1+SLIP); budget=cash*P["fraction"]; qty=(budget/(px*(1+FEE))).quantize(D(".00000001"),rounding=ROUND_DOWN)
            cost=qty*px*(1+FEE)
            if qty>0 and cost<=cash:
                state["cash"]=str(cash-cost); state["fees"]=str(D(state["fees"])+qty*px*FEE)
                state["position"]={"symbol":sym,"qty":str(qty),"entry":str(px),"cost":str(cost),"entry_ts":latest,"peak":str(px)}
                state["trades"].append({"ts":latest,"symbol":sym,"side":"buy","price":str(px),"qty":str(qty)})
    prices={s:h[-1][4] for s,h in hist.items() if h}; cash=D(state["cash"])
    eq=cash+(D(state["position"]["qty"])*prices[state["position"]["symbol"]] if state["position"] else 0)
    state["peak"]=str(max(D(state["peak"]),eq)); state["max_dd"]=str(max(D(state["max_dd"]),(D(state["peak"])-eq)/D(state["peak"])))
    state["last_bar_ts"]=latest\n    state["cycles"]=int(state.get("cycles",0))+1\n    state["fetch_errors"]=fetch_errors[-100:]
    p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    print(json.dumps({"paper_only":True,"status":"OK","equity_yen":str(eq),"state":state},ensure_ascii=False))

if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("--state",required=True); a=ap.parse_args(); main(a.state)
