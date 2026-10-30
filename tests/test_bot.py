import json
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from bot.strategy import NY, find_signal, parse_bars, plan_trade
from bot.report import build, round_trips

CFG = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text())
DAY = date(2026, 10, 19)


def mk(prices):
    """prices: list of (o,h,l,c) for consecutive 5-min bars from 9:30 NY."""
    out = []
    t0 = datetime(2026, 10, 19, 9, 30, tzinfo=NY)
    for i, (o, h, l, c) in enumerate(prices):
        t = (t0 + timedelta(minutes=5 * i)).astimezone(tz=None)
        out.append({"t": (t0 + timedelta(minutes=5 * i)).isoformat(), "o": o, "h": h, "l": l, "c": c, "v": 1000})
    return parse_bars(out)


RANGE = [(100, 101, 99.5, 100.5), (100.5, 100.8, 99.8, 100.2), (100.2, 100.9, 99.9, 100.6)]  # hi 101, lo 99.5


def at(h, m):
    return datetime(2026, 10, 19, h, m, 5, tzinfo=NY)


class Strategy(unittest.TestCase):
    def test_breakout_fresh(self):
        bars = mk(RANGE + [(100.6, 101.4, 100.5, 101.3)])  # 9:45 bar closes above 101
        sig = find_signal(bars, DAY, at(9, 50), CFG)
        self.assertIsNotNone(sig)
        self.assertAlmostEqual(sig["or_mid"], 100.25)

    def test_bar_not_complete(self):
        bars = mk(RANGE + [(100.6, 101.4, 100.5, 101.3)])
        self.assertIsNone(find_signal(bars, DAY, at(9, 48), CFG))

    def test_stale_breakout_ignored(self):
        bars = mk(RANGE + [(100.6, 101.4, 100.5, 101.3), (101.3, 101.6, 101.1, 101.5)])
        self.assertIsNone(find_signal(bars, DAY, at(9, 55), CFG))

    def test_no_breakout(self):
        bars = mk(RANGE + [(100.6, 101.2, 100.5, 100.9)])
        self.assertIsNone(find_signal(bars, DAY, at(9, 50), CFG))

    def test_incomplete_range(self):
        self.assertIsNone(find_signal(mk(RANGE[:2]), DAY, at(9, 50), CFG))

    def test_plan(self):
        bars = mk(RANGE + [(100.6, 101.4, 100.5, 101.3)])
        sig = find_signal(bars, DAY, at(9, 50), CFG)
        p = plan_trade(sig, 100000, 200000, CFG)
        self.assertEqual(p["stop"], 100.25)
        self.assertAlmostEqual(p["target"], 102.35, places=2)
        # risk 0.5% of 100k = 500 / 1.05 = 476, cap 20% = 20000/101.3 = 197
        self.assertEqual(p["qty"], 197)
        self.assertLess(p["max_loss"], 500)


class Report(unittest.TestCase):
    def test_round_trips_and_build(self):
        fills = [
            {"date": "2026-10-19", "symbol": "TSLA", "side": "buy", "qty": "8", "price": "364.18"},
            {"date": "2026-10-19", "symbol": "TSLA", "side": "sell", "qty": "8", "price": "370.04"},
            {"date": "2026-10-19", "symbol": "AMD", "side": "buy", "qty": "10", "price": "100"},
            {"date": "2026-10-19", "symbol": "AMD", "side": "sell", "qty": "10", "price": "99"},
        ]
        trips = round_trips(fills)
        self.assertEqual(len(trips), 2)
        self.assertAlmostEqual(sum(t["pnl"] for t in trips), 8 * 5.86 - 10, places=6)
        daily = [{"date": "2026-10-19", "equity": "100036.88", "prev_equity": "100000", "pnl": "36.88",
                  "fills": "4", "spy": "600"}]
        md = build(fills, daily)
        self.assertIn("percentuale vincenti **50%**", md)


if __name__ == "__main__":
    unittest.main()
