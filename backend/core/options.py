"""
Options engine: fetches ATM SPY contracts from Alpaca, computes Greeks
via Black-Scholes, filters by spread quality, and selects the best
contract for Claude to evaluate.
"""

import os
import math
import numpy as np
from datetime import date, datetime, timezone
from scipy.stats import norm
from scipy.optimize import brentq

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.trading.enums import ContractType
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionSnapshotRequest

RISK_FREE_RATE = 0.043          # ~current Fed funds rate
MAX_SPREAD_PCT = 0.20           # skip contracts where spread > 20% of mid
MIN_OPEN_INTEREST = 50
MIN_VOLUME = 10
STRIKE_RANGE = 8                # fetch strikes ± $8 from ATM
CONTRACTS_FOR_CLAUDE = 3        # how many candidate contracts to show Claude


# ── Black-Scholes ──────────────────────────────────────────────────────────────

def _bs_price(S, K, T, r, sigma, option_type="call"):
    """Theoretical Black-Scholes price."""
    if T <= 0 or sigma <= 0:
        return max(0, S - K) if option_type == "call" else max(0, K - S)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def _implied_volatility(market_price, S, K, T, r, option_type="call"):
    """Back-solve IV from market mid-price using Brent's method."""
    if T <= 0 or market_price <= 0:
        return None
    intrinsic = max(0, S - K) if option_type == "call" else max(0, K - S)
    if market_price <= intrinsic:
        return None
    try:
        iv = brentq(
            lambda sigma: _bs_price(S, K, T, r, sigma, option_type) - market_price,
            1e-6, 10.0, xtol=1e-6, maxiter=100
        )
        return round(iv, 4)
    except Exception:
        return None


def _greeks(S, K, T, r, sigma, option_type="call"):
    """Compute delta, gamma, theta, vega from BS formula."""
    if T <= 0 or sigma <= 0:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    pdf_d1 = norm.pdf(d1)

    delta = norm.cdf(d1) if option_type == "call" else norm.cdf(d1) - 1
    gamma = pdf_d1 / (S * sigma * math.sqrt(T))
    vega  = S * pdf_d1 * math.sqrt(T) / 100          # per 1% IV move
    theta = (
        -(S * pdf_d1 * sigma) / (2 * math.sqrt(T))
        - r * K * math.exp(-r * T) * (norm.cdf(d2) if option_type == "call" else norm.cdf(-d2))
    ) / 365                                            # per calendar day

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 4),
        "theta": round(theta, 4),
        "vega":  round(vega, 4),
    }


# ── Alpaca data fetch ──────────────────────────────────────────────────────────

def _get_clients():
    api_key = os.getenv("ALPACA_API_KEY")
    secret  = os.getenv("ALPACA_SECRET_KEY")
    trading = TradingClient(api_key, secret, paper=True)
    data    = OptionHistoricalDataClient(api_key, secret)
    return trading, data


def _time_to_expiry(expiry: date) -> float:
    """Fraction of a year remaining until expiry (using trading hours)."""
    now = datetime.now(timezone.utc)
    exp = datetime(expiry.year, expiry.month, expiry.day, 21, 0, 0, tzinfo=timezone.utc)
    seconds = max(0, (exp - now).total_seconds())
    return seconds / (365.25 * 24 * 3600)


def get_option_candidates(spy_price: float, signal: str, expiry: date = None) -> list[dict]:
    """
    Fetch ATM SPY option contracts, compute Greeks + spread quality,
    return top CONTRACTS_FOR_CLAUDE candidates for Claude to evaluate.

    signal: 'buy' → calls, 'sell' → puts
    """
    if expiry is None:
        expiry = date.today()

    option_type   = "call" if signal == "buy" else "put"
    contract_type = ContractType.CALL if signal == "buy" else ContractType.PUT

    trading, data_client = _get_clients()

    # Fetch contracts near ATM
    req = GetOptionContractsRequest(
        underlying_symbols=["SPY"],
        expiration_date=expiry,
        contract_type=contract_type,
        strike_price_gte=str(round(spy_price - STRIKE_RANGE)),
        strike_price_lte=str(round(spy_price + STRIKE_RANGE)),
        limit=30,
    )
    contracts = trading.get_option_contracts(req)
    if not contracts.option_contracts:
        return []

    symbols    = [c.symbol for c in contracts.option_contracts]
    strike_map = {c.symbol: float(c.strike_price) for c in contracts.option_contracts}

    # Fetch latest quotes
    snaps = data_client.get_option_snapshot(OptionSnapshotRequest(symbol_or_symbols=symbols))

    T = _time_to_expiry(expiry)
    candidates = []

    for sym, snap in snaps.items():
        q = snap.latest_quote
        if not q or q.bid_price is None or q.ask_price is None:
            continue
        if q.bid_price <= 0 or q.ask_price <= 0:
            continue

        bid    = float(q.bid_price)
        ask    = float(q.ask_price)
        mid    = round((bid + ask) / 2, 4)
        spread = round(ask - bid, 4)
        spread_pct = round(spread / mid, 4) if mid > 0 else 1.0

        # Filter illiquid / wide-spread contracts
        if spread_pct > MAX_SPREAD_PCT:
            continue

        strike = strike_map[sym]
        iv     = _implied_volatility(mid, spy_price, strike, T, RISK_FREE_RATE, option_type)
        if iv is None:
            continue

        greeks = _greeks(spy_price, strike, T, RISK_FREE_RATE, iv, option_type)

        # Moneyness label
        diff = spy_price - strike if option_type == "call" else strike - spy_price
        if abs(diff) < 1:
            moneyness = "ATM"
        elif diff > 0:
            moneyness = f"ITM +{diff:.1f}"
        else:
            moneyness = f"OTM {diff:.1f}"

        candidates.append({
            "symbol":      sym,
            "strike":      strike,
            "option_type": option_type,
            "expiry":      str(expiry),
            "moneyness":   moneyness,
            "bid":         bid,
            "ask":         ask,
            "mid":         mid,
            "spread":      spread,
            "spread_pct":  spread_pct,
            "iv":          iv,
            "greeks":      greeks,
            "cost_per_contract": round(mid * 100, 2),   # 1 contract = 100 shares
        })

    # Sort: prefer near-ATM, tight spread
    candidates.sort(key=lambda x: (abs(x["strike"] - spy_price), x["spread_pct"]))
    return candidates[:CONTRACTS_FOR_CLAUDE]
