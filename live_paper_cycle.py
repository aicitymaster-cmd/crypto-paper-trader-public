"""Five-minute public-market PAPER validation loop.

No credentials, no account access, no live orders. Public HTTPS GET only.
State is a local JSON file supplied by the workflow cache. If state disappears
after the initialization window, the campaign fails closed and will not restart.
"""
from __future__ import annotations

import argparse
import json
import math
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo
from campaign_config import load_config, require_matching_hash, CampaignConfigError
from campaign_window import resolve_window, CampaignWindowError

D = Decimal
JST = ZoneInfo("Asia/Tokyo")
ASSETS = {
    "BTC": "btc_jpy",
    "ETH": "eth_jpy",
    "SOL": "sol_jpy",
    "XRP": "xrp_jpy",
    "DOGE": "doge_jpy",
}
CFG, CONFIG_SHA256 = load_config()
SLOW_CFG = CFG["slow_5m"]
RISK_CFG = CFG["common_risk"]
STRATEGIES = tuple(v["name"] for v in SLOW_CFG["strategies"].values())
START_YEN = D(CFG["initial_state"]["cash_yen_per_strategy"])
TRADE_FRACTION = D(SLOW_CFG["trade_fraction"])
FEE_RATE = D(RISK_CFG["fee_rate_each_side"])
SLIPPAGE_RATE = D(RISK_CFG["slippage_rate_each_side"])
RESERVE_RATE = D(RISK_CFG["reserve_rate"])
MAX_POSITIONS = int(RISK_CFG["max_positions"])
MAX_HOLD_BARS = int(SLOW_CFG["max_hold_bars"])
STOP_LOSS = D(SLOW_CFG["stop_loss"])
TAKE_PROFIT = D(SLOW_CFG["take_profit"])
MIN_PROJECTED_NET_RETURN = D(RISK_CFG["minimum_projected_net_return"])
MAX_BODY = 2_000_000
TIMEOUT = 8
USER_AGENT = "crypto-paper-public-validation/1.0"


class PaperCycleError(RuntimeError):
    pass


def dec(v: object) -> Decimal:
    try:
        x = D(str(v))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PaperCycleError("BAD_NUMBER") from exc
    if not x.is_finite():
        raise PaperCycleError("BAD_NUMBER")
    return x


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise PaperCycleError("NAIVE_TIME")
    return dt.astimezone(timezone.utc)


def public_get_json(url: str) -> dict:
    if not url.startswith("https://public.bitbank.cc/"):
        raise PaperCycleError("UNAPPROVED_HOST")
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
        with opener.open(req, timeout=TIMEOUT) as r:
            if int(getattr(r, "status", 0)) != 200:
                raise PaperCycleError("BAD_HTTP_STATUS")
            if r.geturl() != url:
                raise PaperCycleError("REDIRECT_NOT_ALLOWED")
            body = r.read(MAX_BODY + 1)
    except PaperCycleError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PaperCycleError("PUBLIC_READ_FAILED") from exc
    if len(body) > MAX_BODY:
        raise PaperCycleError("BODY_TOO_LARGE")
    try:
        obj = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PaperCycleError("BAD_JSON") from exc
    if (
        not isinstance(obj, dict)
        or obj.get("success") != 1
        or not isinstance(obj.get("data"), dict)
    ):
        raise PaperCycleError("BAD_API_PAYLOAD")
    return obj["data"]


