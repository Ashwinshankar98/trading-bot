import asyncio
from fastapi import APIRouter, Query
from database import get_connection
from core.backtester import backtest_ema_cross, monte_carlo_simulation

router = APIRouter(prefix="/strategy", tags=["strategy"])

@router.get("/")
def list_versions():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM strategy_versions ORDER BY version DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.get("/active")
def get_active():
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM strategy_versions WHERE is_active = 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else {}

@router.post("/{version}/activate")
def activate_version(version: int):
    conn = get_connection()
    conn.execute("UPDATE strategy_versions SET is_active = 0")
    conn.execute(
        "UPDATE strategy_versions SET is_active = 1 WHERE version = ?", (version,)
    )
    conn.commit()
    conn.close()
    return {"activated": version}


@router.get("/backtest/{symbol}")
async def run_backtest(
    symbol: str,
    period_years: int = Query(default=2, ge=1, le=10),
    fast: int        = Query(default=9,  ge=3, le=50),
    slow: int        = Query(default=21, ge=5, le=200),
    sl_pct: float    = Query(default=0.02, ge=0.005, le=0.10),
    tp_pct: float    = Query(default=0.04, ge=0.01,  le=0.20),
):
    """
    Backtest the EMA-cross strategy on a symbol (slide 2).
    Returns CAGR, Sharpe, max drawdown, win rate + when it performs best/worst.
    """
    result = await asyncio.to_thread(
        backtest_ema_cross, symbol.upper(), period_years, fast, slow, sl_pct, tp_pct
    )
    return result


@router.post("/monte-carlo")
async def run_monte_carlo(
    win_rate: float         = Query(default=0.40, ge=0.0, le=1.0),
    avg_win_pct: float      = Query(default=4.0),
    avg_loss_pct: float     = Query(default=-2.0),
    n_trades: int           = Query(default=50,   ge=10, le=500),
    n_simulations: int      = Query(default=1000, ge=100, le=10000),
    position_size_pct: float = Query(default=0.10, ge=0.01, le=0.50),
):
    """
    Monte Carlo simulation (slide 9): run N simulations to estimate probability of loss,
    return distribution, worst-case scenarios, and whether the strategy is robust or fragile.
    """
    result = await asyncio.to_thread(
        monte_carlo_simulation,
        win_rate, avg_win_pct, avg_loss_pct,
        n_trades, n_simulations, 10000.0, position_size_pct,
    )
    return result


@router.get("/monte-carlo/from-history")
async def monte_carlo_from_history(
    strategy_id: str = Query(default="all"),
    n_trades: int    = Query(default=50),
):
    """
    Run Monte Carlo using actual closed trade statistics from the DB.
    """
    conn = get_connection()
    if strategy_id == "all":
        rows = conn.execute("SELECT pnl, pnl_pct FROM trades WHERE status='closed'").fetchall()
    else:
        rows = conn.execute(
            "SELECT pnl, pnl_pct FROM trades WHERE status='closed' AND strategy_id=?", (strategy_id,)
        ).fetchall()
    conn.close()

    trades = [dict(r) for r in rows if r["pnl"] is not None]
    if len(trades) < 5:
        return {"error": "Need at least 5 closed trades", "total": len(trades)}

    wins   = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]

    win_rate    = len(wins) / len(trades)
    avg_win     = round(sum(t["pnl_pct"] for t in wins)   / len(wins),   2) if wins   else 0.0
    avg_loss    = round(sum(t["pnl_pct"] for t in losses) / len(losses), 2) if losses else 0.0

    result = await asyncio.to_thread(
        monte_carlo_simulation, win_rate, avg_win, avg_loss, n_trades
    )
    result["source"] = {
        "strategy_id": strategy_id,
        "total_trades": len(trades),
        "win_rate": round(win_rate * 100, 1),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
    }
    return result
