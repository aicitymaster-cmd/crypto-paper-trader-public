from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from campaign_config import load_config, CampaignConfigError


class CampaignWindowError(RuntimeError):
    pass


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise CampaignWindowError("NAIVE_TIME")
    return dt.astimezone(timezone.utc)


def resolve_window(path: Path, *, now: datetime, hours: int) -> dict:
    cfg, digest = load_config()
    if int(cfg.get("duration_hours", -1)) != hours:
        raise CampaignWindowError("DURATION_CONFIG_MISMATCH")

    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CampaignWindowError("WINDOW_STATE_UNREADABLE") from exc

        if (
            state.get("paper_only") is not True
            or state.get("version") != 1
            or state.get("config_sha256") != digest
            or int(state.get("duration_hours", -1)) != hours
        ):
            raise CampaignWindowError("WINDOW_STATE_INVALID")

        start = parse_utc(state["started_at"])
        end = parse_utc(state["ends_at"])
        if end - start != timedelta(hours=hours):
            raise CampaignWindowError("WINDOW_LENGTH_INVALID")
    else:
        start = now.astimezone(timezone.utc)
        end = start + timedelta(hours=hours)
        state = {
            "version": 1,
            "paper_only": True,
            "config_sha256": digest,
            "duration_hours": hours,
            "started_at": iso(start),
            "ends_at": iso(end),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    active = start <= now < end
    return {
        **state,
        "active": active,
        "ended": now >= end,
        "status": "ACTIVE" if active else "ENDED" if now >= end else "WAITING",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--hours", type=int, required=True)
    ap.add_argument("--github-output")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    result = resolve_window(Path(args.state), now=now, hours=args.hours)

    if args.github_output:
        out = Path(args.github_output)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(f"active={'true' if result['active'] else 'false'}\n")
            fh.write(f"started_at={result['started_at']}\n")
            fh.write(f"ends_at={result['ends_at']}\n")
            fh.write(f"status={result['status']}\n")

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CampaignWindowError, CampaignConfigError) as exc:
        print(json.dumps({
            "paper_only": True,
            "status": "BLOCKED",
            "reason": str(exc),
        }, ensure_ascii=False))
        raise SystemExit(2)