def fetch_market(
    symbol: str,
    *,
    now: datetime,
    getter: Callable[[str], dict] = public_get_json,
) -> dict:
    pair = ASSETS[symbol]
    ticker = getter(f"https://public.bitbank.cc/{pair}/ticker")
    ask = dec(ticker.get("sell"))
    bid = dec(ticker.get("buy"))
    last = dec(ticker.get("last"))
    if min(ask, bid, last) <= 0 or bid > ask:
        raise PaperCycleError("BAD_TICKER")

    utc_now = now.astimezone(timezone.utc)
    days = [
        (utc_now - timedelta(days=1)).strftime("%Y%m%d"),
        utc_now.strftime("%Y%m%d"),
    ]
    bars: list[tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal]] = []
    for day in days:
        data = getter(
            f"https://public.bitbank.cc/{pair}/candlestick/5min/{day}"
        )
        cs = data.get("candlestick")
        if not isinstance(cs, list) or not cs:
            raise PaperCycleError("BAD_CANDLES")
        rows = cs[0].get("ohlcv") if isinstance(cs[0], dict) else None
        if not isinstance(rows, list):
            raise PaperCycleError("BAD_CANDLES")
        for row in rows:
            if not isinstance(row, list) or len(row) != 6:
                continue
            o, h, l, c, v, ts = row
            try:
                tup = (int(ts), dec(o), dec(h), dec(l), dec(c), dec(v))
            except (ValueError, TypeError, PaperCycleError):
                continue
            if min(tup[1], tup[2], tup[3], tup[4]) > 0 and tup[5] >= 0:
                bars.append(tup)

    by_ts = {b[0]: b for b in bars}
    bars = [by_ts[k] for k in sorted(by_ts)]
    cutoff_ms = int((now - timedelta(seconds=20)).timestamp() * 1000)
    bars = [b for b in bars if b[0] + 5 * 60 * 1000 <= cutoff_ms]
    if len(bars) < 60:
        raise PaperCycleError("INSUFFICIENT_CANDLES")
    latest_age = now.timestamp() - ((bars[-1][0] / 1000) + 5 * 60)
    if latest_age < -5 or latest_age > 12 * 60:
        raise PaperCycleError("STALE_CANDLES")
    return {
        "symbol": symbol,
        "pair": pair,
        "bid": bid,
        "ask": ask,
        "last": last,
        "bars": bars[-120:],
    }


def sma(xs: list[Decimal], n: int) -> Decimal:
    return sum(xs[-n:], D("0")) / D(n)


def zscore(xs: list[Decimal], n: int) -> Decimal:
    vals = [float(x) for x in xs[-n:]]
    mean = sum(vals) / n
    var = sum((x - mean) ** 2 for x in vals) / n
    sd = math.sqrt(var)
    if sd == 0:
        return D("0")
    return D(str((vals[-1] - mean) / sd))


def signal(strategy: str, market: dict) -> str:
    bars = market["bars"]
    closes = [b[4] for b in bars]
    highs = [b[2] for b in bars]
    c = closes[-1]
    if strategy == "momentum":
        s12, s36 = sma(closes, 12), sma(closes, 36)
        return (
            "buy"
            if c > s12 > s36 and closes[-1] > closes[-4]
            else "sell"
            if c < s12
            else "skip"
        )
    if strategy == "breakout":
        prior_high = max(highs[-21:-1])
        return (
            "buy"
            if c > prior_high
            else "sell"
            if c < sma(closes, 12)
            else "skip"
        )
    if strategy == "mean_reversion":
        z = zscore(closes, 20)
        trend = sma(closes, 20) >= sma(closes, 50) * D("0.985")
        return (
            "buy"
            if z <= D("-1.5") and trend
            else "sell"
            if z >= D("0")
            else "skip"
        )
    raise PaperCycleError("UNKNOWN_STRATEGY")


def new_state(start: datetime, end: datetime) -> dict:
    return {
        "version": 1,
        "paper_only": True,
        "config_sha256": CONFIG_SHA256,
        "campaign_start": iso(start),
        "campaign_end": iso(end),
        "ended": False,
        "cycles": 0,
        "last_cycle": None,
        "strategies": {
            s: {
                "cash": str(START_YEN),
                "reserve": "0",
                "positions": {},
                "trades": [],
                "realized_pnl": "0",
            }
            for s in STRATEGIES
        },
        "last_prices": {},
        "errors": [],
    }


def load_or_init(
    path: Path,
    *,
    now: datetime,
    campaign_start: datetime,
    campaign_end: datetime,
) -> dict:
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PaperCycleError("STATE_UNREADABLE") from exc
        if state.get("paper_only") is not True or state.get("version") != 1:
            raise PaperCycleError("STATE_INVALID")
        try:
            require_matching_hash(state, CONFIG_SHA256)
        except CampaignConfigError as exc:
            raise PaperCycleError(str(exc)) from exc
        if (
            state.get("campaign_start") != iso(campaign_start)
            or state.get("campaign_end") != iso(campaign_end)
        ):
            raise PaperCycleError("CAMPAIGN_MISMATCH")
        return state

    if (
        now < campaign_start
        or now > campaign_start + timedelta(minutes=30)
    ):
        raise PaperCycleError("STATE_MISSING_OUTSIDE_INIT_WINDOW")
    return new_state(campaign_start, campaign_end)


