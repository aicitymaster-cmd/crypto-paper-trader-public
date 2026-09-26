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

    def test_bitbank_candle_dates_use_utc_not_jst(self):
        now = datetime(2026, 9, 25, 15, 36, tzinfo=timezone.utc)
        seen = []

        latest_start = int((now - timedelta(minutes=15)).timestamp() * 1000)
        rows = []
        for i in range(60):
            ts = latest_start - (59 - i) * 300000
            rows.append(["100", "101", "99", "100", "10", ts])

        def getter(url):
            seen.append(url)
            if url.endswith("/ticker"):
                return {"sell": "100.1", "buy": "99.9", "last": "100"}
            return {"candlestick": [{"ohlcv": rows}]}

        m.fetch_market("BTC", now=now, getter=getter)
        candle_urls = [u for u in seen if "/candlestick/" in u]
        self.assertTrue(any(u.endswith("/20260925") for u in candle_urls))
        self.assertTrue(any(u.endswith("/20260924") for u in candle_urls))
        self.assertFalse(any(u.endswith("/20260926") for u in candle_urls))

    def test_campaign_end_liquidates_open_positions_once(self):
        state = m.new_state(self.now, self.now + timedelta(hours=2))
        account = state["strategies"]["mean_reversion"]
        account["cash"] = "9000"
        account["positions"]["BTC"] = {
            "qty": "10",
            "entry_price": "100",
            "cost_basis": "1000",
            "entry_at": m.iso(self.now),
            "entry_bar": 0,
        }
        market = self.market()
        m.finalize_campaign(state, {"BTC": market}, now=self.now)

        self.assertTrue(state["ended"])
        self.assertEqual(account["positions"], {})
        sells = [t for t in account["trades"] if t["side"] == "sell"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0]["reason"], "CAMPAIGN_END")
        first_cash = account["cash"]

        m.finalize_campaign(state, {"BTC": market}, now=self.now + timedelta(minutes=5))
        self.assertEqual(account["cash"], first_cash)
        self.assertEqual(
            len([t for t in account["trades"] if t["side"] == "sell"]),
            1,
        )

    def test_campaign_end_requires_price_for_every_open_position(self):
        state = m.new_state(self.now, self.now + timedelta(hours=2))
        account = state["strategies"]["mean_reversion"]
        account["positions"]["BTC"] = {
            "qty": "1",
            "entry_price": "100",
            "cost_basis": "100",
            "entry_at": m.iso(self.now),
            "entry_bar": 0,
        }
        with self.assertRaisesRegex(
            m.PaperCycleError,
            "FINALIZATION_MARKET_MISSING:BTC",
        ):
            m.finalize_campaign(state, {}, now=self.now)
        self.assertFalse(state["ended"])
        self.assertIn("BTC", account["positions"])


if __name__ == "__main__":
    unittest.main()
