import unittest
from frozen_gold_order_plan import plan
class PlanTests(unittest.TestCase):
    def test_waiting_has_no_plan(self):
        p=plan({"status":"WAITING_ENTRY_WINDOW"})
        self.assertFalse(p["order_allowed"])
    def test_eligible(self):
        p=plan({"status":"ELIGIBLE","entry_reference_price":4000})
        self.assertEqual(p["bull_ko_reference"],3970.0)
        self.assertEqual(p["bear_ko_reference"],4030.0)
        self.assertFalse(p["order_allowed"])
if __name__=="__main__": unittest.main()
