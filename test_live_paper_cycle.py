import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from decimal import Decimal as D
import live_paper_cycle as m


class LivePaperCycleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 25, 8, 15, tzinfo=timezone.utc)

    def market(self, base="100"):
        b = D(base)
        bars = []
        start = int((self.now - timedelta(hours=10)).timestamp() * 1000)
        for i in range(120):
            c = b + D(i) / D("20")
            bars.append(
                (
                    start + i * 300000,
                    c,
                    c + D("1"),
                    c - D("1"),
                    c,
                    D("10"),
                )
            )
        return {
            "symbol": "BTC",
            "pair": "btc_jpy",
            "bid": bars[-1][4] - D(".1"),
            "ask": bars[-1][4] + D(".1"),
            "last": bars[-1][4],
            "bars": bars,
        }

    def test_state_cannot_restart_after_window(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(
                m.PaperCycleError,
                "STATE_MISSING_OUTSIDE_INIT_WINDOW",
            ):
                m.load_or_init(
                    Path(d) / "x.json",
                    now=self.now + timedelta(hours=1),
                    campaign_start=self.now,
                    campaign_end=self.now + timedelta(days=7),
                )

    def test_campaign_is_paper_only(self):
        s = m.new_state(self.now, self.now + timedelta(days=7))
        self.assertTrue(s["paper_only"])
        self.assertEqual(
            set(s["strategies"]),
            set(m.STRATEGIES),
        )

    def test_momentum_can_buy_without_debt(self):
        s = m.new_state(self.now, self.now + timedelta(days=7))
        mk = {"BTC": self.market()}
        m.run_cycle(s, mk, now=self.now)
        a = s["strategies"]["momentum"]
        self.assertGreaterEqual(D(a["cash"]), 0)
        self.assertLessEqual(
            len(a["positions"]),
            m.MAX_POSITIONS,
        )

    def test_ended_does_not_restart(self):
        s = m.new_state(self.now, self.now + timedelta(days=7))
        s["ended"] = True
        before = s["cycles"]
        m.run_cycle(
            s,
            {"BTC": self.market()},
            now=self.now + timedelta(days=8),
        )
        self.assertEqual(s["cycles"], before)

    def test_unknown_strategy_fails_closed(self):
        with self.assertRaises(m.PaperCycleError):
            m.signal("x", self.market())

    def test_fill_uses_spread_and_slippage(self):
        mk = self.market()
        self.assertGreater(
            m.fill_price("buy", mk),
            mk["ask"],
        )
        self.assertLess(
            m.fill_price("sell", mk),
            mk["bid"],
        )


if __name__ == "__main__":
    unittest.main()
