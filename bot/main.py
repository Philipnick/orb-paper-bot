"""ORB paper-trading bot for Alpaca.

  python -m bot.main check     # verify keys, paper account, data feed
  python -m bot.main morning   # wait for 9:45 NY, scan for breakouts, place bracket orders until the deadline
  python -m bot.main flatten   # wait until 10 min before the close, close everything, write the journal
  python -m bot.main report    # rebuild journal/REPORT.md
"""
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from .alpaca import Alpaca, AlpacaError
from .strategy import NY, find_signal, parse_bars, plan_trade
from . import report

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = ROOT / "journal"


def log(msg):
    print(f"[{now_ny():%Y-%m-%d %H:%M:%S} NY] {msg}", flush=True)


def load_cfg():
    return json.loads((ROOT / "config.json").read_text())


def now_ny():
    return datetime.now(NY)


def sleep_until(dt, why=""):
    secs = (dt - now_ny()).total_seconds()
    if secs > 0:
        log(f"Attendo fino alle {dt:%H:%M:%S} NY {why}({secs/60:.0f} min)")
        time.sleep(secs)


def today_session(api):
    """(open_dt, close_dt) for today in NY, or None if the market is closed today."""
    day = now_ny().date().isoformat()
    cal = api.calendar(day)
    if not cal or cal[0]["date"] != day:
        return None
    op = datetime.fromisoformat(f"{day} {cal[0]['open']}").replace(tzinfo=NY)
    cl = datetime.fromisoformat(f"{day} {cal[0]['close']}").replace(tzinfo=NY)
    return op, cl


