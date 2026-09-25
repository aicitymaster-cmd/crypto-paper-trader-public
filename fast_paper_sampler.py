"""10-second PAPER market sampler using public bitbank ticker endpoints only.

No credentials, no account access, no live orders. This is a data-collection
helper intended to run inside a GitHub Actions job for a bounded duration.
"""
from __future__ import annotations

import argparse
import json
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

PAIRS = {
    "BTC": "btc_jpy",
    "ETH": "eth_jpy",
    "SOL": "sol_jpy",
    "XRP": "xrp_jpy",
    "DOGE": "doge_jpy",
}
BASE = "https://public.bitbank.cc"
USER_AGENT = "crypto-paper-fast-sampler/1.0"
TIMEOUT = 8
MAX_BODY = 500_000

class SamplerError(RuntimeError):
    pass

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def dec(value) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise SamplerError("BAD_NUMBER") from exc
    if not out.is_finite() or out <= 0:
        raise SamplerError("BAD_NUMBER")
    return out

def public_get_json(url: str) -> dict:
    if not url.startswith(BASE + "/"):
        raise SamplerError("UNAPPROVED_HOST")
    ctx = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx)
    )
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            if int(getattr(resp, "status", 0)) != 200:
                raise SamplerError("BAD_HTTP_STATUS")
            if resp.geturl() != url:
                raise SamplerError("REDIRECT_NOT_ALLOWED")
            body = resp.read(MAX_BODY + 1)
    except SamplerError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SamplerError("PUBLIC_READ_FAILED") from exc
    if len(body) > MAX_BODY:
        raise SamplerError("BODY_TOO_LARGE")
    try:
        obj = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SamplerError("BAD_JSON") from exc
    if not isinstance(obj, dict) or obj.get("success") != 1:
        raise SamplerError("BAD_API_PAYLOAD")
    data = obj.get("data")
    if not isinstance(data, dict):
        raise SamplerError("BAD_API_PAYLOAD")
    return data

def read_tick(symbol: str) -> dict:
    pair = PAIRS[symbol]
    data = public_get_json(f"{BASE}/{pair}/ticker")
    bid = dec(data.get("buy"))
    ask = dec(data.get("sell"))
    last = dec(data.get("last"))
    if bid > ask:
        raise SamplerError("INVERTED_SPREAD")
    return {
        "symbol": symbol,
        "pair": pair,
        "bid": str(bid),
        "ask": str(ask),
        "last": str(last),
        "spread_bps": str(((ask - bid) / last) * Decimal("10000")),
    }

def sample_once() -> dict:
    ticks = {}
    errors = {}
    for symbol in PAIRS:
        try:
            ticks[symbol] = read_tick(symbol)
        except SamplerError as exc:
            errors[symbol] = str(exc)
    if not ticks:
        raise SamplerError("NO_TICKS")
    return {"at": now_iso(), "paper_only": True, "ticks": ticks, "errors": errors}

def append_jsonl(path: Path, item: dict, max_lines: int = 2500) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            raise SamplerError("STATE_UNREADABLE") from exc
    existing.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    existing = existing[-max_lines:]
    path.write_text("\n".join(existing) + "\n", encoding="utf-8")

def run_loop(path: Path, *, interval: int, duration: int) -> int:
    if interval < 5 or interval > 60:
        raise SamplerError("BAD_INTERVAL")
    if duration < interval or duration > 270:
        raise SamplerError("BAD_DURATION")
    start = time.monotonic()
    count = 0
    while True:
        item = sample_once()
        append_jsonl(path, item)
        count += 1
        elapsed = time.monotonic() - start
        remaining = duration - elapsed
        if remaining < interval:
            break
        time.sleep(interval)
    print(json.dumps({
        "paper_only": True,
        "samples": count,
        "interval_seconds": interval,
        "duration_seconds": duration,
    }, ensure_ascii=False))
    return 0

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--interval", type=int, default=10)
    ap.add_argument("--duration", type=int, default=240)
    args = ap.parse_args(argv)
    return run_loop(Path(args.output), interval=args.interval, duration=args.duration)

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SamplerError as exc:
        print(json.dumps({
            "paper_only": True,
            "status": "BLOCKED",
            "reason": str(exc),
        }, ensure_ascii=False))
        raise SystemExit(2)
