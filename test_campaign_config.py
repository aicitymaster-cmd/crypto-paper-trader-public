import json
import tempfile
import unittest
from pathlib import Path

from campaign_config import (
    CampaignConfigError,
    load_config,
    require_matching_hash,
)


class FrozenCampaignConfigTests(unittest.TestCase):
    def test_config_loads_and_is_v2_paper_only(self):
        cfg, digest = load_config()
        self.assertEqual(cfg["version"], 2)
        self.assertTrue(cfg["paper_only"])
        self.assertEqual(len(digest), 64)

    def test_start_state_is_fixed(self):
        cfg, _ = load_config()
        initial = cfg["initial_state"]
        self.assertEqual(initial["cash_yen_per_strategy"], "10000")
        self.assertEqual(initial["reserve_yen"], "0")
        self.assertEqual(initial["positions"], {})
        self.assertEqual(initial["trades"], [])

    def test_abc_rules_exist_for_both_speeds(self):
        cfg, _ = load_config()
        self.assertEqual(set(cfg["slow_5m"]["strategies"]), {"A", "B", "C"})
        self.assertEqual(set(cfg["fast_10s"]["strategies"]), {"A", "B", "C"})

    def test_state_hash_is_bound_once(self):
        state = {}
        require_matching_hash(state, "a" * 64)
        self.assertEqual(state["config_sha256"], "a" * 64)
        require_matching_hash(state, "a" * 64)

    def test_changed_config_blocks(self):
        state = {"config_sha256": "a" * 64}
        with self.assertRaisesRegex(
            CampaignConfigError,
            "CONFIG_CHANGED_DURING_CAMPAIGN",
        ):
            require_matching_hash(state, "b" * 64)

    def test_file_change_changes_hash(self):
        cfg, digest = load_config()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cfg.json"
            changed = dict(cfg)
            changed["duration_days"] = 8
            p.write_text(json.dumps(changed), encoding="utf-8")
            _, changed_digest = load_config(p)
        self.assertNotEqual(digest, changed_digest)


if __name__ == "__main__":
    unittest.main()
