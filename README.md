# ORB paper bot

Bot di day trading **solo su conto demo** (Alpaca paper). Gira gratis su GitHub Actions, senza server.

Strategia: *opening range breakout*, la stessa di `day-trader-skill` (scanner → entry → exit → budget → risk), ma completamente automatica.

1. Range di apertura: massimo e minimo dalle 9:30 alle 9:45 di New York.
2. Ingresso: la prima candela da 5 minuti che chiude sopra il massimo del range (fino alle 11:30).
3. Stop a metà del range, obiettivo pari al rischio (1:1). Lo stop e l'obiettivo stanno sui server di Alpaca (ordine *bracket*).
4. Rischio per operazione: 0,5% del capitale. Massimo 3 operazioni al giorno. Stop agli ingressi se la giornata perde il 2%.
5. Tutto chiuso 10 minuti prima della chiusura.

Si cambia tutto in `config.json`.

## Quando gira (ora di Lisbona/Londra)

| | con ora legale USA | senza (da novembre a marzo) |
|---|---|---|
| Apertura NY | 13:30 | 14:30 |
| Ingressi | 13:45 – 15:30 | 14:45 – 16:30 |
| Chiusura posizioni | 19:50 | 20:50 |

## Setup

1. **Settings → Secrets and variables → Actions → New repository secret**. Crea due secret:
   - `ALPACA_API_KEY` = la *API Key ID* del paper trading
   - `ALPACA_SECRET_KEY` = la *Secret Key* del paper trading
2. **Actions** → se richiesto, abilita i workflow.
3. **Actions → "0 - Verifica collegamento" → Run workflow**. Se diventa verde, è tutto collegato.

Da lì in poi parte da solo ogni giorno di borsa. I risultati sono in [`journal/REPORT.md`](journal/REPORT.md).

## File

- `bot/strategy.py`: la strategia (solo calcoli)
- `bot/alpaca.py`: collegamento ad Alpaca. L'indirizzo del conto **paper** è fisso nel codice
- `bot/main.py`: i comandi `check`, `morning`, `flatten`, `report`
- `journal/`: ordini, esecuzioni, capitale giornaliero, report

## Limiti

- I dati gratuiti di Alpaca vengono dal feed IEX: prezzi reali, ma una piccola parte dei volumi.
- GitHub può far partire i job in ritardo. Per questo ogni job parte con anticipo e ha una riserva. Se un ingresso salta, si perde solo quel giorno.
- È una simulazione. I risultati del conto demo non tengono conto di slippage realistico né delle tasse.

Non è un consiglio finanziario.
