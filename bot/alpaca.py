"""Minimal Alpaca REST client (standard library only). PAPER ONLY by design."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

TRADING = "https://paper-api.alpaca.markets/v2"  # hard-coded: this bot never touches a live account
DATA = "https://data.alpaca.markets/v2"


class AlpacaError(Exception):
    pass


class Alpaca:
    def __init__(self, key=None, secret=None):
        self.key = key or os.environ.get("ALPACA_API_KEY", "").strip()
        self.secret = secret or os.environ.get("ALPACA_SECRET_KEY", "").strip()
        if not self.key or not self.secret:
            raise AlpacaError("Mancano ALPACA_API_KEY / ALPACA_SECRET_KEY (vanno nei Secrets di GitHub).")

    def _req(self, method, url, params=None, body=None, retries=3):
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        headers = {"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret,
                   "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(retries):
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    txt = r.read().decode()
                    return json.loads(txt) if txt else None
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")
                if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise AlpacaError(f"{method} {url} -> {e.code}: {msg}") from None
            except urllib.error.URLError as e:
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise AlpacaError(f"{method} {url} -> {e}") from None

    # trading
    def account(self):
        return self._req("GET", f"{TRADING}/account")

    def clock(self):
        return self._req("GET", f"{TRADING}/clock")

    def calendar(self, day):
        return self._req("GET", f"{TRADING}/calendar", {"start": day, "end": day})

    def positions(self):
        return self._req("GET", f"{TRADING}/positions")

    def orders(self, **params):
        return self._req("GET", f"{TRADING}/orders", params)

    def submit_order(self, body):
        return self._req("POST", f"{TRADING}/orders", body=body)

    def cancel_all_orders(self):
        return self._req("DELETE", f"{TRADING}/orders")

    def close_all_positions(self):
        return self._req("DELETE", f"{TRADING}/positions", {"cancel_orders": "true"})

    def fills(self, day):
        return self._req("GET", f"{TRADING}/account/activities/FILL", {"date": day}) or []

    # market data (free plan -> IEX feed)
    def bars(self, symbols, timeframe, start, end=None):
        out = {}
        params = {"symbols": ",".join(symbols), "timeframe": timeframe, "start": start,
                  "feed": "iex", "limit": 10000, "adjustment": "raw"}
        if end:
            params["end"] = end
        while True:
            res = self._req("GET", f"{DATA}/stocks/bars", params)
            for sym, lst in (res.get("bars") or {}).items():
                out.setdefault(sym, []).extend(lst)
            tok = res.get("next_page_token")
            if not tok:
                return out
            params["page_token"] = tok

    def latest_price(self, symbol):
        res = self._req("GET", f"{DATA}/stocks/{symbol}/trades/latest", {"feed": "iex"})
        return float(res["trade"]["p"])
