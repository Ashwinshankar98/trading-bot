from core.indicators import fetch_ohlcv, adx, atr

def detect_regime(symbol: str) -> str:
    """
    Returns 'trending', 'ranging', or 'volatile'.
    - trending:  ADX > 25 (strong directional move)
    - volatile:  ATR/price > 0.03 (big swings, stay out)
    - ranging:   everything else (RSI mean-reversion plays)
    """
    try:
        df    = fetch_ohlcv(symbol, period="5d", interval="1h")
        adx_v = adx(df)
        atr_v = atr(df)
        price = float(df["Close"].iloc[-1])
        atr_pct = atr_v / price

        if atr_pct > 0.03:
            return "volatile"
        elif adx_v > 25:
            return "trending"
        else:
            return "ranging"
    except Exception:
        return "ranging"
