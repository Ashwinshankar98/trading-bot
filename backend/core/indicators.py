import yfinance as yf
import pandas as pd
import numpy as np

def fetch_ohlcv(symbol: str, period: str = "5d", interval: str = "1h") -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)
    df.dropna(inplace=True)
    return df

def rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi_  = 100 - (100 / (1 + rs))
    return round(float(rsi_.iloc[-1]), 2)

def macd(series: pd.Series, fast=12, slow=26, signal=9) -> dict:
    ema_fast   = series.ewm(span=fast, adjust=False).mean()
    ema_slow   = series.ewm(span=slow, adjust=False).mean()
    macd_line  = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram  = macd_line - signal_line
    return {
        "macd":      round(float(macd_line.iloc[-1]), 4),
        "signal":    round(float(signal_line.iloc[-1]), 4),
        "histogram": round(float(histogram.iloc[-1]), 4),
        "bullish_cross": (
            float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]) and
            float(macd_line.iloc[-2]) <= float(signal_line.iloc[-2])
        ),
        "bearish_cross": (
            float(macd_line.iloc[-1]) < float(signal_line.iloc[-1]) and
            float(macd_line.iloc[-2]) >= float(signal_line.iloc[-2])
        ),
    }

def ema(series: pd.Series, period: int) -> float:
    return round(float(series.ewm(span=period, adjust=False).mean().iloc[-1]), 4)

def ema_cross(series: pd.Series, fast=9, slow=21) -> dict:
    ema_f = series.ewm(span=fast, adjust=False).mean()
    ema_s = series.ewm(span=slow, adjust=False).mean()
    return {
        "ema_fast":      round(float(ema_f.iloc[-1]), 4),
        "ema_slow":      round(float(ema_s.iloc[-1]), 4),
        "bullish_cross": (
            float(ema_f.iloc[-1]) > float(ema_s.iloc[-1]) and
            float(ema_f.iloc[-2]) <= float(ema_s.iloc[-2])
        ),
        "bearish_cross": (
            float(ema_f.iloc[-1]) < float(ema_s.iloc[-1]) and
            float(ema_f.iloc[-2]) >= float(ema_s.iloc[-2])
        ),
        "price_above_slow": None,
    }

def vwap(df: pd.DataFrame) -> float:
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    cumvol  = df["Volume"].cumsum()
    cumtpv  = (typical * df["Volume"]).cumsum()
    vwap_   = cumtpv / cumvol
    return round(float(vwap_.iloc[-1]), 4)

def bollinger_bands(series: pd.Series, period=20, std=2) -> dict:
    sma   = series.rolling(period).mean()
    sigma = series.rolling(period).std()
    upper = sma + std * sigma
    lower = sma - std * sigma
    price = float(series.iloc[-1])
    return {
        "upper": round(float(upper.iloc[-1]), 4),
        "middle": round(float(sma.iloc[-1]), 4),
        "lower": round(float(lower.iloc[-1]), 4),
        "pct_b": round((price - float(lower.iloc[-1])) /
                       (float(upper.iloc[-1]) - float(lower.iloc[-1]) + 1e-9), 4),
    }

def adx(df: pd.DataFrame, period=14) -> float:
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    dm_pos = (high.diff()).clip(lower=0)
    dm_neg = (-low.diff()).clip(lower=0)
    atr_   = tr.rolling(period).mean()
    di_pos = 100 * dm_pos.rolling(period).mean() / atr_.replace(0, np.nan)
    di_neg = 100 * dm_neg.rolling(period).mean() / atr_.replace(0, np.nan)
    dx     = (100 * (di_pos - di_neg).abs() / (di_pos + di_neg).replace(0, np.nan))
    adx_   = dx.rolling(period).mean()
    return round(float(adx_.iloc[-1]), 2)

def atr(df: pd.DataFrame, period=14) -> float:
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return round(float(tr.rolling(period).mean().iloc[-1]), 4)

def get_all_indicators(symbol: str) -> dict:
    """Fetch OHLCV and compute all indicators for a symbol."""
    try:
        df = fetch_ohlcv(symbol)
        close = df["Close"]
        return {
            "symbol":   symbol,
            "price":    round(float(close.iloc[-1]), 4),
            "rsi":      rsi(close),
            "macd":     macd(close),
            "ema_cross": ema_cross(close),
            "vwap":     vwap(df),
            "bollinger": bollinger_bands(close),
            "adx":      adx(df),
            "atr":      atr(df),
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}
