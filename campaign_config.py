from __future__ import annotations

import hashlib
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("paper_campaign_v2.json")


class CampaignConfigError(RuntimeError):
    pass


def load_config(path: Path = CONFIG_PATH) -> tuple[dict, str]:
    try:
        raw = path.read_bytes()
        cfg = json.loads(raw)
    except Exception as exc:
        raise CampaignConfigError("CONFIG_UNREADABLE") from exc
    if cfg.get("version") != 2 or cfg.get("paper_only") is not True:
        raise CampaignConfigError("CONFIG_INVALID")
    digest = hashlib.sha256(raw).hexdigest()
    return cfg, digest


def require_matching_hash(state: dict, digest: str) -> None:
    saved = state.get("config_sha256")
    if saved is None:
        state["config_sha256"] = digest
        return
    if saved != digest:
        raise CampaignConfigError("CONFIG_CHANGED_DURING_CAMPAIGN")
