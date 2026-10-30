"""Opening-range breakout (ORB), long only. Pure functions, no network.

Rules (same idea as day-trader-skill's trader-scanner/entry/exit):
- Opening range = high/low of the first N minutes (default 9:30-9:45 New York).
- Signal = the FIRST completed 5-minute bar after the range that closes above the range high.
  It is only actionable while it is the most recent completed bar (no stale entries).
- Stop = range midpoint. Target = entry + target_r * risk. Flat before the close.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import math

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OPEN = time(9, 30)


@dataclass
class Bar:
    start: datetime  # aware, New York time
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


def parse_bars(raw):
    """Alpaca bar dicts -> list[Bar] sorted, New York time."""
    out = []
    for b in raw:
        ts = datetime.fromisoformat(b["t"].replace("Z", "+00:00")).astimezone(NY)
        out.append(Bar(ts, float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"]), float(b.get("v", 0))))
    out.sort(key=lambda x: x.start)
    return out


def opening_range(bars, day, cfg):
    start = datetime.combine(day, OPEN, NY)
    end = start + timedelta(minutes=cfg["opening_range_minutes"])
    rng = [b for b in bars if start <= b.start < end]
    need = cfg["opening_range_minutes"] // cfg["bar_minutes"]
    if len(rng) < need:
        return None
    return max(b.h for b in rng), min(b.l for b in rng)


def find_signal(bars, day, now, cfg):
    """Return dict with the breakout, or None. `now` is aware New York time."""
    orng = opening_range(bars, day, cfg)
    if not orng:
        return None
    hi, lo = orng
    bm = timedelta(minutes=cfg["bar_minutes"])
    or_end = datetime.combine(day, OPEN, NY) + timedelta(minutes=cfg["opening_range_minutes"])
    done = [b for b in bars if b.start >= or_end and b.start + bm <= now]
    if not done:
        return None
    first = next((b for b in done if b.c > hi), None)
    if first is None or first is not done[-1]:
        return None  # no breakout yet, or it happened earlier and is stale
    mid = (hi + lo) / 2
    width_pct = (hi - lo) / mid * 100
    if first.c < cfg["min_price"]:
        return None
    if not (cfg["min_range_pct"] <= width_pct <= cfg["max_range_pct"]):
        return None
    return {
        "or_high": hi, "or_low": lo, "or_mid": mid,
        "bar_start": first.start.isoformat(), "close": first.c,
        "strength_pct": (first.c - hi) / hi * 100, "range_pct": width_pct,
    }


def plan_trade(sig, equity, buying_power, cfg):
    entry = sig["close"]
    stop = round(sig["or_mid"], 2)
    risk = entry - stop
    if risk <= 0.01:
        return None
    target = round(entry + cfg["target_r"] * risk, 2)
    qty = min(
        equity * cfg["risk_per_trade_pct"] / 100 / risk,
        equity * cfg["max_position_pct"] / 100 / entry,
        buying_power * 0.95 / entry,
    )
    qty = math.floor(qty)
    if qty < 1:
        return None
    return {"qty": qty, "entry_ref": entry, "stop": stop, "target": target,
            "risk_per_share": round(risk, 4), "max_loss": round(qty * risk, 2)}
