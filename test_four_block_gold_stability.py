import unittest
import four_block_gold_stability as m
class FourBlockTests(unittest.TestCase):
    def test_module_loads(self):
        self.assertTrue(callable(m.main))
if __name__=="__main__": unittest.main()
