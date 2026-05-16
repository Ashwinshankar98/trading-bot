from fastapi import APIRouter
from database import get_connection
import os
import httpx

router = APIRouter(prefix="/trades", tags=["trades"])

@router.get("/")
def list_trades(status: str = "all", limit: int = 100):
    conn = get_connection()
    if status == "all":
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY entry_at DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = ? ORDER BY entry_at DESC LIMIT ?",
            (status, limit)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.get("/account")
def get_account_summary():
    conn = get_connection()
    account = dict(conn.execute("SELECT * FROM account WHERE id = 1").fetchone())
    closed  = conn.execute(
        "SELECT pnl FROM trades WHERE status = 'closed'"
    ).fetchall()
    conn.close()

    total_pnl   = sum(r["pnl"] for r in closed if r["pnl"])
    wins        = [r for r in closed if (r["pnl"] or 0) > 0]
    win_rate    = round(len(wins) / len(closed) * 100, 1) if closed else 0.0
    open_pnl    = round(account["equity"] - account["balance"], 2)

    return {
        **account,
        "total_pnl":   round(total_pnl, 2),
        "open_pnl":    open_pnl,
        "win_rate":    win_rate,
        "total_trades": len(closed),
    }

@router.get("/{trade_id}/journal")
def get_trade_journal(trade_id: int):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM trade_journal WHERE trade_id = ?", (trade_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else {}

@router.post("/{trade_id}/close")
def manual_close(trade_id: int, price: float):
    from core.paper_trader import close_trade
    pnl, msg = close_trade(trade_id, price)
    return {"pnl": pnl, "message": msg}

@router.get("/test-telegram")
async def test_telegram():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        return {"error": "Telegram not configured"}
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json={
            "chat_id": chat_id,
            "text": "Trading bot is live and connected to Telegram!"
        })
    
    return {"status": "sent", "telegram_response": resp.json()}
