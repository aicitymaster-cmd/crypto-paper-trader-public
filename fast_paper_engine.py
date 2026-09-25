"""Replay 10-second ticker samples sequentially for PAPER-only strategy testing."""
from __future__ import annotations
import argparse, json, math
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, InvalidOperation, ROUND_DOWN
from pathlib import Path
from campaign_config import load_config, require_matching_hash, CampaignConfigError
from campaign_window import resolve_window, CampaignWindowError

CFG, CONFIG_SHA256 = load_config()
FAST_CFG = CFG["fast_10s"]
RISK_CFG = CFG["common_risk"]
STRATEGIES=tuple(v["name"] for v in FAST_CFG["strategies"].values())
START=D(CFG["initial_state"]["cash_yen_per_strategy"])
FEE=D(RISK_CFG["fee_rate_each_side"]); SLIP=D(RISK_CFG["slippage_rate_each_side"]); FRACTION=D(FAST_CFG["trade_fraction"])
MAX_POS=int(RISK_CFG["max_positions"]); STOP=D(FAST_CFG["stop_loss"]); TAKE=D(FAST_CFG["take_profit"]); MAX_HOLD=int(FAST_CFG["max_hold_samples"]); MIN_NET=D(RISK_CFG["minimum_projected_net_return"])

class EngineError(RuntimeError): pass

def dec(x):
    try:v=D(str(x))
    except (InvalidOperation,ValueError,TypeError) as e: raise EngineError("BAD_NUMBER") from e
    if not v.is_finite() or v<=0: raise EngineError("BAD_NUMBER")
    return v

def parse_time(s):
    if s.endswith("Z"):s=s[:-1]+"+00:00"
    d=datetime.fromisoformat(s)
    if d.tzinfo is None: raise EngineError("NAIVE_TIME")
    return d.astimezone(timezone.utc)

def new_state():
    return {"paper_only":True,"version":1,"config_sha256":CONFIG_SHA256,"last_processed_at":None,"hist":{},"accounts":{s:{"cash":"10000","reserve":"0","positions":{},"trades":[]} for s in STRATEGIES}}

def load_state(path, *, now, window):
    if not path.exists():
        start=parse_time(window["started_at"])
        if now > start + timedelta(minutes=30):
            raise EngineError("STATE_MISSING_OUTSIDE_INIT_WINDOW")
        return new_state()
    try:s=json.loads(path.read_text())
    except Exception as e: raise EngineError("STATE_UNREADABLE") from e
    if s.get("paper_only") is not True or s.get("version")!=1: raise EngineError("STATE_INVALID")
    try: require_matching_hash(s, CONFIG_SHA256)
    except CampaignConfigError as e: raise EngineError(str(e)) from e
    return s

def z(vals):
    xs=[float(x) for x in vals]
    m=sum(xs)/len(xs); sd=math.sqrt(sum((x-m)**2 for x in xs)/len(xs))
    return 0.0 if sd==0 else (xs[-1]-m)/sd

def sig(strategy,h):
    if len(h)<20:return "skip"
    cur=h[-1]
    if strategy=="fast_momentum":
        return "buy" if cur>h[-6]>h[-18] else "sell" if cur<h[-6] else "skip"
    if strategy=="fast_breakout":
        return "buy" if cur>max(h[-13:-1]) else "sell" if cur<sum(h[-6:])/D(6) else "skip"
    if strategy=="fast_mean_reversion":
        zz=z(h[-20:]); trend=sum(h[-10:])/D(10)>=sum(h[-20:])/D(20)*D("0.995")
        return "buy" if zz<=-1.5 and trend else "sell" if zz>=0 else "skip"
    raise EngineError("UNKNOWN_STRATEGY")

def projected_net_return_at_take_profit(tick):
    ask=dec(tick["ask"]); bid=dec(tick["bid"]); last=dec(tick["last"])
    buy_px=ask*(D(1)+SLIP)
    entry_cost=buy_px*(D(1)+FEE)
    spread_ratio=bid/last
    future_bid=last*(D(1)+TAKE)*spread_ratio
    exit_px=future_bid*(D(1)-SLIP)
    exit_net=exit_px*(D(1)-FEE)
    return (exit_net/entry_cost)-D(1)

