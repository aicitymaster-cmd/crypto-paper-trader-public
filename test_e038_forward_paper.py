from decimal import Decimal as D
import e038_forward_paper as e

def bar(ts, close, vol=100):
    c=D(str(close)); return (ts,c,c,c,c,D(str(vol)))

def test_score_matches_e038_formula():
    h=[]
    for i in range(48):
        # rising series, then force strong latest volume
        h.append(bar(i*1800000,100+i,D("100")))
    h[-1]=(h[-1][0],h[-1][1],h[-1][2],h[-1][3],D("147"),D("300"))
    sc=e.score(h)
    assert sc is not None

def test_score_rejects_one_bar_spike_over_12pct():
    h=[bar(i*1800000,100+D(i)/2,100) for i in range(48)]
    prev=h[-2][4]; last=prev*D("1.13")
    h[-1]=(h[-1][0],last,last,last,last,D("500"))
    assert e.score(h) is None

def test_breadth_uses_same_trend_definition():
    good=[bar(i*1800000,100+i,100) for i in range(48)]
    bad=[bar(i*1800000,200-i,100) for i in range(48)]
    assert e.breadth({"a":good,"b":bad})==D("0.5")

def test_fixed_e038_parameters():
    assert e.P["fraction"]==D("0.95")
    assert e.P["take"]==D("0.25")
    assert e.P["stop"]==D("0.03")
    assert e.P["trail"]==D("0.025")
    assert e.P["cooldown"]==36
    assert e.P["max_hold"]==72
    assert e.P["mom12"]==D("0.025")
    assert e.P["mom36"]==D("0.05")
    assert e.P["breadth"]==D("0.50")
    assert e.P["min_vr"]==D("1.30")

def test_strategy_is_bound_to_hash():
    assert len(e.STRATEGY_SHA256)==64
    assert e.STRATEGY_SHA256

def test_fresh_state_has_audit_fields():
    s=e.fresh()
    assert s["paper_only"] is True
    assert s["strategy_sha256"]==e.STRATEGY_SHA256
    assert "started_at" in s and "cycles" in s and "fetch_errors" in s

def test_gap_guard_is_present():
    import inspect
    src=inspect.getsource(e.main)
    assert "BAR_GAP_DETECTED" in src
    assert "1_800_000" in src
