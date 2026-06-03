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

def volume_analysis(df: pd.DataFrame, avg_period: int = 20) -> dict:
    vol = df["Volume"]
    avg = float(vol.rolling(min(avg_period, len(vol))).mean().iloc[-1])
    cur = float(vol.iloc[-1])
    ratio = cur / avg if avg > 0 else 1.0
    return {
        "current": int(cur),
        "avg_20d":  int(avg),
        "ratio":    round(ratio, 2),
        "label":    "above_avg" if ratio > 1.2 else ("below_avg" if ratio < 0.8 else "normal"),
    }


def get_macro_indicators() -> dict:
    """Fetch VIX and 10-year treasury yield for macro context."""
    try:
        vix_df = yf.Ticker("^VIX").history(period="2d", interval="1d")
        tnx_df = yf.Ticker("^TNX").history(period="2d", interval="1d")
        return {
            "vix":       round(float(vix_df["Close"].iloc[-1]), 2) if not vix_df.empty else None,
            "tnx_10yr":  round(float(tnx_df["Close"].iloc[-1]), 2) if not tnx_df.empty else None,
        }
    except Exception:
        return {"vix": None, "tnx_10yr": None}


def detect_fvg(df: pd.DataFrame, lookback: int = 50) -> dict:
    """
    Fair Value Gap: 3-candle price imbalance zones where price tends to return.
    Bullish FVG: candle[i].low > candle[i-2].high  → gap between them is support.
    Bearish FVG: candle[i].high < candle[i-2].low  → gap between them is resistance.
    Returns the nearest active bullish FVG (below price) and bearish FVG (above price).
    """
    if len(df) < 5:
        return {"bullish": None, "bearish": None, "count_bull": 0, "count_bear": 0}

    recent        = df.iloc[-lookback:].copy()
    current_price = float(recent["Close"].iloc[-1])
    bull_fvgs, bear_fvgs = [], []

    for i in range(2, len(recent)):
        # Bullish FVG
        if float(recent["Low"].iloc[i]) > float(recent["High"].iloc[i - 2]):
            bull_fvgs.append({
                "bottom":   round(float(recent["High"].iloc[i - 2]), 4),
                "top":      round(float(recent["Low"].iloc[i]), 4),
                "bars_ago": len(recent) - i - 1,
            })
        # Bearish FVG
        if float(recent["High"].iloc[i]) < float(recent["Low"].iloc[i - 2]):
            bear_fvgs.append({
                "bottom":   round(float(recent["High"].iloc[i]), 4),
                "top":      round(float(recent["Low"].iloc[i - 2]), 4),
                "bars_ago": len(recent) - i - 1,
            })

    # Active: bullish below current price (unmitigated support)
    #         bearish above current price (unmitigated resistance)
    active_bull = sorted(
        [f for f in bull_fvgs if f["top"] < current_price],
        key=lambda x: current_price - x["top"]
    )
    active_bear = sorted(
        [f for f in bear_fvgs if f["bottom"] > current_price],
        key=lambda x: x["bottom"] - current_price
    )

    return {
        "bullish":     active_bull[0] if active_bull else None,
        "bearish":     active_bear[0] if active_bear else None,
        "count_bull":  len(active_bull),
        "count_bear":  len(active_bear),
    }


def detect_liquidity_sweep(df: pd.DataFrame, swing_period: int = 5) -> dict:
    """
    Liquidity sweep (stop hunt): price wick beyond a swing high/low then closed back.
    Signals smart money absorbed retail stops — high-probability reversal point.
    Checks the last 5 bars against the most recent swing pivots.
    """
    if len(df) < swing_period * 4:
        return {"bull_sweep": False, "bear_sweep": False, "level": None, "bars_ago": None,
                "last_swing_high": None, "last_swing_low": None}

    window = df.iloc[-(swing_period * 6):].copy()
    highs  = window["High"].values
    lows   = window["Low"].values
    n      = len(highs)

    swing_highs, swing_lows = [], []
    for i in range(swing_period, n - swing_period):
        if highs[i] == max(highs[i - swing_period: i + swing_period + 1]):
            swing_highs.append(float(highs[i]))
        if lows[i]  == min(lows[i  - swing_period: i + swing_period + 1]):
            swing_lows.append(float(lows[i]))

    last_swing_high = max(swing_highs) if swing_highs else None
    last_swing_low  = min(swing_lows)  if swing_lows  else None

    bull_sweep = bear_sweep = False
    sweep_level = sweep_bars_ago = None

    last5 = df.iloc[-5:]
    for i in range(len(last5)):
        bar_high  = float(last5["High"].iloc[i])
        bar_low   = float(last5["Low"].iloc[i])
        bar_close = float(last5["Close"].iloc[i])
        ago       = len(last5) - 1 - i

        # Bullish sweep: wick below swing low, closed above it
        if last_swing_low and bar_low < last_swing_low and bar_close > last_swing_low:
            bull_sweep, sweep_level, sweep_bars_ago = True, last_swing_low, ago

        # Bearish sweep: wick above swing high, closed below it
        if last_swing_high and bar_high > last_swing_high and bar_close < last_swing_high:
            bear_sweep, sweep_level, sweep_bars_ago = True, last_swing_high, ago

    return {
        "bull_sweep":       bull_sweep,
        "bear_sweep":       bear_sweep,
        "level":            round(sweep_level, 4)      if sweep_level      else None,
        "bars_ago":         sweep_bars_ago,
        "last_swing_high":  round(last_swing_high, 4) if last_swing_high  else None,
        "last_swing_low":   round(last_swing_low, 4)  if last_swing_low   else None,
    }


