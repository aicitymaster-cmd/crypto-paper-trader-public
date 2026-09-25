import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import fast_paper_sampler as m

class FastSamplerTests(unittest.TestCase):
    def test_interval_too_short_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(m.SamplerError, "BAD_INTERVAL"):
                m.run_loop(Path(d) / "x.jsonl", interval=1, duration=10)

    def test_duration_too_long_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(m.SamplerError, "BAD_DURATION"):
                m.run_loop(Path(d) / "x.jsonl", interval=10, duration=300)

    def test_tick_rejects_inverted_spread(self):
        with patch.object(m, "public_get_json", return_value={
            "buy": "102", "sell": "101", "last": "101.5"
        }):
            with self.assertRaisesRegex(m.SamplerError, "INVERTED_SPREAD"):
                m.read_tick("BTC")

    def test_append_trims_history(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.jsonl"
            for i in range(5):
                m.append_jsonl(p, {"i": i}, max_lines=3)
            self.assertEqual(len(p.read_text().splitlines()), 3)

    def test_sample_once_is_paper_only(self):
        fake = {
            "symbol": "BTC", "pair": "btc_jpy", "bid": "1",
            "ask": "2", "last": "1.5", "spread_bps": "1"
        }
        with patch.object(m, "read_tick", return_value=fake):
            out = m.sample_once()
        self.assertTrue(out["paper_only"])
        self.assertEqual(set(out["ticks"]), set(m.PAIRS))

if __name__ == "__main__":
    unittest.main()
