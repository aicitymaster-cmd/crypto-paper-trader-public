"""One-shot read-only cross-market research from Yahoo Chart OHLC data.

No authentication, secrets, order submission, or account access. Results are
research-only and use generic transaction-cost assumptions, not broker quotes.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from cross_market_backtest import Bar, run_window, summarize

HOST = "query1.finance.yahoo.com"
INTERVAL = "30m"
RANGE = "60d"
TIMEOUT = 15
MAX_BYTES = 8_000_000
USER_AGENT = "crypto-paper-trader-public-readonly-research/1.0"

MARKETS = {
    "USDJPY": "JPY=X",
    "EURUSD": "EURUSD=X",
    "GBPJPY": "GBPJPY=X",
    "GOLD": "GC=F",
    "NASDAQ100": "NQ=F",
    "SP500": "ES=F",
}
LEVERAGES = (1, 5, 10, 25)
SPREAD_BPS = 5.0
FEE_BPS = 1.0


class FetchError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FetchError("REDIRECT_NOT_ALLOWED")


def build_url(symbol: str) -> str:
    encoded = urllib.parse.quote(symbol, safe="")
    return (
        f"https://{HOST}/v8/finance/chart/{encoded}"
        f"?range={RANGE}&interval={INTERVAL}&includePrePost=false"
        "&events=div%2Csplits"
    )


def fetch_chart(symbol: str) -> dict:
    url = build_url(symbol)
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirect(),
        urllib.request.HTTPSHandler(context=context),
    )
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            if int(getattr(resp, "status", 0)) != 200:
                raise FetchError("HTTP_NOT_200")
            if resp.geturl() != url:
                raise FetchError("REDIRECT_NOT_ALLOWED")
            body = resp.read(MAX_BYTES + 1)
    except FetchError:
        raise
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP_{exc.code}") from exc
    except Exception as exc:
        raise FetchError("NETWORK_READ_FAILED") from exc
    if len(body) > MAX_BYTES:
        raise FetchError("BODY_TOO_LARGE")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise FetchError("INVALID_JSON") from exc


def parse_chart(payload: dict) -> list[Bar]:
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise FetchError("CHART_ERROR")
    results = chart.get("result") or []
    if not results:
        raise FetchError("NO_RESULT")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    n = min(len(timestamps), len(opens), len(highs), len(lows), len(closes))
    bars: list[Bar] = []
    for i in range(n):
        values = (opens[i], highs[i], lows[i], closes[i])
        if any(v is None for v in values):
            continue
        o, h, l, c = map(float, values)
        if min(o, h, l, c) <= 0:
            continue
        bars.append(
            Bar(
                datetime.fromtimestamp(int(timestamps[i]), tz=timezone.utc),
                c,
                o,
                h,
                l,
            )
        )
    bars.sort(key=lambda b: b.ts)
    if len(bars) < 36 + 1:
        raise FetchError("INSUFFICIENT_BARS")
    return bars


def daily_7d_windows(bars: list[Bar], **kwargs):
    out = []
    cursor = bars[0].ts.replace(hour=0, minute=0, second=0, microsecond=0)
    last = bars[-1].ts
    while cursor + timedelta(days=7) <= last:
        stop = cursor + timedelta(days=7)
        chunk = [b for b in bars if cursor <= b.ts < stop]
        if len(chunk) > kwargs.get("slow", 36):
            out.append(run_window(chunk, **kwargs))
        cursor += timedelta(days=1)
    return out


def run_all() -> dict:
    markets = {}
    failures = {}
    for name, symbol in MARKETS.items():
        try:
            bars = parse_chart(fetch_chart(symbol))
            cases = {}
            for leverage in LEVERAGES:
                results = daily_7d_windows(
                    bars,
                    start_yen=10_000.0,
                    leverage=float(leverage),
                    spread_bps=SPREAD_BPS,
                    fee_bps=FEE_BPS,
                    fast=12,
                    slow=36,
                    stop_pct=0.01,
                    take_pct=0.03,
                    target_yen=200_000.0,
                    ruin_yen=1_000.0,
                )
                s = summarize(results)
                s["target_rate_pct"] = round(
                    100.0 * s.get("target_hits", 0) / s.get("windows", 1), 4
                ) if s.get("windows", 0) else 0.0
                s["ruin_rate_pct"] = round(
                    100.0 * s.get("ruins", 0) / s.get("windows", 1), 4
                ) if s.get("windows", 0) else 0.0
                cases[f"{leverage}x"] = s
            markets[name] = {
                "symbol": symbol,
                "bars": len(bars),
                "first_ts": bars[0].ts.isoformat(),
                "last_ts": bars[-1].ts.isoformat(),
                "cases": cases,
            }
        except Exception as exc:
            failures[name] = f"{type(exc).__name__}:{exc}"
    return {
        "paper_only": True,
        "source": "Yahoo Chart read-only public endpoint",
        "interval": INTERVAL,
        "range": RANGE,
        "start_yen": 10_000,
        "target_yen": 200_000,
        "ruin_yen": 1_000,
        "strategy": {
            "fast": 12,
            "slow": 36,
            "stop_pct": 0.01,
            "take_pct": 0.03,
            "window_days": 7,
            "window_step_days": 1,
        },
        "generic_cost_assumption": {
            "spread_bps": SPREAD_BPS,
            "fee_bps_each_side": FEE_BPS,
            "broker_specific": False,
        },
        "markets": markets,
        "failures": failures,
    }


if __name__ == "__main__":
    data = run_all()
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))
    if data["failures"]:
        raise SystemExit(2)
