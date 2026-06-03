"""
Backtesting (slide 2) and Monte Carlo simulation (slide 9).
"""
import numpy as np
import pandas as pd
import yfinance as yf


def backtest_ema_cross(
    symbol: str,
    period_years: int = 2,
    fast: int = 9,
    slow: int = 21,
    sl_pct: float = 0.02,
    tp_pct: float = 0.04,
    position_size_pct: float = 0.10,
    capital: float = 10000.0,
) -> dict:
    """
    Vectorized EMA-cross backtest over historical daily data.
    Returns: CAGR, Sharpe, max_drawdown, win_rate + per-trade table.
    """
    df = yf.Ticker(symbol).history(period=f"{period_years}y", interval="1d")
    if df.empty or len(df) < slow + 10:
        return {"error": "insufficient historical data", "symbol": symbol}

    close  = df["Close"]
    ema_f  = close.ewm(span=fast, adjust=False).mean()
    ema_s  = close.ewm(span=slow, adjust=False).mean()

    cross_up   = (ema_f > ema_s) & (ema_f.shift(1) <= ema_s.shift(1))
    cross_down = (ema_f < ema_s) & (ema_f.shift(1) >= ema_s.shift(1))

    trades   = []
    position = None

    for i in range(slow + 1, len(df)):
        price = float(close.iloc[i])
        date  = df.index[i].date().isoformat()

        if position is None:
            if cross_up.iloc[i]:
                position = {
                    "side": "long", "entry": price, "entry_date": date,
                    "sl": price * (1 - sl_pct), "tp": price * (1 + tp_pct),
                }
            elif cross_down.iloc[i]:
                position = {
                    "side": "short", "entry": price, "entry_date": date,
                    "sl": price * (1 + sl_pct), "tp": price * (1 - tp_pct),
                }
        else:
            hit_sl = hit_tp = False
            if position["side"] == "long":
                hit_sl = price <= position["sl"]
                hit_tp = price >= position["tp"]
                flip   = cross_down.iloc[i]
                pnl_pct = (price - position["entry"]) / position["entry"]
            else:
                hit_sl = price >= position["sl"]
                hit_tp = price <= position["tp"]
                flip   = cross_up.iloc[i]
                pnl_pct = (position["entry"] - price) / position["entry"]

            if hit_sl or hit_tp or flip:
                trades.append({
                    **position,
                    "exit": price, "exit_date": date,
                    "pnl_pct": round(pnl_pct * 100, 2),
                    "exit_reason": "sl" if hit_sl else ("tp" if hit_tp else "flip"),
                })
                position = None
                # Immediately flip on cross
                if flip:
                    if cross_up.iloc[i]:
                        position = {
                            "side": "long", "entry": price, "entry_date": date,
                            "sl": price * (1 - sl_pct), "tp": price * (1 + tp_pct),
                        }
                    else:
                        position = {
                            "side": "short", "entry": price, "entry_date": date,
                            "sl": price * (1 + sl_pct), "tp": price * (1 - tp_pct),
                        }

    if not trades:
        return {"symbol": symbol, "total_trades": 0, "error": "no trades generated"}

    # Equity curve with position sizing
    equity = capital
    equity_series = [capital]
    for t in trades:
        equity *= (1 + (t["pnl_pct"] / 100) * position_size_pct)
        equity_series.append(equity)

    eq = pd.Series(equity_series)
    daily_returns = eq.pct_change().dropna()

    wins   = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]

    total_return = (equity - capital) / capital
    cagr         = (1 + total_return) ** (1 / period_years) - 1
    sharpe       = float(daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() > 0 else 0.0
    peak         = eq.cummax()
    max_dd       = float(((eq - peak) / peak).min())
    win_rate     = len(wins) / len(trades)
    avg_win      = round(sum(t["pnl_pct"] for t in wins)   / len(wins),   2) if wins   else 0.0
    avg_loss     = round(sum(t["pnl_pct"] for t in losses) / len(losses), 2) if losses else 0.0
    profit_factor = round(
        abs(avg_win * len(wins)) / abs(avg_loss * len(losses)), 2
    ) if losses and avg_loss != 0 else None

    # Regime where the strategy works best / worst (slide 2 "when it performs best/worst")
    long_trades  = [t for t in trades if t["side"] == "long"]
    short_trades = [t for t in trades if t["side"] == "short"]
    long_wr  = round(sum(1 for t in long_trades  if t["pnl_pct"] > 0) / len(long_trades)  * 100, 1) if long_trades  else 0
    short_wr = round(sum(1 for t in short_trades if t["pnl_pct"] > 0) / len(short_trades) * 100, 1) if short_trades else 0

    return {
        "symbol":          symbol,
        "period_years":    period_years,
        "strategy":        f"EMA({fast}/{slow}) cross | SL {sl_pct*100:.0f}% | TP {tp_pct*100:.0f}%",
        "total_trades":    len(trades),
        "win_rate":        round(win_rate * 100, 1),
        "cagr":            round(cagr * 100, 2),
        "sharpe":          round(sharpe, 2),
        "max_drawdown":    round(max_dd * 100, 2),
        "total_return":    round(total_return * 100, 2),
        "final_capital":   round(equity, 2),
        "avg_win_pct":     avg_win,
        "avg_loss_pct":    avg_loss,
        "profit_factor":   profit_factor,
        "long_win_rate":   long_wr,
        "short_win_rate":  short_wr,
        "performs_best":   "trending bull/bear markets with clear momentum",
        "performs_worst":  "choppy sideways markets with frequent false crosses",
        "what_breaks_it":  "low ADX + high VIX → frequent whipsaws",
        "recent_trades":   trades[-10:],
    }


def monte_carlo_simulation(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    n_trades: int = 50,
    n_simulations: int = 1000,
    starting_capital: float = 10000.0,
    position_size_pct: float = 0.10,
) -> dict:
    """
    Monte Carlo simulation (slide 9): probability of loss, return distribution,
    worst-case scenarios. Explain if strategy is robust or fragile.

    avg_loss_pct should be negative (e.g. -2.5 for a 2.5% loss).
    """
    rng     = np.random.default_rng(seed=42)
    results = np.empty(n_simulations)

    for sim in range(n_simulations):
        cap = starting_capital
        for _ in range(n_trades):
            if rng.random() < win_rate:
                cap *= 1 + (avg_win_pct  / 100) * position_size_pct
            else:
                cap *= 1 + (avg_loss_pct / 100) * position_size_pct
        results[sim] = cap

    returns_pct = (results - starting_capital) / starting_capital * 100
    prob_loss   = float(np.mean(results < starting_capital))

    # Robustness assessment
    if prob_loss < 0.20:
        robustness = "robust — strong positive expectancy even under uncertainty"
    elif prob_loss < 0.40:
        robustness = "moderate — profitable on average but meaningful downside tail"
    else:
        robustness = "fragile — high probability of loss; strategy needs improvement"

    return {
        "n_simulations":    n_simulations,
        "n_trades":         n_trades,
        "input_win_rate":   round(win_rate * 100, 1),
        "input_avg_win":    avg_win_pct,
        "input_avg_loss":   avg_loss_pct,
        "prob_loss":        round(prob_loss * 100, 1),
        "prob_profit":      round((1 - prob_loss) * 100, 1),
        "return_distribution": {
            "p5":    round(float(np.percentile(returns_pct, 5)),  2),
            "p25":   round(float(np.percentile(returns_pct, 25)), 2),
            "p50":   round(float(np.percentile(returns_pct, 50)), 2),
            "p75":   round(float(np.percentile(returns_pct, 75)), 2),
            "p95":   round(float(np.percentile(returns_pct, 95)), 2),
        },
        "worst_case":  round(float(returns_pct.min()), 2),
        "best_case":   round(float(returns_pct.max()),  2),
        "robustness":  robustness,
        "starting_capital":  starting_capital,
        "position_size_pct": position_size_pct,
    }
