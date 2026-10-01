import unittest
from conditional_gold_research import summ
from cross_market_backtest import Result
class ConditionalTests(unittest.TestCase):
    def test_summary(self):
        x=summ([Result(50000,400,10,1,1,False,True),Result(0,-100,100,1,0,True,False)])
        self.assertEqual(x["target_rate_pct"],50.0)
        self.assertEqual(x["windows"],2)
if __name__=="__main__": unittest.main()
