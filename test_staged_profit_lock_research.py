import unittest
from staged_profit_lock_research import summarize, LockResult

class StagedLockTests(unittest.TestCase):
    def test_summary(self):
        rows=[
            LockResult(50000,10000,40000,True,False,2),
            LockResult(5000,5000,0,False,True,3),
        ]
        s=summarize(rows)
        self.assertEqual(s["target_rate_pct"],50.0)
        self.assertEqual(s["final_at_least_5000_rate_pct"],100.0)
        self.assertEqual(s["reserve_positive_rate_pct"],100.0)

if __name__=="__main__":
    unittest.main()
