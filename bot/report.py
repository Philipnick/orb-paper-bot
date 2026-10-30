"""Builds journal/REPORT.md from journal/fills.csv and journal/daily.csv."""
import csv
from collections import defaultdict
from datetime import datetime, timezone


def _read(path):
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def round_trips(fills):
    """Group fills by (date, symbol): one day trade each. P&L only when bought qty == sold qty."""
    g = defaultdict(lambda: {"bq": 0.0, "bc": 0.0, "sq": 0.0, "sp": 0.0})
    for f in fills:
        k = (f["date"], f["symbol"])
        q, p = float(f["qty"]), float(f["price"])
        if f["side"] == "buy":
            g[k]["bq"] += q
            g[k]["bc"] += q * p
        else:
            g[k]["sq"] += q
            g[k]["sp"] += q * p
    out = []
    for (d, s), v in sorted(g.items()):
        if v["bq"] and abs(v["bq"] - v["sq"]) < 1e-9:
            out.append({"date": d, "symbol": s, "qty": v["bq"], "entry": v["bc"] / v["bq"],
                        "exit": v["sp"] / v["sq"], "pnl": v["sp"] - v["bc"]})
    return out


def build(fills, daily):
    trips = round_trips(fills)
    wins = [t for t in trips if t["pnl"] > 0]
    losses = [t for t in trips if t["pnl"] <= 0]
    gross_w = sum(t["pnl"] for t in wins)
    gross_l = -sum(t["pnl"] for t in losses)
    L = ["# Report del bot ORB (conto demo Alpaca)", "",
         f"_Aggiornato: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC_", ""]
    if daily:
        start = float(daily[0]["prev_equity"])
        end = float(daily[-1]["equity"])
        ret = (end / start - 1) * 100
        L += ["## Conto", "",
              f"- Giorni di borsa registrati: **{len(daily)}** (dal {daily[0]['date']} al {daily[-1]['date']})",
              f"- Capitale: {start:,.2f} $ → **{end:,.2f} $** (**{ret:+.2f}%**)"]
        spys = [d for d in daily if d.get("spy")]
        if len(spys) >= 2:
            sret = (float(spys[-1]["spy"]) / float(spys[0]["spy"]) - 1) * 100
            L.append(f"- S&P 500 (SPY) nello stesso periodo, dal primo all'ultimo giorno registrato: {sret:+.2f}%")
        L.append("")
    L += ["## Operazioni", ""]
    if not trips:
        L.append("Nessuna operazione completata finora.")
    else:
        n = len(trips)
        L += [f"- Operazioni: **{n}** · vinte {len(wins)} · perse {len(losses)} · "
              f"percentuale vincenti **{len(wins) / n * 100:.0f}%**",
              f"- P&L totale: **{sum(t['pnl'] for t in trips):+,.2f} $**",
              f"- Vincita media: {gross_w / len(wins):+,.2f} $" if wins else "- Vincita media: n/d",
              f"- Perdita media: {-gross_l / len(losses):+,.2f} $" if losses else "- Perdita media: n/d",
              f"- Profit factor: {gross_w / gross_l:.2f}" if gross_l else "- Profit factor: n/d",
              "", "| Data | Titolo | Qtà | Entrata | Uscita | P&L $ |", "|---|---|---:|---:|---:|---:|"]
        for t in reversed(trips[-50:]):
            L.append(f"| {t['date']} | {t['symbol']} | {t['qty']:g} | {t['entry']:.2f} | {t['exit']:.2f} | {t['pnl']:+.2f} |")
    L += ["", "## Giorni", "", "| Data | Capitale $ | P&L $ | Esecuzioni |", "|---|---:|---:|---:|"]
    for d in reversed(daily[-60:]):
        L.append(f"| {d['date']} | {float(d['equity']):,.2f} | {float(d['pnl']):+,.2f} | {d['fills']} |")
    L += ["", "_Simulazione su conto paper. Non è un consiglio finanziario._", ""]
    return "\n".join(L)


def write(journal_dir):
    journal_dir.mkdir(parents=True, exist_ok=True)
    md = build(_read(journal_dir / "fills.csv"), _read(journal_dir / "daily.csv"))
    (journal_dir / "REPORT.md").write_text(md)
