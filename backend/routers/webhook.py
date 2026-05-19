import os, json, logging
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks

logger = logging.getLogger(__name__)
from core.indicators import get_all_indicators
from core.regime import detect_regime
from core.paper_trader import get_strategy_account, get_active_strategy, open_trade, close_trade, get_open_trades
from core.llm import decide_trade, write_post_mortem
from database import get_connection

router = APIRouter(prefix="/webhook", tags=["webhook"])

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "changeme")

STRATEGY_NAMES = {
    "ema_cross":    "EMA Cross + VWAP",
    "orb":          "Opening Range Breakout",
    "ema_pullback": "EMA 21 Pullback",
}

async def send_telegram(message: str):
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"})


@router.post("/test")
async def test_trade(body: dict = None):
    """Force open a paper trade for pipeline testing — bypasses Claude."""
    if body is None:
        body = {}

    symbol      = body.get("symbol", "SPY").upper()
    side        = body.get("side", "long")
    price       = body.get("price", 738.52)
    strategy_id = body.get("strategy", "ema_cross")

    reasoning  = f"TEST TRADE — manually triggered for {STRATEGY_NAMES.get(strategy_id, strategy_id)} pipeline verification."
    indicators = {"test": True, "price": price}

    trade_id, msg = open_trade(symbol, side, price, indicators, reasoning, "test", strategy_id)

    if not trade_id:
        return {"status": "blocked", "reason": msg}

    await send_telegram(
        f"🧪 <b>TEST TRADE OPENED</b>\n"
        f"Strategy: {STRATEGY_NAMES.get(strategy_id, strategy_id)}\n"
        f"Symbol: {symbol} | Side: {side.upper()} | Price: ${price}\n"
        f"Close with: /trades/{trade_id}/close?price={round(price + 2, 2)}"
    )

    return {
        "status":      "opened",
        "trade_id":    trade_id,
        "symbol":      symbol,
        "side":        side,
        "price":       price,
        "strategy_id": strategy_id,
        "close_url":   f"/trades/{trade_id}/close?price={round(price + 2, 2)}"
    }


async def _process_signal(symbol: str, signal: str, price: float, strategy_id: str):
    """Process trade logic in the background so TradingView gets an immediate 200."""
    logger.info("[SIGNAL] %s %s %s @ %.2f", strategy_id, signal.upper(), symbol, price)
    try:
     await _process_signal_inner(symbol, signal, price, strategy_id)
    except Exception as e:
        logger.exception("[SIGNAL] Unhandled error processing %s %s: %s", strategy_id, signal, e)


async def _process_signal_inner(symbol: str, signal: str, price: float, strategy_id: str):
    # ── Close signal ──────────────────────────────────────────────────────────
    if signal == "close":
        open_trades   = get_open_trades(strategy_id)
        symbol_trades = [t for t in open_trades if t["symbol"] == symbol]
        for trade in symbol_trades:
            pnl, msg = close_trade(trade["id"], price)
            if pnl is not None:
                conn      = get_connection()
                trade_row = dict(conn.execute("SELECT * FROM trades WHERE id=?", (trade["id"],)).fetchone())
                conn.close()
                pm = write_post_mortem(trade_row, trade.get("indicators") or {})
                conn = get_connection()
                conn.execute("""
                    INSERT INTO trade_journal (trade_id, what_worked, what_failed, market_notes)
                    VALUES (?, ?, ?, ?)
                """, (trade["id"], pm["what_worked"], pm["what_failed"], pm["market_notes"]))
                conn.commit()
                conn.close()
                await send_telegram(
                    f"🔴 <b>TRADE CLOSED</b>\n"
                    f"Strategy: {STRATEGY_NAMES.get(strategy_id, strategy_id)}\n"
                    f"Symbol: {symbol} | Exit: ${price}\n"
                    f"PnL: ${pnl:.2f} {'✅ WIN' if pnl > 0 else '❌ LOSS'}"
                )
        return

    # ── Buy / Sell signal ─────────────────────────────────────────────────────
    logger.info("[SIGNAL] Fetching indicators for %s", symbol)
    indicators = get_all_indicators(symbol)
    logger.info("[SIGNAL] Indicators: %s", indicators)
    regime     = detect_regime(symbol)
    logger.info("[SIGNAL] Regime: %s", regime)
    account    = get_strategy_account(strategy_id)
    strategy   = get_active_strategy()

    decision = decide_trade(symbol, signal, indicators, regime, account, strategy)
    logger.info("[SIGNAL] Decision: action=%s confidence=%.2f reason=%s",
                decision["action"], decision["confidence"], decision["reasoning"][:100])

    if decision["action"] != "open" or decision["confidence"] < strategy.get("entry_threshold", 0.60):
        logger.info("[SIGNAL] Skipped — action=%s confidence=%.2f threshold=%.2f",
                    decision["action"], decision["confidence"], strategy.get("entry_threshold", 0.60))
        return

    side = decision["side"] or ("long" if signal == "buy" else "short")
    trade_id, msg = open_trade(symbol, side, price, indicators, decision["reasoning"], regime, strategy_id)
    logger.info("[SIGNAL] open_trade result: trade_id=%s msg=%s", trade_id, msg)

    if not trade_id:
        return

    await send_telegram(
        f"🟢 <b>TRADE OPENED</b>\n"
        f"Strategy: {STRATEGY_NAMES.get(strategy_id, strategy_id)}\n"
        f"Symbol: {symbol} | Side: {side.upper()} | Price: ${price}\n"
        f"Regime: {regime} | Confidence: {decision['confidence']:.0%}\n"
        f"Reason: {decision['reasoning'][:150]}"
    )


@router.post("/tradingview")
async def tradingview_webhook(payload: dict, background_tasks: BackgroundTasks):
    if payload.get("secret") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    symbol      = payload.get("symbol", "SPY").upper()
    signal      = payload.get("signal", "").lower()
    price       = float(payload.get("price", 0))
    strategy_id = payload.get("strategy", "ema_cross")

    conn = get_connection()
    conn.execute("""
        INSERT INTO signals (symbol, source, signal_type, payload)
        VALUES (?, 'tradingview', ?, ?)
    """, (symbol, signal, json.dumps(payload)))
    conn.commit()
    conn.close()

    # Acknowledge immediately — TradingView won't wait for yfinance + Claude
    background_tasks.add_task(_process_signal, symbol, signal, price, strategy_id)
    return {"status": "received", "symbol": symbol, "signal": signal, "strategy": strategy_id}