def append_csv(path, fields, rows, key=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if path.exists():
        with path.open() as f:
            existing = list(csv.DictReader(f))
    if key:
        new_keys = {r[key] for r in rows}
        existing = [r for r in existing if r[key] not in new_keys]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in existing + rows:
            w.writerow({k: r.get(k, "") for k in fields})


# ---------------------------------------------------------------- check
def cmd_check(api, cfg):
    acct = api.account()
    num = acct.get("account_number", "")
    log(f"Account {num} status={acct.get('status')} equity={acct.get('equity')} buying_power={acct.get('buying_power')}")
    if not num.startswith("PA"):
        raise AlpacaError("Questo non sembra un conto PAPER (il numero dovrebbe iniziare con PA). Mi fermo.")
    clk = api.clock()
    log(f"Mercato aperto ora: {clk['is_open']} | prossima apertura {clk['next_open']} | prossima chiusura {clk['next_close']}")
    start = (now_ny() - timedelta(days=5)).isoformat()
    bars = api.bars(["AAPL", "SPY"], "1Day", start)
    for s, b in bars.items():
        log(f"Dati OK: {s} ultima chiusura giornaliera {b[-1]['c']} ({b[-1]['t'][:10]})")
    log("Tutto a posto: chiavi, conto paper e dati funzionano.")


# ---------------------------------------------------------------- morning
def todays_entries(api, open_dt):
    orders = api.orders(status="all", after=(open_dt - timedelta(hours=6)).isoformat(),
                        limit=500, direction="asc", nested="true")
    return [o for o in orders if o.get("side") == "buy" and (o.get("client_order_id") or "").startswith("orb-")
            and o.get("status") not in ("rejected", "canceled", "expired")]


def cmd_morning(api, cfg):
    sess = today_session(api)
    if not sess:
        log("Oggi la borsa USA è chiusa. Niente da fare.")
        return
    open_dt, close_dt = sess
    day = open_dt.date()
    hh, mm = map(int, cfg["entry_deadline"].split(":"))
    deadline = min(open_dt.replace(hour=hh, minute=mm), close_dt - timedelta(minutes=60))
    bm = timedelta(minutes=cfg["bar_minutes"])
    or_end = open_dt + timedelta(minutes=cfg["opening_range_minutes"])

    if now_ny() >= deadline:
        log("Finestra di ingresso già chiusa per oggi (esecuzione partita in ritardo).")
        return

    # Positions left over from a missed flatten on a previous day: close them first.
    if api.positions() and not todays_entries(api, open_dt):
        log("Trovate posizioni rimaste aperte da un giorno precedente: le chiudo all'apertura.")
        api.close_all_positions()

    rows = []
    next_check = or_end + bm  # the first bar after the range completes here
    while True:
        n = now_ny()
        if n < next_check:
            sleep_until(next_check + timedelta(seconds=20), "(attendo la chiusura della candela) ")
        else:  # started late: evaluate the most recently completed bar right away
            k = int((n - open_dt).total_seconds() // bm.total_seconds())
            next_check = open_dt + bm * k
        if next_check > deadline:
            break
        now = now_ny()

        acct = api.account()
        equity, last_eq = float(acct["equity"]), float(acct["last_equity"])
        if equity < last_eq * (1 - cfg["daily_loss_limit_pct"] / 100):
            log(f"Limite di perdita giornaliera raggiunto ({equity:.2f} vs {last_eq:.2f}). Stop ingressi.")
            break
        entries = todays_entries(api, open_dt)
        done_syms = {o["symbol"] for o in entries}
        slots = cfg["max_trades_per_day"] - len(entries)
        if slots <= 0:
            log("Numero massimo di operazioni per oggi raggiunto.")
            break

        syms = [s for s in cfg["universe"] if s not in done_syms]
        raw = api.bars(syms, f"{cfg['bar_minutes']}Min", open_dt.isoformat())
        signals = []
        for s in syms:
            sig = find_signal(parse_bars(raw.get(s, [])), day, now, cfg)
            if sig:
                signals.append((s, sig))
        signals.sort(key=lambda x: -x[1]["strength_pct"])
        log(f"Controllo {now:%H:%M}: {len(signals)} breakout su {len(syms)} titoli, slot liberi {slots}")

        for s, sig in signals[:slots]:
            plan = plan_trade(sig, equity, float(acct["buying_power"]), cfg)
            if not plan:
                log(f"{s}: breakout ma posizione troppo piccola o rischio nullo, salto.")
                continue
            px = api.latest_price(s)
            if not (plan["stop"] + 0.01 < px < plan["target"] - 0.01):
                log(f"{s}: prezzo attuale {px} fuori da stop/obiettivo, salto.")
                continue
            body = {"symbol": s, "qty": str(plan["qty"]), "side": "buy", "type": "market",
                    "time_in_force": "day", "order_class": "bracket",
                    "take_profit": {"limit_price": f"{plan['target']:.2f}"},
                    "stop_loss": {"stop_price": f"{plan['stop']:.2f}"},
                    "client_order_id": f"orb-{s}-{day.isoformat()}"}
            try:
                o = api.submit_order(body)
                status = o.get("status")
                log(f"ORDINE {s}: compro {plan['qty']} @~{px} stop {plan['stop']} obiettivo {plan['target']} "
                    f"(perdita max ~{plan['max_loss']} $) -> {status}")
            except AlpacaError as e:
                status = f"errore: {e}"
                log(f"{s}: ordine rifiutato: {e}")
            rows.append({"date": day.isoformat(), "time": f"{now:%H:%M}", "symbol": s, "qty": plan["qty"],
                         "price_ref": px, "stop": plan["stop"], "target": plan["target"],
                         "or_high": round(sig["or_high"], 2), "or_low": round(sig["or_low"], 2),
                         "max_loss": plan["max_loss"], "status": status})
        next_check = next_check + bm

    if rows:
        append_csv(JOURNAL / "orders.csv", list(rows[0].keys()), rows)
    log(f"Fine finestra di ingresso. Ordini inviati oggi: {len(rows)}")


# ---------------------------------------------------------------- flatten
def cmd_flatten(api, cfg):
    sess = today_session(api)
    if not sess:
        log("Oggi la borsa USA è chiusa. Niente da fare.")
        return
    open_dt, close_dt = sess
    day = open_dt.date().isoformat()
    daily = JOURNAL / "daily.csv"
    if daily.exists() and f"\n{day}," in daily.read_text():
        log("Giornata già chiusa e registrata da un'esecuzione precedente.")
        return
    sleep_until(close_dt - timedelta(minutes=cfg["flatten_minutes_before_close"]), "per chiudere tutto ")

    for attempt in range(3):
        pos = api.positions()
        if not pos:
            break
        log(f"Chiudo {len(pos)} posizioni: {', '.join(p['symbol'] for p in pos)}")
        api.cancel_all_orders()
        api.close_all_positions()
        time.sleep(60)
    else:
        log("ATTENZIONE: alcune posizioni risultano ancora aperte.")

    acct = api.account()
    try:
        spy = api.latest_price("SPY")
    except AlpacaError:
        spy = ""
    fills = api.fills(day)
    append_csv(JOURNAL / "fills.csv",
               ["id", "date", "time", "symbol", "side", "qty", "price"],
               [{"id": f["id"], "date": day, "time": f["transaction_time"], "symbol": f["symbol"],
                 "side": f["side"], "qty": f["qty"], "price": f["price"]} for f in fills], key="id")
    eq, last = float(acct["equity"]), float(acct["last_equity"])
    append_csv(JOURNAL / "daily.csv", ["date", "equity", "prev_equity", "pnl", "fills", "spy"],
               [{"date": day, "equity": f"{eq:.2f}", "prev_equity": f"{last:.2f}",
                 "pnl": f"{eq - last:.2f}", "fills": len(fills), "spy": spy}], key="date")
    log(f"Giornata chiusa: equity {eq:.2f} (P&L {eq - last:+.2f} $), {len(fills)} esecuzioni")
    report.write(JOURNAL)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "report":
        report.write(JOURNAL)
        return
    cfg = load_cfg()
    api = Alpaca()
    {"check": cmd_check, "morning": cmd_morning, "flatten": cmd_flatten}[cmd](api, cfg)


if __name__ == "__main__":
    try:
        main()
    except AlpacaError as e:
        log(f"ERRORE: {e}")
        sys.exit(1)
