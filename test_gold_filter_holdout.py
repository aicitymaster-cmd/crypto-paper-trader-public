import unittest
from gold_filter_holdout import summ
from cross_market_backtest import Result
class HoldoutTests(unittest.TestCase):
    def test_summary(self):
        x=summ([Result(50000,400,1,1,1,False,True),Result(0,-100,100,1,0,True,False)])
        self.assertEqual(x["target_rate_pct"],50.0)
if __name__=="__main__": unittest.main()
