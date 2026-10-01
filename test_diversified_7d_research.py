import unittest
from diversified_7d_research import evaluate, robustness_key

class DiversifiedResearchTests(unittest.TestCase):
    def test_evaluate_tracks_target_and_floor(self):
        s=evaluate([4000,5000,50000,60000])
        self.assertEqual(s["target_hits"],2)
        self.assertEqual(s["at_least_5000"],3)
        self.assertEqual(s["target_rate_pct"],50.0)
        self.assertEqual(s["at_least_5000_rate_pct"],75.0)

    def test_robustness_prefers_both_halves(self):
        def row(a,b,f1=100,f2=100):
            return {"summary":{"first_half":{"target_rate_pct":a,"at_least_5000_rate_pct":f1},
                               "second_half":{"target_rate_pct":b,"at_least_5000_rate_pct":f2},
                               "all":{"target_rate_pct":(a+b)/2,"median_final_yen":10000}}}
        self.assertGreater(robustness_key(row(10,10)),robustness_key(row(30,0)))

if __name__=="__main__":
    unittest.main()