def fill_price(side: str, market: dict) -> Decimal:
    if side == "buy":
        return market["ask"] * (D("1") + SLIPPAGE_RATE)
    return market["bid"] * (D("1") - SLIPPAGE_RATE)


def equity(account: dict, prices: dict[str, Decimal]) -> Decimal:
    total = dec(account["cash"]) + dec(account["reserve"])
    for symbol, p in account["positions"].items():
        if symbol not in prices:
            raise PaperCycleError("MISSING_VALUATION_PRICE")
        total += dec(p["qty"]) * prices[symbol]
    return total


def sell(
    account: dict,
    symbol: str,
    market: dict,
    at: datetime,
    reason: str,
) -> None:
    pos = account["positions"].pop(symbol)
    qty = dec(pos["qty"])
    entry_cost = dec(pos["cost_basis"])
    px = fill_price("sell", market)
    gross = qty * px
    fee = gross * FEE_RATE
    net = gross - fee
    pnl = net - entry_cost
    reserve_add = max(D("0"), pnl * RESERVE_RATE)

    account["cash"] = str(dec(account["cash"]) + net - reserve_add)
    account["reserve"] = str(dec(account["reserve"]) + reserve_add)
    account["realized_pnl"] = str(
        dec(account["realized_pnl"]) + pnl
    )
    account["trades"].append(
        {
            "at": iso(at),
            "symbol": symbol,
            "side": "sell",
            "price": str(px),
            "qty": str(qty),
            "fee": str(fee),
            "pnl": str(pnl),
            "reserved": str(reserve_add),
            "reason": reason,
        }
    )


def projected_net_return_at_take_profit(market: dict) -> Decimal:
    buy_px = fill_price("buy", market)
    entry_cost_per_unit = buy_px * (D("1") + FEE_RATE)
    spread_ratio = market["bid"] / market["last"]
    future_bid = market["last"] * (D("1") + TAKE_PROFIT) * spread_ratio
    exit_px = future_bid * (D("1") - SLIPPAGE_RATE)
    exit_net_per_unit = exit_px * (D("1") - FEE_RATE)
    return (exit_net_per_unit / entry_cost_per_unit) - D("1")


def buy(
    account: dict,
    symbol: str,
    market: dict,
    at: datetime,
) -> None:
    if (
        len(account["positions"]) >= MAX_POSITIONS
        or symbol in account["positions"]
    ):
        return
    if projected_net_return_at_take_profit(market) < MIN_PROJECTED_NET_RETURN:
        return
    cash = dec(account["cash"])
    budget = cash * TRADE_FRACTION
    px = fill_price("buy", market)
    qty = (
        budget / (px * (D("1") + FEE_RATE))
    ).quantize(D("0.00000001"), rounding=ROUND_DOWN)
    if qty <= 0:
        return
    gross = qty * px
    fee = gross * FEE_RATE
    cost = gross + fee
    if cost > cash:
        return
    account["cash"] = str(cash - cost)
    account["positions"][symbol] = {
        "qty": str(qty),
        "entry_price": str(px),
        "cost_basis": str(cost),
        "entry_at": iso(at),
        "entry_bar": market["bars"][-1][0],
    }
    account["trades"].append(
        {
            "at": iso(at),
            "symbol": symbol,
            "side": "buy",
            "price": str(px),
            "qty": str(qty),
            "fee": str(fee),
            "reason": "SIGNAL",
        }
    )