def buy(a,sym,tick,at,index):
    if sym in a["positions"] or len(a["positions"])>=MAX_POS:return
    if projected_net_return_at_take_profit(tick) < MIN_NET:return
    cash=D(a["cash"]); ask=dec(tick["ask"]); px=ask*(D(1)+SLIP); budget=cash*FRACTION
    qty=(budget/(px*(D(1)+FEE))).quantize(D("0.00000001"),rounding=ROUND_DOWN)
    if qty<=0:return
    gross=qty*px; fee=gross*FEE; cost=gross+fee
    if cost>cash:return
    a["cash"]=str(cash-cost); a["positions"][sym]={"qty":str(qty),"entry":str(px),"cost":str(cost),"index":index}
    a["trades"].append({"at":at,"symbol":sym,"side":"buy","price":str(px),"qty":str(qty),"fee":str(fee)})

def sell(a,sym,tick,at,reason):
    p=a["positions"].pop(sym); qty=D(p["qty"]); bid=dec(tick["bid"]); px=bid*(D(1)-SLIP)
    gross=qty*px; fee=gross*FEE; net=gross-fee; pnl=net-D(p["cost"]); reserve=max(D(0),pnl*D("0.5"))
    a["cash"]=str(D(a["cash"])+net-reserve); a["reserve"]=str(D(a["reserve"])+reserve)
    a["trades"].append({"at":at,"symbol":sym,"side":"sell","price":str(px),"qty":str(qty),"fee":str(fee),"pnl":str(pnl),"reason":reason})

def process(state,samples):
    last=parse_time(state["last_processed_at"]) if state["last_processed_at"] else None
    processed=0
    for sample in samples:
        at=parse_time(sample["at"])
        if last and at<=last: continue
        ticks=sample.get("ticks") or {}
        if not ticks: continue
        for sym,t in ticks.items():
            hist=state["hist"].setdefault(sym,[]); hist.append(str(dec(t["last"]))); state["hist"][sym]=hist[-120:]
        idx=processed
        for strategy,a in state["accounts"].items():
            for sym in list(a["positions"]):
                if sym not in ticks:continue
                p=a["positions"][sym]; cur=dec(ticks[sym]["last"]); ent=D(p["entry"]); reason=None
                if cur<=ent*(D(1)-STOP):reason="STOP"
                elif cur>=ent*(D(1)+TAKE):reason="TAKE"
                elif idx-int(p["index"])>=MAX_HOLD:reason="MAX_HOLD"
                elif sig(strategy,[D(x) for x in state["hist"].get(sym,[])])=="sell":reason="EXIT_SIGNAL"
                if reason:sell(a,sym,ticks[sym],sample["at"],reason)
            for sym,t in ticks.items():
                if len(a["positions"])>=MAX_POS:break
                h=[D(x) for x in state["hist"].get(sym,[])]
                if sig(strategy,h)=="buy":buy(a,sym,t,sample["at"],idx)
        state["last_processed_at"]=sample["at"]; last=at; processed+=1
    return processed

def read_jsonl(path):
    out=[]
    if not path.exists():return out
    for line in path.read_text().splitlines():
        if line.strip(): out.append(json.loads(line))
    return out

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--samples",required=True); ap.add_argument("--state",required=True); ap.add_argument("--window",required=True)
    a=ap.parse_args(argv)
    now=datetime.now(timezone.utc)
    try:
        window=resolve_window(Path(a.window),now=now,hours=int(CFG["duration_hours"]))
    except CampaignWindowError as e:
        raise EngineError(str(e)) from e
    if not window["active"]:
        print(json.dumps({"paper_only":True,"status":"ENDED","started_at":window["started_at"],"ends_at":window["ends_at"]},ensure_ascii=False)); return 0
    sp=Path(a.samples); st=Path(a.state); state=load_state(st,now=now,window=window); n=process(state,read_jsonl(sp)); st.parent.mkdir(parents=True,exist_ok=True); st.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    print(json.dumps({"paper_only":True,"processed_samples":n,"last_processed_at":state["last_processed_at"],"started_at":window["started_at"],"ends_at":window["ends_at"]},ensure_ascii=False)); return 0
if __name__=="__main__":
    try: raise SystemExit(main())
    except EngineError as e:
        print(json.dumps({"paper_only":True,"status":"BLOCKED","reason":str(e)},ensure_ascii=False)); raise SystemExit(2)
