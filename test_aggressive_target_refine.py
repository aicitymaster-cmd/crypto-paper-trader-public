import unittest
from aggressive_target_refine import s
from cross_market_backtest import Result
class RefineTests(unittest.TestCase):
    def test_counts(self):
        rows=[Result(0,-100,100,1,0,True,True),Result(10000,0,0,1,0,False,False)]
        x=s(rows)
        self.assertEqual(x["target_rate_pct"],50.0)
        self.assertEqual(x["zero_finish_rate_pct"],50.0)
if __name__=="__main__": unittest.main()
