import unittest
import ig_gold_ko_stress as s
class StressTests(unittest.TestCase):
    def test_ranges(self):
        self.assertIn(0.5,s.PREMIUMS)
        self.assertIn(0.6,s.SPREADS)
if __name__=="__main__": unittest.main()
