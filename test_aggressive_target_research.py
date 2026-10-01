import unittest
from aggressive_target_research import summarize, rank_key
from cross_market_backtest import Result

class AggressiveTargetTests(unittest.TestCase):
    def test_summary_counts_touch_and_zero(self):
        rows=[
            Result(0, -100, 100, 1,0,True,True),
            Result(1000,-90,90,1,0,False,False),
        ]
        s=summarize(rows)
        self.assertEqual(s["target_hits"],1)
        self.assertEqual(s["zero_finishes"],1)
        self.assertEqual(s["target_rate_pct"],50.0)

    def test_rank_prefers_repeatable_hits(self):
        a={"summary":{"first_half":{"target_rate_pct":10},"second_half":{"target_rate_pct":10},"all":{"target_rate_pct":10,"zero_finish_rate_pct":80}}}
        b={"summary":{"first_half":{"target_rate_pct":30},"second_half":{"target_rate_pct":0},"all":{"target_rate_pct":15,"zero_finish_rate_pct":20}}}
        self.assertGreater(rank_key(a),rank_key(b))

if __name__=="__main__":
    unittest.main()
