"""Time Machine (idea from day-trader-skill's trader-timemachine).

Before entering, replay the rest of the session N times: each 5-minute candle is drawn at
random from the stock's own candles at the same time of day over the previous sessions.
Count which comes first: stop, target, or neither by the flat-by time.
Also re-run the same ORB rule on those real past sessions.
"""
import random
from collections import defaultdict
from datetime import datetime, timedelta

from .strategy import NY, OPEN


def _slot(dt, bar_min):
    return ((dt.hour * 60 + dt.minute) - (OPEN.hour * 60 + OPEN.minute)) // bar_min


def group_sessions(bars):
    """list[Bar] -> {date: [Bar,...]} (regular session only)."""
    days = defaultdict(list)
    for b in bars:
        t = b.start.timetz()
        if t.replace(tzinfo=None) >= OPEN and b.start.hour < 16:
            days[b.start.date()].append(b)
    return dict(sorted(days.items()))


def first_hit(bars_after, stop, target):
    """'target' | 'stop' | 'flat' and the exit price. Same-bar touch of both counts as stop."""
    for b in bars_after:
        if b.l <= stop:
            return "stop", stop
        if b.h >= target:
            return "target", target
    return "flat", (bars_after[-1].c if bars_after else None)


def simulate(history, entry_time, entry, stop, target, flat_time, cfg, n=10000, seed=None):
    bm = cfg["bar_minutes"]
    pool = defaultdict(list)
    for day_bars in history.values():
        for b in day_bars:
            if b.o > 0:
                pool[_slot(b.start, bm)].append((b.h / b.o - 1, b.l / b.o - 1, b.c / b.o - 1))
    first = _slot(entry_time, bm)        # slot of the first bar AFTER entry
    last = _slot(flat_time, bm)          # exclusive
    slots = [pool[s] for s in range(first, last) if pool[s]]
    if not slots:
        return None
    rng = random.Random(seed)
    res = {"target": 0, "stop": 0, "flat": 0}
    for _ in range(n):
        p = entry
        out = "flat"
        for choices in slots:
            hr, lr, cr = rng.choice(choices)
            if p * (1 + lr) <= stop:
                out = "stop"
                break
            if p * (1 + hr) >= target:
                out = "target"
                break
            p *= 1 + cr
        res[out] += 1
    return {k: v / n for k, v in res.items()}


def history_check(history, cfg, deadline_hm, flat_hm):
    """Apply the ORB rule to each past session. Returns counts."""
    bm = timedelta(minutes=cfg["bar_minutes"])
    out = {"fired": 0, "target": 0, "stop": 0, "flat": 0}
    for day, bars in history.items():
        op = datetime.combine(day, OPEN, NY)
        or_end = op + timedelta(minutes=cfg["opening_range_minutes"])
        rng = [b for b in bars if b.start < or_end]
        if len(rng) < cfg["opening_range_minutes"] // cfg["bar_minutes"]:
            continue
        hi, lo = max(b.h for b in rng), min(b.l for b in rng)
        deadline = op.replace(hour=deadline_hm[0], minute=deadline_hm[1])
        flat = op.replace(hour=flat_hm[0], minute=flat_hm[1])
        trig = next((b for b in bars if b.start >= or_end and b.start + bm <= deadline and b.c > hi), None)
        if not trig:
            continue
        stop = round((hi + lo) / 2, 2)
        risk = trig.c - stop
        if risk <= 0.01:
            continue
        target = trig.c + cfg["target_r"] * risk
        after = [b for b in bars if b.start >= trig.start + bm and b.start + bm <= flat]
        out["fired"] += 1
        out[first_hit(after, stop, target)[0]] += 1
    return out


def evaluate(api_bars_raw, today, entry_time, entry, stop, target, cfg, flat_time, seed=None):
    """Full Time Machine verdict for one signal. api_bars_raw: parsed Bars of ~60 past sessions."""
    sessions = group_sessions(api_bars_raw)
    history = {d: b for d, b in sessions.items() if d < today}
    history = dict(list(history.items())[-cfg.get("tm_sessions", 59):])
    sim = simulate(history, entry_time, entry, stop, target, flat_time, cfg,
                   n=cfg.get("tm_simulations", 10000), seed=seed)
    hh, mm = map(int, cfg["entry_deadline"].split(":"))
    hist = history_check(history, cfg, (hh, mm), (flat_time.hour, flat_time.minute))
    if sim is None:
        return None
    edge = sim["target"] - sim["stop"]
    passed = edge >= cfg.get("tm_min_edge", 0.10)
    return {"p_target": round(sim["target"], 3), "p_stop": round(sim["stop"], 3), "p_flat": round(sim["flat"], 3),
            "edge": round(edge, 3), "hist_fired": hist["fired"], "hist_target": hist["target"],
            "hist_stop": hist["stop"], "sessions": len(history), "pass": passed}
