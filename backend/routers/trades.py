import os
import httpx
from fastapi import APIRouter
from database import get_connection
from core.paper_trader import get_all_strategy_accounts
from core.options import get_positions_live_pnl

router = APIRouter(prefix="/trades", tags=["trades"])

@router.get("/")
def list_trades(status: str = "all", strategy: str = "all", limit: int = 100):
    conn = get_connection()
    if status == "all" and strategy == "all":
        rows = conn.execute("SELECT * FROM trades ORDER BY entry_at DESC LIMIT ?", (limit,)).fetchall()
    elif status == "all":
        rows = conn.execute("SELECT * FROM trades WHERE strategy_id=? ORDER BY entry_at DESC LIMIT ?", (strategy, limit)).fetchall()
    elif strategy == "all":
        rows = conn.execute("SELECT * FROM trades WHERE status=? ORDER BY entry_at DESC LIMIT ?", (status, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM trades WHERE status=? AND strategy_id=? ORDER BY entry_at DESC LIMIT ?", (status, strategy, limit)).fetchall()
    conn.close()

    trades = [dict(r) for r in rows]

    # Inject live P&L from Alpaca for open options positions
    open_options = [t for t in trades if t.get("status") == "open" and t.get("asset_class") == "option"]
    if open_options:
        live_pnl = get_positions_live_pnl()
        for trade in trades:
            if trade.get("asset_class") == "option" and trade.get("status") == "open":
                sym = trade.get("option_symbol")
                if sym and sym in live_pnl:
                    pos = live_pnl[sym]
                    trade["live_pnl"]        = pos["unrealized_pnl"]
                    trade["live_pnl_pct"]    = pos["unrealized_plpc"]
                    trade["current_premium"] = pos["current_price"]

    return trades

@router.get("/account")
def get_account_summary():
    """Combined account across all strategies."""
    accounts  = get_all_strategy_accounts()
    conn      = get_connection()
    closed    = conn.execute("SELECT pnl, strategy_id FROM trades WHERE status='closed'").fetchall()
    open_tr   = conn.execute("SELECT * FROM trades WHERE status='open'").fetchall()
    conn.close()

    total_balance = sum(a["balance"] for a in accounts)
    total_equity  = sum(a["equity"]  for a in accounts)
    total_pnl     = sum(r["pnl"] for r in closed if r["pnl"])
    wins          = [r for r in closed if (r["pnl"] or 0) > 0]
    win_rate      = round(len(wins) / len(closed) * 100, 1) if closed else 0.0

    return {
        "balance":       round(total_balance, 2),
        "equity":        round(total_equity, 2),
        "total_pnl":     round(total_pnl, 2),
        "open_pnl":      round(total_equity - total_balance, 2),
        "win_rate":      win_rate,
        "total_trades":  len(closed),
        "open_trades":   len(open_tr),
        "updated_at":    accounts[0]["updated_at"] if accounts else None,
    }

@router.get("/strategies")
def get_strategy_breakdown():
    """Per-strategy performance breakdown."""
    accounts = get_all_strategy_accounts()
    conn     = get_connection()
    result   = []

    for acct in accounts:
        sid    = acct["strategy_id"]
        closed = conn.execute(
            "SELECT pnl FROM trades WHERE status='closed' AND strategy_id=?", (sid,)
        ).fetchall()
        open_t = conn.execute(
            "SELECT * FROM trades WHERE status='open' AND strategy_id=?", (sid,)
        ).fetchall()

        wins     = [r for r in closed if (r["pnl"] or 0) > 0]
        losses   = [r for r in closed if (r["pnl"] or 0) <= 0]
        total_pnl= round(sum(r["pnl"] for r in closed if r["pnl"]), 2)
        win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0.0
        avg_win  = round(sum(r["pnl"] for r in wins) / len(wins), 2) if wins else 0.0
        avg_loss = round(sum(r["pnl"] for r in losses) / len(losses), 2) if losses else 0.0

        result.append({
            "strategy_id":    sid,
            "name":           acct["name"],
            "description":    acct["description"],
            "is_active":      acct["is_active"],
            "balance":        round(acct["balance"], 2),
            "equity":         round(acct["equity"], 2),
            "total_pnl":      total_pnl,
            "pnl_pct":        round((total_pnl / 10000) * 100, 2),
            "win_rate":       win_rate,
            "total_trades":   len(closed),
            "open_trades":    len(open_t),
            "avg_win":        avg_win,
            "avg_loss":       avg_loss,
        })

    conn.close()
    return result

@router.get("/matrix")
def get_pnl_matrix():
    """P&L breakdown by strategy × symbol — shows which strategy works best on which ticker."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            strategy_id,
            symbol,
            COUNT(*)                                                  AS trades,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)                 AS wins,
            ROUND(SUM(pnl), 2)                                        AS total_pnl,
            ROUND(AVG(pnl), 2)                                        AS avg_pnl,
            ROUND(AVG(CASE WHEN pnl > 0 THEN pnl END), 2)            AS avg_win,
            ROUND(AVG(CASE WHEN pnl <= 0 THEN pnl END), 2)           AS avg_loss
        FROM trades
        WHERE status = 'closed'
        GROUP BY strategy_id, symbol
        ORDER BY strategy_id, symbol
    """).fetchall()

    open_rows = conn.execute("""
        SELECT strategy_id, symbol, COUNT(*) AS open_trades
        FROM trades WHERE status = 'open'
        GROUP BY strategy_id, symbol
    """).fetchall()
    conn.close()

    open_map = {(r["strategy_id"], r["symbol"]): r["open_trades"] for r in open_rows}

    result = []
    for r in rows:
        r = dict(r)
        win_rate = round(r["wins"] / r["trades"] * 100, 1) if r["trades"] else 0
        result.append({
            **r,
            "win_rate":   win_rate,
            "open_trades": open_map.get((r["strategy_id"], r["symbol"]), 0),
        })
    return result


@router.get("/{trade_id}/journal")
def get_trade_journal(trade_id: int):
    conn = get_connection()
    row  = conn.execute("SELECT * FROM trade_journal WHERE trade_id=?", (trade_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}

@router.post("/{trade_id}/close")
async def manual_close(trade_id: int, price: float):
    from core.paper_trader import close_trade
    conn  = get_connection()
    trade = conn.execute("SELECT strategy_id, side FROM trades WHERE id=?", (trade_id,)).fetchone()
    conn.close()

    pnl, msg = close_trade(trade_id, price)

    if pnl is not None and trade:
        strategy_id = trade["strategy_id"]
        strategy_names = {
            "ema_cross":    "EMA Cross + VWAP",
            "orb":          "Opening Range Breakout",
            "ema_pullback": "EMA 21 Pullback",
        }
        token   = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if token and chat_id:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id":    chat_id,
                        "parse_mode": "HTML",
                        "text": (
                            f"🔴 <b>TRADE CLOSED</b>\n"
                            f"Strategy: {strategy_names.get(strategy_id, strategy_id)}\n"
                            f"Trade ID: {trade_id} | Exit: ${price}\n"
                            f"PnL: ${pnl:.2f} {'✅ WIN' if pnl > 0 else '❌ LOSS'}"
                        ),
                    }
                )
    return {"pnl": pnl, "message": msg}