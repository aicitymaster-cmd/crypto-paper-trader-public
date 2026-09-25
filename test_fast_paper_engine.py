import unittest, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal as D
import fast_paper_engine as m

class T(unittest.TestCase):
    def sample(self,i,price):
        return {"at":f"2026-09-25T00:{i//6:02d}:{(i%6)*10:02d}Z","ticks":{"BTC":{"bid":str(D(price)-D('0.1')),"ask":str(D(price)+D('0.1')),"last":str(price)}}}
    def test_future_not_needed(self):
        s=m.new_state(); xs=[self.sample(i,100+i*0.1) for i in range(25)]; n=m.process(s,xs); self.assertEqual(n,25); self.assertEqual(s['last_processed_at'],xs[-1]['at'])
    def test_replay_dedupes(self):
        s=m.new_state(); xs=[self.sample(i,100+i*0.1) for i in range(25)]; m.process(s,xs); self.assertEqual(m.process(s,xs),0)
    def test_cash_never_negative(self):
        s=m.new_state(); xs=[self.sample(i,100+i*0.2) for i in range(30)]; m.process(s,xs)
        for a in s['accounts'].values(): self.assertGreaterEqual(D(a['cash']),0)
    def test_bad_state_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'s.json'; p.write_text('{}')
            now=datetime(2026,9,25,0,0,tzinfo=timezone.utc)
            window={
                "started_at":"2026-09-25T00:00:00Z",
                "ends_at":"2026-09-25T06:00:00Z",
            }
            with self.assertRaises(m.EngineError):
                m.load_state(p, now=now, window=window)
if __name__=='__main__': unittest.main()