def multi_factor_score(indicators: dict, signal: str) -> dict:
    """
    Score 5 factors for signal alignment. Require ≥3/5 to proceed.
    Factors: momentum, trend, VWAP, ADX, FVG/sweep confluence (SMC).
    """
    score = 0
    factors = {}
    is_long = signal.lower() in ("buy", "long")

    # 1. Momentum: RSI in healthy zone + MACD histogram direction
    rsi_val   = indicators.get("rsi") or 50
    macd_hist = (indicators.get("macd") or {}).get("histogram") or 0
    if is_long:
        momentum = (40 <= rsi_val <= 70) and macd_hist > 0
    else:
        momentum = (30 <= rsi_val <= 60) and macd_hist < 0
    factors["momentum"] = bool(momentum)
    if momentum: score += 1

    # 2. Trend: EMA fast vs slow alignment
    ema_data = indicators.get("ema_cross") or {}
    ema_fast = ema_data.get("ema_fast") or 0
    ema_slow = ema_data.get("ema_slow") or 0
    trend_ok = (ema_fast > ema_slow if is_long else ema_fast < ema_slow) if (ema_fast and ema_slow) else False
    factors["trend"] = bool(trend_ok)
    if trend_ok: score += 1

    # 3. VWAP: price on correct side
    price    = indicators.get("price") or 0
    vwap_val = indicators.get("vwap") or price
    vwap_ok  = price > vwap_val if is_long else price < vwap_val
    factors["vwap"] = bool(vwap_ok)
    if vwap_ok: score += 1

    # 4. ADX: market is trending, not choppy
    adx_ok = (indicators.get("adx") or 0) > 20
    factors["adx_trending"] = bool(adx_ok)
    if adx_ok: score += 1

    # 5. SMC confluence: active FVG or liquidity sweep in the right direction
    fvg   = indicators.get("fvg") or {}
    sweep = indicators.get("sweep") or {}
    if is_long:
        smc_ok = bool(fvg.get("bullish")) or bool(sweep.get("bull_sweep"))
    else:
        smc_ok = bool(fvg.get("bearish")) or bool(sweep.get("bear_sweep"))
    factors["fvg_or_sweep"] = bool(smc_ok)
    if smc_ok: score += 1

    return {"score": score, "max": 5, "pct": round(score / 5, 2), "factors": factors}


def get_all_indicators(symbol: str) -> dict:
    """Fetch OHLCV and compute all indicators for a symbol."""
    try:
        # Try 5d first, fall back to 1mo if market is closed
        df = fetch_ohlcv(symbol, period="5d", interval="1h")
        if df.empty or len(df) < 5:
            df = fetch_ohlcv(symbol, period="1mo", interval="1d")
        if df.empty:
            return {"error": "no data available", "symbol": symbol}

        close = df["Close"]
        last_close = round(float(close.iloc[-1]), 4)

        # EMA cross — need at least 21 bars
        ema_cross_val = ema_cross(close) if len(close) >= 21 else {
            "ema_fast": None, "ema_slow": None,
            "bullish_cross": False, "bearish_cross": False
        }
        ema_cross_val["price_above_slow"] = (
            last_close > ema_cross_val["ema_slow"]
            if ema_cross_val["ema_slow"] else None
        )

        vol_avg = float(close.rolling(20).mean().iloc[-1]) if len(df) >= 20 else None
        rvol_val = round(float(df["Volume"].iloc[-1]) / float(df["Volume"].rolling(20).mean().iloc[-1]), 2) \
                   if len(df) >= 20 and df["Volume"].rolling(20).mean().iloc[-1] > 0 else None

        return {
            "symbol":    symbol,
            "price":     last_close,
            "rsi":       rsi(close) if len(close) >= 14 else None,
            "macd":      macd(close) if len(close) >= 26 else None,
            "ema_cross": ema_cross_val,
            "vwap":      vwap(df),
            "bollinger": bollinger_bands(close) if len(close) >= 20 else None,
            "adx":       adx(df) if len(df) >= 14 else None,
            "atr":       atr(df) if len(df) >= 14 else None,
            "rvol":      rvol_val,
            "fvg":       detect_fvg(df),
            "sweep":     detect_liquidity_sweep(df),
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}
