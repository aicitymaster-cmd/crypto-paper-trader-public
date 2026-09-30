"""Optimistic upper-bound KO-style PAPER simulation.

Research only. Uses public OHLC and deliberately assumes zero spread, zero
funding, and zero knockout premium. Any configuration that fails here is not
expected to become viable after real trading costs are added.
"""
from __future__ import annotations

import json
from datetime import timedelta

from cross_market_backtest import Bar
from cross_market_public_run import MARKETS, fetch_chart, parse_chart

DISTANCES = (0.0025, 0.005, 0.01)  # 0.25%, 0.5%, 1.0%
RISK_FRACTIONS = (0.25, 0.5, 1.0)
START_YEN = 10_000.0
TARGET_YEN = 200_000.0
RUIN_YEN = 1_000.0
FAST = 12
SLOW = 36


def sma(values, n):
    return sum(values[-n:]) / n


def run_window(bars: list[Bar], distance: float, risk_fraction: float) -> dict:
    equity = START_YEN
    peak = equity
    max_dd = 0.0
    pos = 0
    entry = 0.0
    entry_equity = equity
    risk_budget = 0.0
    trades = 0
    wins = 0
    target_hit = False

    for i in range(SLOW, len(bars)):
        closes = [b.close for b in bars[: i + 1]]
        bar = bars[i]
        signal = 1 if sma(closes, FAST) > sma(closes, SLOW) else -1

        if pos:
            _, high, low, close = bar.ohlc()
            adverse = (low / entry - 1.0) if pos == 1 else (entry / high - 1.0)
            favorable = (high / entry - 1.0) if pos == 1 else (entry / low - 1.0)
            close_move = pos * (close / entry - 1.0)

            adverse_pnl = max(-risk_budget, risk_budget * adverse / distance)
            adverse_equity = max(0.0, entry_equity + adverse_pnl)
            max_dd = max(max_dd, (peak - adverse_equity) / peak if peak else 0.0)

            favorable_pnl = risk_budget * favorable / distance
            favorable_equity = max(0.0, entry_equity + favorable_pnl)
            peak = max(peak, favorable_equity)
            if favorable_equity >= TARGET_YEN:
                equity = TARGET_YEN
                target_hit = True
                trades += 1
                wins += 1
                pos = 0
                break

            if adverse <= -distance:
                equity = max(0.0, entry_equity - risk_budget)
                trades += 1
                pos = 0
            elif signal != pos:
                pnl = max(-risk_budget, risk_budget * close_move / distance)
                equity = max(0.0, entry_equity + pnl)
                trades += 1
                wins += pnl > 0
                pos = 0

            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)

        if not pos and equity > RUIN_YEN:
            pos = signal
            entry = bar.close
            entry_equity = equity
            risk_budget = equity * risk_fraction

    if pos and equity > RUIN_YEN and not target_hit:
        close_move = pos * (bars[-1].close / entry - 1.0)
        pnl = max(-risk_budget, risk_budget * close_move / distance)
        equity = max(0.0, entry_equity + pnl)
        trades += 1
        wins += pnl > 0
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)

    return {
        "final_yen": round(equity, 2),
        "target_hit": target_hit,
        "ruined": equity <= RUIN_YEN,
        "max_dd_pct": round(max_dd * 100.0, 4),
        "trades": trades,
        "wins": wins,
    }


def daily_windows(bars: list[Bar], distance: float, risk_fraction: float):
    out = []
    cursor = bars[0].ts.replace(hour=0, minute=0, second=0, microsecond=0)
    end = bars[-1].ts
    while cursor + timedelta(days=7) <= end:
        stop = cursor + timedelta(days=7)
        chunk = [b for b in bars if cursor <= b.ts < stop]
        if len(chunk) > SLOW:
            out.append(run_window(chunk, distance, risk_fraction))
        cursor += timedelta(days=1)
    return out


def summarize(rows):
    finals = sorted(r["final_yen"] for r in rows)
    n = len(rows)
    median = finals[n // 2] if n % 2 else (finals[n // 2 - 1] + finals[n // 2]) / 2
    return {
        "windows": n,
        "target_hits": sum(r["target_hit"] for r in rows),
        "target_rate_pct": round(100 * sum(r["target_hit"] for r in rows) / n, 4),
        "ruins": sum(r["ruined"] for r in rows),
        "ruin_rate_pct": round(100 * sum(r["ruined"] for r in rows) / n, 4),
        "below_5000": sum(r["final_yen"] < 5_000.0 for r in rows),
        "below_5000_rate_pct": round(100 * sum(r["final_yen"] < 5_000.0 for r in rows) / n, 4),
        "at_least_5000": sum(r["final_yen"] >= 5_000.0 for r in rows),
        "at_least_5000_rate_pct": round(100 * sum(r["final_yen"] >= 5_000.0 for r in rows) / n, 4),
        "median_final_yen": round(median, 2),
        "best_final_yen": round(max(finals), 2),
        "worst_final_yen": round(min(finals), 2),
        "avg_max_dd_pct": round(sum(r["max_dd_pct"] for r in rows) / n, 4),
    }


def run_all():
    markets = {}
    failures = {}
    for name, symbol in MARKETS.items():
        try:
            bars = parse_chart(fetch_chart(symbol))
            cases = {}
            for d in DISTANCES:
                for rf in RISK_FRACTIONS:
                    rows = daily_windows(bars, d, rf)
                    cases[f"d{d:.4f}_risk{rf:.2f}"] = summarize(rows)
            markets[name] = {
                "symbol": symbol,
                "bars": len(bars),
                "cases": cases,
            }
        except Exception as exc:
            failures[name] = f"{type(exc).__name__}:{exc}"
    return {
        "paper_only": True,
        "model": "KO-style optimistic upper bound",
        "assumptions": {
            "spread": 0,
            "funding": 0,
            "knockout_premium": 0,
            "distances": DISTANCES,
            "risk_fractions": RISK_FRACTIONS,
            "start_yen": START_YEN,
            "target_yen": TARGET_YEN,
        },
        "markets": markets,
        "failures": failures,
    }


if __name__ == "__main__":
    data = run_all()
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))
    if data["failures"]:
        raise SystemExit(2)
