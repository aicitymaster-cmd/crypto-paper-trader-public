import unittest
from gold_ko_stat_robustness import wilson
class StatTests(unittest.TestCase):
    def test_wilson(self):
        lo,hi=wilson(13,36)
        self.assertLess(lo,36.2)
        self.assertGreater(hi,36.0)
        self.assertGreater(lo,0)
        self.assertLess(hi,100)
if __name__=="__main__": unittest.main()
