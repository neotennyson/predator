from __future__ import annotations

import os
from datetime import date

import requests

BASE = "https://api.dhan.co/v2"

UNDERLYING = {
    "NIFTY": {"scrip": 13, "seg": "IDX_I", "order_segment": "NSE_FNO", "lot": 75},
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I", "order_segment": "NSE_FNO", "lot": 35},
    "FINNIFTY": {"scrip": 27, "seg": "IDX_I", "order_segment": "NSE_FNO", "lot": 65},
    "SENSEX": {"scrip": 51, "seg": "BSE_I", "order_segment": "BSE_FNO", "lot": 20},
}

OPT_KEY = {"call": "ce", "put": "pe"}


class DhanBroker:
    def __init__(self, client_id: str | None = None, access_token: str | None = None, timeout: int = 10):
        from .secrets_store import load

        stored = load()
        self.client_id = client_id or os.environ.get("DHAN_CLIENT_ID") or stored.get("dhan_client_id") or ""
        self.access_token = access_token or os.environ.get("DHAN_ACCESS_TOKEN") or stored.get("dhan_access_token") or ""
        if not self.client_id or not self.access_token:
            raise RuntimeError("no Dhan credentials — paste a fresh token on the dashboard (or set env vars)")
        self.timeout = timeout
        self.session = requests.Session()

    def _headers(self) -> dict:
        return {
            "access-token": self.access_token,
            "client-id": self.client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _req(self, method: str, path: str, json_body: dict | None = None, params: dict | None = None):
        url = f"{BASE}{path}"
        resp = self.session.request(method, url, headers=self._headers(), json=json_body, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    def fund_limit(self) -> dict:
        return self._req("GET", "/fundlimit")

    def expiries(self, underlying: str = "NIFTY") -> list[str]:
        u = UNDERLYING[underlying]
        data = self._req("POST", "/optionchain/expirylist", json_body={"UnderlyingScrip": u["scrip"], "UnderlyingSeg": u["seg"]})
        return data.get("data", [])

    def option_chain(self, underlying: str, expiry: str) -> dict:
        u = UNDERLYING[underlying]
        return self._req("POST", "/optionchain", json_body={"UnderlyingScrip": u["scrip"], "UnderlyingSeg": u["seg"], "Expiry": expiry})

    def atm_option(self, chain: dict, spot: float, side: str, strike_step: float = 50.0) -> tuple[str, float, float]:
        oc = chain["data"]["oc"]
        target = round(spot / strike_step) * strike_step
        best_key = min(oc.keys(), key=lambda k: abs(float(k) - target))
        node = oc[best_key][OPT_KEY[side]]
        return str(node["SecurityId"]), float(best_key), float(node.get("LastPrice") or 0.0)

    def _order_body(self, txn: str, security_id: str, quantity: int, expiry: date, option_type: str, underlying: str) -> dict:
        u = UNDERLYING[underlying]
        return {
            "dhanClientId": self.client_id,
            "transactionType": txn,
            "exchangeSegment": u["order_segment"],
            "productType": "INTRADAY",
            "orderType": "MARKET",
            "validity": "DAY",
            "securityId": security_id,
            "quantity": int(quantity),
            "price": 0,
            "drvExpiryDate": expiry.isoformat() + "T00:00:00",
            "drvOptionType": option_type.upper(),
        }

    def buy_option(self, security_id: str, quantity: int, expiry: date, option_type: str, underlying: str = "NIFTY") -> dict:
        return self._req("POST", "/orders", json_body=self._order_body("BUY", security_id, quantity, expiry, option_type, underlying))

    def exit_option(self, security_id: str, quantity: int, expiry: date, option_type: str, underlying: str = "NIFTY") -> dict:
        return self._req("POST", "/orders", json_body=self._order_body("SELL", security_id, quantity, expiry, option_type, underlying))

    def ltp(self, security_id: str, segment: str = "NSE_FNO") -> float:
        data = self._req("POST", "/marketfeed/ltp", json_body={segment: [int(security_id)]})
        return float(data["data"][segment][str(security_id)]["last_price"])

    def positions(self) -> dict:
        return self._req("GET", "/positions")


def broker_from_env() -> DhanBroker:
    return DhanBroker()
