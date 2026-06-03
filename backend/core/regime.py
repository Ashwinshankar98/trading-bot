import yfinance as yf
from core.indicators import fetch_ohlcv, adx, atr


def detect_regime(symbol: str) -> dict:
    """
    Returns a rich regime dict covering all 4 market regime dimensions (slide 4):
      regime     : trending | ranging | volatile
      trend      : bull | bear | sideways
      volatility : low | medium | high
      volume     : above_avg | normal | below_avg
    Also includes recommendations for strategy selection.
    """
    try:
        df = fetch_ohlcv(symbol, period="5d", interval="1h")
        if df.empty:
            return _default_regime()

        adx_v   = adx(df)
        atr_v   = atr(df)
        price   = float(df["Close"].iloc[-1])
        atr_pct = atr_v / price

        # Macro: VIX and 10-yr treasury yield
        try:
            vix_df = yf.Ticker("^VIX").history(period="2d", interval="1d")
            tnx_df = yf.Ticker("^TNX").history(period="2d", interval="1d")
            vix = round(float(vix_df["Close"].iloc[-1]), 2) if not vix_df.empty else 20.0
            tnx = round(float(tnx_df["Close"].iloc[-1]), 2) if not tnx_df.empty else None
        except Exception:
            vix, tnx = 20.0, None

        # Volume vs 20-period average
        vol       = df["Volume"]
        vol_avg   = float(vol.rolling(min(20, len(vol))).mean().iloc[-1])
        vol_cur   = float(vol.iloc[-1])
        vol_ratio = vol_cur / vol_avg if vol_avg > 0 else 1.0
        vol_label = "above_avg" if vol_ratio > 1.2 else ("below_avg" if vol_ratio < 0.8 else "normal")

        # Trend direction via EMA stack
        close = df["Close"]
        ema9  = float(close.ewm(span=9,  adjust=False).mean().iloc[-1])
        ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=min(50, len(close) - 1), adjust=False).mean().iloc[-1])

        if ema9 > ema21 and ema21 > ema50:
            trend_dir = "bull"
        elif ema9 < ema21 and ema21 < ema50:
            trend_dir = "bear"
        else:
            trend_dir = "sideways"

        # Volatility level
        if vix > 28 or atr_pct > 0.022:
            vol_level = "high"
        elif vix < 16 or atr_pct < 0.008:
            vol_level = "low"
        else:
            vol_level = "medium"

        # Base regime classification
        if atr_pct > 0.025 or vix > 30:
            base = "volatile"
        elif adx_v > 25:
            base = "trending"
        else:
            base = "ranging"

        # Strategy recommendations (slide 4 output)
        if base == "trending":
            recommended = ["ema_cross", "momentum", "trend_following"]
            avoid       = ["mean_reversion", "range_trading", "fade_moves"]
        elif base == "ranging":
            recommended = ["mean_reversion", "bollinger_bounce", "orb"]
            avoid       = ["trend_following", "breakout_chasing"]
        else:
            recommended = ["reduce_size", "wait_for_confirmation"]
            avoid       = ["ema_cross", "orb", "trend_following"]

        return {
            "regime":                 base,
            "trend":                  trend_dir,
            "volatility":             vol_level,
            "volume":                 vol_label,
            "volume_ratio":           round(vol_ratio, 2),
            "recommended_strategies": recommended,
            "avoid":                  avoid,
            "adx":                    adx_v,
            "atr_pct":                round(atr_pct * 100, 2),
            "vix":                    vix,
            "tnx_10yr":               tnx,
        }
    except Exception:
        return _default_regime()


def _default_regime() -> dict:
    return {
        "regime": "ranging", "trend": "sideways",
        "volatility": "medium", "volume": "normal",
        "volume_ratio": 1.0,
        "recommended_strategies": [], "avoid": [],
        "adx": None, "atr_pct": None, "vix": None, "tnx_10yr": None,
    }
