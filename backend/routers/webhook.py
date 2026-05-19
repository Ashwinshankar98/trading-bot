import os, json
import httpx
from fastapi import APIRouter, HTTPException
from models.schemas import WebhookPayload
from core.indicators import get_all_indicators
from core.regime import detect_regime
from core.paper_trader import get_account, get_active_strategy, open_trade, close_trade, get_open_trades
from core.llm import decide_trade, write_post_mortem
from database import get_connection

router = APIRouter(prefix="/webhook", tags=["webhook"])

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "changeme")
# Paper trading mode — no market hours restriction
PAPER_TRADING  = os.getenv("PAPER_TRADING", "true").lower() == "true"

async def send_telegram(message: str):
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": "HTML"
        })


@router.post("/test")
async def test_trade(body: dict = None):
    """
    Force open a paper trade for testing — bypasses Claude and indicator checks.
    Use this to verify the full pipeline: trade opens, shows in dashboard,
    Telegram fires, close it, P&L updates.
    """
    if body is None:
        body = {}

    symbol = body.get("symbol", "SPY").upper()
    side   = body.get("side", "long")
    price  = body.get("price", 738.52)

    reasoning = "TEST TRADE — manually triggered to verify pipeline. Not based on real signal."
    regime    = "ranging"
    indicators = {"test": True, "price": price}

    trade_id, msg = open_trade(symbol, side, price, indicators, reasoning, regime)

    if not trade_id:
        return {"status": "blocked", "reason": msg}

    await send_telegram(
        f"🧪 <b>TEST TRADE OPENED</b>\n"
        f"Symbol: {symbol}\n"
        f"Side: {side.upper()}\n"
        f"Price: ${price}\n"
        f"This is a test trade to verify the pipeline."
    )

    return {
        "status":   "opened",
        "trade_id": trade_id,
        "symbol":   symbol,
        "side":     side,
        "price":    price,
        "message":  "Test trade opened. Check dashboard and Telegram. Use /trades/{id}/close to close it.",
        "close_url": f"/trades/{trade_id}/close?price={price + 1.5}"
    }


@router.post("/tradingview")
async def tradingview_webhook(payload: WebhookPayload):
    if payload.secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    symbol = payload.symbol.upper()
    signal = payload.signal.lower()
    price  = payload.price

    conn = get_connection()
    conn.execute("""
        INSERT INTO signals (symbol, source, signal_type, payload)
        VALUES (?, 'tradingview', ?, ?)
    """, (symbol, signal, json.dumps(payload.model_dump())))
    conn.commit()
    conn.close()

    # ── Close signal ──────────────────────────────────────────────────────────
    if signal == "close":
        open_trades   = get_open_trades()
        symbol_trades = [t for t in open_trades if t["symbol"] == symbol]
        results = []
        for trade in symbol_trades:
            pnl, msg = close_trade(trade["id"], price)
            if pnl is not None:
                conn      = get_connection()
                trade_row = dict(conn.execute(
                    "SELECT * FROM trades WHERE id = ?", (trade["id"],)
                ).fetchone())
                conn.close()
                pm = write_post_mortem(trade_row, trade.get("indicators") or {})
                conn = get_connection()
                conn.execute("""
                    INSERT INTO trade_journal (trade_id, what_worked, what_failed, market_notes)
                    VALUES (?, ?, ?, ?)
                """, (trade["id"], pm["what_worked"], pm["what_failed"], pm["market_notes"]))
                conn.commit()
                conn.close()
                results.append({"trade_id": trade["id"], "pnl": pnl})
                await send_telegram(
                    f"🔴 <b>TRADE CLOSED</b>\n"
                    f"Symbol: {symbol}\n"
                    f"PnL: ${pnl:.2f}\n"
                    f"{'✅ WIN' if pnl > 0 else '❌ LOSS'}"
                )
        return {"status": "closed", "results": results}

    # ── Buy / Sell signal ─────────────────────────────────────────────────────
    indicators = get_all_indicators(symbol)
    regime     = detect_regime(symbol)
    account    = get_account()
    strategy   = get_active_strategy()

    decision = decide_trade(symbol, signal, indicators, regime, account, strategy)

    if decision["action"] != "open" or decision["confidence"] < strategy.get("entry_threshold", 0.60):
        return {
            "status":     "skipped",
            "reason":     decision["reasoning"],
            "confidence": decision["confidence"]
        }

    side     = decision["side"] or ("long" if signal == "buy" else "short")
    trade_id, msg = open_trade(
        symbol, side, price,
        indicators, decision["reasoning"], regime
    )

    if not trade_id:
        return {"status": "blocked", "reason": msg}

    await send_telegram(
        f"🟢 <b>TRADE OPENED</b>\n"
        f"Symbol: {symbol}\n"
        f"Side: {side.upper()}\n"
        f"Price: ${price}\n"
        f"Regime: {regime}\n"
        f"Confidence: {decision['confidence']}\n"
        f"Reason: {decision['reasoning'][:200]}"
    )

    return {
        "status":     "opened",
        "trade_id":   trade_id,
        "symbol":     symbol,
        "side":       side,
        "price":      price,
        "regime":     regime,
        "confidence": decision["confidence"],
        "reasoning":  decision["reasoning"]
    }