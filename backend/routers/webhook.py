import os, json
from fastapi import APIRouter, HTTPException
from models.schemas import WebhookPayload
from core.indicators import get_all_indicators
from core.regime import detect_regime
from core.paper_trader import get_account, get_active_strategy, open_trade, close_trade, get_open_trades
from core.llm import decide_trade, write_post_mortem
from database import get_connection

router = APIRouter(prefix="/webhook", tags=["webhook"])

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "changeme")

@router.post("/tradingview")
async def tradingview_webhook(payload: WebhookPayload):
    if payload.secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    symbol  = payload.symbol.upper()
    signal  = payload.signal.lower()   # buy / sell / close
    price   = payload.price

    conn = get_connection()
    conn.execute("""
        INSERT INTO signals (symbol, source, signal_type, payload)
        VALUES (?, 'tradingview', ?, ?)
    """, (symbol, signal, json.dumps(payload.model_dump())))
    conn.commit()
    conn.close()

    if signal == "close":
        open_trades = get_open_trades()
        symbol_trades = [t for t in open_trades if t["symbol"] == symbol]
        results = []
        for trade in symbol_trades:
            pnl, msg = close_trade(trade["id"], price)
            if pnl is not None:
                conn = get_connection()
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
        return {"status": "closed", "results": results}

    indicators = get_all_indicators(symbol)
    regime     = detect_regime(symbol)
    account    = get_account()
    strategy   = get_active_strategy()

    decision = decide_trade(symbol, signal, indicators, regime, account, strategy)

    if decision["action"] != "open" or decision["confidence"] < strategy.get("entry_threshold", 0.60):
        return {
            "status": "skipped",
            "reason": decision["reasoning"],
            "confidence": decision["confidence"]
        }

    side = decision["side"] or ("long" if signal == "buy" else "short")
    trade_id, msg = open_trade(
        symbol, side, price,
        indicators, decision["reasoning"], regime
    )

    if not trade_id:
        return {"status": "blocked", "reason": msg}

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
