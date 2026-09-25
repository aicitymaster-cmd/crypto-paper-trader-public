import unittest
from decimal import Decimal as D

import fast_paper_engine as fast
import live_paper_cycle as slow


class NetProfitEntryGateTests(unittest.TestCase):
    def test_slow_gate_passes_normal_spread(self):
        market={"ask":D("100.05"),"bid":D("99.95"),"last":D("100")}
        self.assertGreaterEqual(
            slow.projected_net_return_at_take_profit(market),
            slow.MIN_PROJECTED_NET_RETURN,
        )

    def test_slow_gate_blocks_excessive_spread(self):
        market={"ask":D("101"),"bid":D("99"),"last":D("100")}
        self.assertLess(
            slow.projected_net_return_at_take_profit(market),
            slow.MIN_PROJECTED_NET_RETURN,
        )

    def test_fast_gate_passes_normal_spread(self):
        tick={"ask":"100.05","bid":"99.95","last":"100"}
        self.assertGreaterEqual(
            fast.projected_net_return_at_take_profit(tick),
            fast.MIN_NET,
        )

    def test_fast_gate_blocks_excessive_spread(self):
        tick={"ask":"101","bid":"99","last":"100"}
        self.assertLess(
            fast.projected_net_return_at_take_profit(tick),
            fast.MIN_NET,
        )


if __name__ == "__main__":
    unittest.main()
