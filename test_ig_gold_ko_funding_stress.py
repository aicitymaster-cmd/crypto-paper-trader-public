import unittest
from ig_gold_ko_funding_stress import rollovers_between
from datetime import datetime, timezone
class FundingStressTests(unittest.TestCase):
    def test_rollovers(self):
        a=datetime(2026,1,1,10,tzinfo=timezone.utc)
        b=datetime(2026,1,4,10,tzinfo=timezone.utc)
        self.assertEqual(rollovers_between(a,b),3)
if __name__=="__main__": unittest.main()
