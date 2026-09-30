from datetime import datetime, timedelta, timezone
import unittest

from cross_market_backtest import Bar
from ko_upper_bound_run import run_window, summarize


class KOUpperBoundTests(unittest.TestCase):
    def base_bars(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return [Bar(t + timedelta(minutes=30*i), 100 + i*0.02) for i in range(37)]

    def test_intrabar_knockout_loses_risk_budget(self):
        bars = self.base_bars()
        t = bars[-1].ts + timedelta(minutes=30)
        bars.append(Bar(t, 100.8, 100.7, 101.0, 99.0))
        r = run_window(bars, distance=0.005, risk_fraction=0.5)
        self.assertLessEqual(r["final_yen"], 5_000.0)

    def test_large_favorable_move_can_hit_target_in_upper_bound(self):
        bars = self.base_bars()
        t = bars[-1].ts
        price = bars[-1].close
        for i in range(1, 8):
            # Strong uninterrupted upside, no adverse excursion.
            c = price * (1 + 0.02 * i)
            bars.append(Bar(t + timedelta(minutes=30*i), c, c, c, c))
        r = run_window(bars, distance=0.0025, risk_fraction=1.0)
        self.assertTrue(r["target_hit"])
        self.assertEqual(r["final_yen"], 200_000.0)

    def test_summary_reports_5000_yen_threshold(self):
        rows = [
            {"final_yen": 4_999.0, "target_hit": False, "ruined": False, "max_dd_pct": 50.0},
            {"final_yen": 5_000.0, "target_hit": False, "ruined": False, "max_dd_pct": 50.0},
            {"final_yen": 200_000.0, "target_hit": True, "ruined": False, "max_dd_pct": 10.0},
        ]
        s = summarize(rows)
        self.assertEqual(s["below_5000"], 1)
        self.assertEqual(s["at_least_5000"], 2)
        self.assertAlmostEqual(s["below_5000_rate_pct"], 33.3333, places=4)
        self.assertAlmostEqual(s["at_least_5000_rate_pct"], 66.6667, places=4)


if __name__ == "__main__":
    unittest.main()
