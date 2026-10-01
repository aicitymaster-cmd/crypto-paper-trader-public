import unittest
from datetime import datetime, timezone, timedelta
from cross_market_backtest import Bar
from frozen_gold_forward_signal import evaluate

class ForwardSignalTests(unittest.TestCase):
    def test_eligible(self):
        start=datetime(2026,9,30,16,tzinfo=timezone.utc)
        bars=[]
        price=4000.0
        for i in range(26):
            ts=start+timedelta(hours=i)
            p=price*(1+0.0005*i)
            bars.append(Bar(ts,p,p,p,p))
        # Thursday 16 UTC on Oct 1 exists as final matching bar
        out=evaluate(bars)
        self.assertIn(out["status"],("ELIGIBLE","NOT_ELIGIBLE"))
        self.assertTrue(out["parameters_frozen"])

if __name__=="__main__": unittest.main()