def run_cycle(
    state: dict,
    markets: dict[str, dict],
    *,
    now: datetime,
) -> dict:
    if state.get("ended"):
        return state
    end = parse_utc(state["campaign_end"])
    if now >= end:
        state["ended"] = True
        state["last_cycle"] = iso(now)
        return state

    if state.get("last_cycle"):
        prev = parse_utc(state["last_cycle"])
        delta = (now - prev).total_seconds()
        if delta < 60:
            raise PaperCycleError("CYCLE_TOO_FAST")
        if delta > 20 * 60:
            state["errors"].append(
                {
                    "at": iso(now),
                    "error": "CYCLE_GAP",
                    "seconds": int(delta),
                }
            )
            state["errors"] = state["errors"][-100:]

    prices = {s: m["last"] for s, m in markets.items()}
    state["last_prices"] = {
        s: str(p) for s, p in prices.items()
    }

    for strategy, account in state["strategies"].items():
        for symbol in list(account["positions"]):
            if symbol not in markets:
                continue
            market = markets[symbol]
            pos = account["positions"][symbol]
            entry = dec(pos["entry_price"])
            current = market["last"]
            held_bars = max(
                0,
                int(
                    (
                        market["bars"][-1][0]
                        - int(pos["entry_bar"])
                    )
                    / (5 * 60 * 1000)
                ),
            )
            sig = signal(strategy, market)
            reason = None
            if current <= entry * (D("1") - STOP_LOSS):
                reason = "STOP_LOSS"
            elif current >= entry * (D("1") + TAKE_PROFIT):
                reason = "TAKE_PROFIT"
            elif held_bars >= MAX_HOLD_BARS:
                reason = "MAX_HOLD"
            elif sig == "sell":
                reason = "EXIT_SIGNAL"
            if reason:
                sell(account, symbol, market, now, reason)

        candidates = []
        for symbol, market in markets.items():
            if symbol in account["positions"]:
                continue
            if signal(strategy, market) == "buy":
                closes = [b[4] for b in market["bars"]]
                score = abs(
                    (closes[-1] / closes[-4]) - D("1")
                )
                candidates.append((score, symbol))

        for _, symbol in sorted(candidates, reverse=True):
            if len(account["positions"]) >= MAX_POSITIONS:
                break
            buy(account, symbol, markets[symbol], now)

        account["equity"] = str(equity(account, prices))

    state["cycles"] = int(state.get("cycles", 0)) + 1
    state["last_cycle"] = iso(now)
    return state


def summary(state: dict) -> dict:
    out = {
        "paper_only": True,
        "campaign_start": state["campaign_start"],
        "campaign_end": state["campaign_end"],
        "ended": state["ended"],
        "cycles": state["cycles"],
        "strategies": {},
    }
    for s, a in state["strategies"].items():
        eq = dec(a.get("equity", a["cash"]))
        sells = [
            t for t in a["trades"] if t["side"] == "sell"
        ]
        wins = sum(
            1 for t in sells if dec(t["pnl"]) > 0
        )
        out["strategies"][s] = {
            "equity_yen": str(eq.quantize(D("0.01"))),
            "return_pct": str(
                ((eq / START_YEN) - 1) * 100
            ),
            "reserve_yen": a["reserve"],
            "closed_trades": len(sells),
            "wins": wins,
            "win_rate_pct": str(
                (D(wins) / D(len(sells)) * 100)
                if sells
                else D("0")
            ),
            "open_positions": sorted(a["positions"]),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--window", required=True)
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    try:
        window = resolve_window(
            Path(args.window),
            now=now,
            hours=int(CFG["duration_hours"]),
        )
    except CampaignWindowError as exc:
        raise PaperCycleError(str(exc)) from exc
    start = parse_utc(window["started_at"])
    end = parse_utc(window["ends_at"])
    if end - start != timedelta(hours=int(CFG["duration_hours"])):
        raise PaperCycleError("CAMPAIGN_LENGTH_MISMATCH")

    path = Path(args.state)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = load_or_init(
        path,
        now=now,
        campaign_start=start,
        campaign_end=end,
    )

    if now < start:
        print(
            json.dumps(
                {
                    "paper_only": True,
                    "status": "WAITING_FOR_CAMPAIGN_START",
                    "start": iso(start),
                },
                ensure_ascii=False,
            )
        )
        return 0

    if state.get("ended") or now >= end:
        state["ended"] = True
        path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(summary(state), ensure_ascii=False))
        return 0

    markets = {}
    errors = {}
    for symbol in ASSETS:
        try:
            markets[symbol] = fetch_market(symbol, now=now)
        except PaperCycleError as exc:
            errors[symbol] = str(exc)

    if not markets:
        raise PaperCycleError("NO_FRESH_MARKETS")

    if errors:
        state["errors"].append(
            {"at": iso(now), "market_errors": errors}
        )
        state["errors"] = state["errors"][-100:]

    state = run_cycle(state, markets, now=now)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary(state), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PaperCycleError as exc:
        print(
            json.dumps(
                {
                    "paper_only": True,
                    "status": "BLOCKED",
                    "reason": str(exc),
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(2)
