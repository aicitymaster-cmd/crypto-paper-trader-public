import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import campaign_window


class TwoHourCampaignWindowTests(unittest.TestCase):
    def test_first_run_sets_exact_two_hour_window(self):
        now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "window.json"
            result = campaign_window.resolve_window(p, now=now, hours=2)
            self.assertTrue(result["active"])
            self.assertFalse(result["ended"])
            self.assertEqual(
                campaign_window.parse_utc(result["ends_at"])
                - campaign_window.parse_utc(result["started_at"]),
                timedelta(hours=2),
            )

    def test_existing_window_does_not_restart(self):
        start = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "window.json"
            first = campaign_window.resolve_window(p, now=start, hours=2)
            later = campaign_window.resolve_window(
                p, now=start + timedelta(hours=2), hours=2
            )
            self.assertEqual(first["started_at"], later["started_at"])
            self.assertEqual(first["ends_at"], later["ends_at"])

    def test_after_two_hours_is_ended(self):
        start = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "window.json"
            campaign_window.resolve_window(p, now=start, hours=2)
            ended = campaign_window.resolve_window(
                p, now=start + timedelta(hours=2), hours=2
            )
            self.assertFalse(ended["active"])
            self.assertTrue(ended["ended"])
            self.assertEqual(ended["status"], "ENDED")

    def test_duration_mismatch_blocks(self):
        now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "window.json"
            with self.assertRaisesRegex(
                campaign_window.CampaignWindowError,
                "DURATION_CONFIG_MISMATCH",
            ):
                campaign_window.resolve_window(p, now=now, hours=7)


if __name__ == "__main__":
    unittest.main()
