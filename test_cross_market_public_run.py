from datetime import datetime, timedelta, timezone
import unittest

from cross_market_public_run import build_url, daily_7d_windows, parse_chart


class CrossMarketPublicRunTests(unittest.TestCase):
    def payload(self, count=400):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [int((start + timedelta(minutes=30*i)).timestamp()) for i in range(count)]
        close = [100.0 + i * 0.01 for i in range(count)]
        return {
            "chart": {
                "result": [{
                    "timestamp": ts,
                    "indicators": {"quote": [{
                        "open": close,
                        "high": [x + 0.02 for x in close],
                        "low": [x - 0.02 for x in close],
                        "close": close,
                    }]},
                }],
                "error": None,
            }
        }

    def test_url_is_https_and_encoded(self):
        url = build_url("JPY=X")
        self.assertTrue(url.startswith("https://query1.finance.yahoo.com/"))
        self.assertIn("JPY%3DX", url)
        self.assertIn("interval=30m", url)

    def test_parse_chart_uses_ohlc(self):
        bars = parse_chart(self.payload())
        self.assertGreater(len(bars), 36)
        self.assertGreater(bars[0].high, bars[0].close)
        self.assertLess(bars[0].low, bars[0].close)

    def test_daily_windows_overlap_by_one_day(self):
        bars = parse_chart(self.payload(count=48 * 20))
        rs = daily_7d_windows(
            bars,
            leverage=1,
            spread_bps=5,
            fee_bps=1,
            fast=12,
            slow=36,
        )
        self.assertGreaterEqual(len(rs), 12)


if __name__ == "__main__":
    unittest.main()
