from datetime import datetime, timedelta, timezone
import unittest

from cross_market_backtest import Bar, rolling_7d, run_window, summarize


class CrossMarketTests(unittest.TestCase):
    def bars(self, count=400, step=0.001):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return [Bar(t + timedelta(hours=i), 100.0 * ((1 + step) ** i)) for i in range(count)]

    def test_costs_reduce_equity(self):
        bars = self.bars()
        free = run_window(bars, leverage=2, spread_bps=0)
        costly = run_window(bars, leverage=2, spread_bps=10)
        self.assertLess(costly.final_yen, free.final_yen)

    def test_no_live_side_effects_and_target_is_explicit(self):
        r = run_window(self.bars(), leverage=1, target_yen=200_000)
        self.assertGreater(r.trades, 0)
        self.assertFalse(r.ruined)
        self.assertIsInstance(r.target_hit, bool)

    def test_mark_to_market_can_trigger_ruin(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        prices = [100 + i * 0.1 for i in range(37)] + [95.0]
        bars = [Bar(t + timedelta(hours=i), p) for i, p in enumerate(prices)]
        r = run_window(bars, leverage=25, spread_bps=0, stop_pct=1.0)
        self.assertTrue(r.ruined)
        self.assertLessEqual(r.final_yen, 1_000)

    def test_rolling_windows_and_summary(self):
        bars = self.bars(count=24 * 21 + 40)
        rs = rolling_7d(bars, leverage=1)
        s = summarize(rs)
        self.assertGreaterEqual(s["windows"], 3)
        self.assertIn("target_hits", s)
        self.assertIn("ruins", s)


if __name__ == "__main__":
    unittest.main()
