import unittest
from ig_gold_ko_realistic import floor_step
class IGRealisticTests(unittest.TestCase):
    def test_floor_step(self):
        self.assertAlmostEqual(floor_step(1.879,0.04),1.84)
        self.assertAlmostEqual(floor_step(1.879,0.1),1.8)
if __name__=="__main__": unittest.main()
