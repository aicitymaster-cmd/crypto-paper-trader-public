"""PAPER-only cross-market 7-day backtest utilities.

Consumes pre-downloaded OHLC CSV data. It never submits orders, authenticates,
or performs network writes. The purpose is apples-to-apples research from a
JPY 10,000 starting balance across FX, metals, and indices.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class Bar:
    ts: datetime
    close: float


@dataclass(frozen=True)
class Result:
    final_yen: float
    return_pct: float
    max_dd_pct: float
    trades: int
    wins: int
    ruined: bool
    target_hit: bool


def load_csv(path: str | Path) -> list[Bar]:
    rows: list[Bar] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        names = {n.lower(): n for n in (reader.fieldnames or [])}
        time_key = names.get("date") or names.get("timestamp") or names.get("time")
        close_key = names.get("close")
        if not time_key or not close_key:
            raise ValueError("CSV requires Date/Timestamp and Close columns")
        for row in reader:
            raw = row[time_key].strip().replace("Z", "+00:00")
            ts = datetime.fromisoformat(raw)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            rows.append(Bar(ts.astimezone(timezone.utc), float(row[close_key])))
    rows.sort(key=lambda x: x.ts)
    return rows


def _sma(values: list[float], n: int) -> float:
    return sum(values[-n:]) / n


def run_window(
    bars: list[Bar],
    start_yen: float = 10_000.0,
    leverage: float = 1.0,
    spread_bps: float = 2.0,
    fee_bps: float = 0.0,
    fast: int = 12,
    slow: int = 36,
    stop_pct: float = 0.01,
    take_pct: float = 0.03,
    target_yen: float = 200_000.0,
    ruin_yen: float = 1_000.0,
) -> Result:
    """Simple long/short trend PAPER strategy with explicit transaction costs.

    Position is +1/-1/0. Exposure is equity * leverage. Each completed trade
    pays spread once plus entry/exit fees. This is intentionally generic: it
    compares market opportunity without claiming broker-specific execution.
    """
    if leverage <= 0 or slow <= fast or len(bars) <= slow:
        raise ValueError("invalid parameters or insufficient bars")
    equity = float(start_yen)
    peak = equity
    max_dd = 0.0
    pos = 0
    entry = 0.0
    entry_equity = equity
    trades = wins = 0
    target_hit = False
    cost_rate = (spread_bps + 2.0 * fee_bps) / 10_000.0

    for i in range(slow, len(bars)):
        closes = [b.close for b in bars[: i + 1]]
        price = closes[-1]
        if price <= 0:
            continue
        fast_ma, slow_ma = _sma(closes, fast), _sma(closes, slow)
        signal = 1 if fast_ma > slow_ma else -1

        if pos:
            raw = pos * (price / entry - 1.0)
            move = raw * leverage
            should_exit = raw <= -stop_pct or raw >= take_pct or signal != pos
            if should_exit:
                pnl = entry_equity * (move - leverage * cost_rate)
                equity = max(0.0, entry_equity + pnl)
                trades += 1
                wins += pnl > 0
                pos = 0
                peak = max(peak, equity)
                if peak:
                    max_dd = max(max_dd, (peak - equity) / peak)
                target_hit |= equity >= target_yen
                if equity <= ruin_yen:
                    break

        if not pos and equity > ruin_yen:
            pos = signal
            entry = price
            entry_equity = equity

    if pos and equity > ruin_yen:
        price = bars[-1].close
        raw = pos * (price / entry - 1.0)
        pnl = entry_equity * (raw * leverage - leverage * cost_rate)
        equity = max(0.0, entry_equity + pnl)
        trades += 1
        wins += pnl > 0
        peak = max(peak, equity)
        if peak:
            max_dd = max(max_dd, (peak - equity) / peak)
        target_hit |= equity >= target_yen

    return Result(
        final_yen=round(equity, 2),
        return_pct=round((equity / start_yen - 1.0) * 100.0, 4),
        max_dd_pct=round(max_dd * 100.0, 4),
        trades=trades,
        wins=wins,
        ruined=equity <= ruin_yen,
        target_hit=target_hit,
    )


def rolling_7d(bars: list[Bar], **kwargs) -> list[Result]:
    if not bars:
        return []
    out: list[Result] = []
    cursor = bars[0].ts
    end = bars[-1].ts
    while cursor + timedelta(days=7) <= end:
        stop = cursor + timedelta(days=7)
        chunk = [b for b in bars if cursor <= b.ts < stop]
        if len(chunk) > kwargs.get("slow", 36):
            out.append(run_window(chunk, **kwargs))
        cursor = stop
    return out


def summarize(results: list[Result]) -> dict[str, float | int]:
    if not results:
        return {"windows": 0}
    finals = sorted(r.final_yen for r in results)
    n = len(finals)
    median = finals[n // 2] if n % 2 else (finals[n // 2 - 1] + finals[n // 2]) / 2
    return {
        "windows": n,
        "target_hits": sum(r.target_hit for r in results),
        "ruins": sum(r.ruined for r in results),
        "median_final_yen": round(median, 2),
        "best_final_yen": round(max(finals), 2),
        "worst_final_yen": round(min(finals), 2),
        "avg_max_dd_pct": round(sum(r.max_dd_pct for r in results) / n, 4),
    }
