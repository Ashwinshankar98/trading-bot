import os, json
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks
from core.indicators import get_all_indicators
from core.regime import detect_regime
from core.paper_trader import (
    get_strategy_account, get_active_strategy, open_trade, close_trade,
    get_open_trades, open_option_trade, close_option_trade
)
from core.llm import decide_trade, decide_options_trade, write_post_mortem
from core.options import get_option_candidates, submit_option_order
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
    print(f"[SIGNAL] {strategy_id} {signal.upper()} {symbol} @ {price:.2f}", flush=True)
    try:
        await _process_signal_inner(symbol, signal, price, strategy_id)
    except Exception as e:
        import traceback
        print(f"[SIGNAL] ERROR: {e}\n{traceback.format_exc()}", flush=True)


async def _close_trades_for_strategy(symbol: str, price: float, strategy_id: str):
    """Shared close logic for both stock and options trades."""
    open_trades   = get_open_trades(strategy_id)
    symbol_trades = [t for t in open_trades if t["symbol"] == symbol]

    for trade in symbol_trades:
        asset_class = trade.get("asset_class", "stock")

        if asset_class == "option":
            # Close via Alpaca — submit sell order for the option
            option_symbol = trade.get("option_symbol")
            contracts     = trade.get("contracts", 1)
            if not option_symbol:
                continue
            print(f"[SIGNAL] Closing option {option_symbol} x{contracts}", flush=True)
            alpaca_result = await submit_option_order(option_symbol, contracts, action="sell")
            exit_premium  = alpaca_result.get("fill_price")
            if exit_premium is None:
                # Fall back to current quote
                from core.options import get_current_option_quote
                exit_premium = get_current_option_quote(option_symbol) or price
            pnl, msg = close_option_trade(trade["id"], exit_premium)
        else:
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

            tag = f"Option {trade.get('option_symbol', '')}" if asset_class == "option" else f"{symbol}"
            await send_telegram(
                f"🔴 <b>TRADE CLOSED</b>\n"
                f"Strategy: {STRATEGY_NAMES.get(strategy_id, strategy_id)}\n"
                f"{tag} | Exit: ${exit_premium if asset_class == 'option' else price:.2f}\n"
                f"PnL: ${pnl:.2f} {'✅ WIN' if pnl > 0 else '❌ LOSS'}"
            )


async def _process_signal_inner(symbol: str, signal: str, price: float, strategy_id: str):
    # ── Close signal ──────────────────────────────────────────────────────────
    if signal == "close":
        await _close_trades_for_strategy(symbol, price, strategy_id)
        return

    # ── Buy / Sell — fetch market context ────────────────────────────────────
    print(f"[SIGNAL] Fetching indicators for {symbol}", flush=True)
    indicators = get_all_indicators(symbol)
    print(f"[SIGNAL] Indicators: {indicators}", flush=True)

    regime   = detect_regime(symbol)
    account  = get_strategy_account(strategy_id)
    strategy = get_active_strategy()
    print(f"[SIGNAL] Regime: {regime}", flush=True)

    # ── Fetch options candidates ──────────────────────────────────────────────
    print(f"[SIGNAL] Fetching options candidates for {symbol} signal={signal}", flush=True)
    candidates = get_option_candidates(price, signal)
    print(f"[SIGNAL] {len(candidates)} candidates found", flush=True)

    if not candidates:
        print("[SIGNAL] No liquid options available — skipping", flush=True)
        return

    # ── Claude decides ────────────────────────────────────────────────────────
    decision = decide_options_trade(symbol, signal, indicators, regime, account, strategy, candidates)
    print(f"[SIGNAL] Decision: action={decision['action']} confidence={decision['confidence']:.2f} contract={decision.get('chosen_contract')}", flush=True)
    print(f"[SIGNAL] Reasoning: {decision.get('reasoning', '')[:150]}", flush=True)

    threshold = strategy.get("entry_threshold", 0.60)
    if decision["action"] != "open" or decision["confidence"] < threshold:
        print(f"[SIGNAL] Skipped — confidence={decision['confidence']:.2f} threshold={threshold:.2f}", flush=True)
        return

    # ── Find chosen candidate ─────────────────────────────────────────────────
    chosen_sym = decision.get("chosen_contract")
    candidate  = next((c for c in candidates if c["symbol"] == chosen_sym), candidates[0])
    contracts  = max(1, min(5, decision.get("contracts", 1)))

    # ── Submit Alpaca order ───────────────────────────────────────────────────
    alpaca_result = await submit_option_order(candidate["symbol"], contracts, action="buy")
    if alpaca_result.get("fill_price") is None:
        print(f"[SIGNAL] Order not filled: {alpaca_result}", flush=True)
        return

    # ── Record in DB ──────────────────────────────────────────────────────────
    side     = "long"   # always buying options (calls for buy, puts for sell)
    trade_id, msg = open_option_trade(
        symbol, side, price, candidate, decision, regime, strategy_id, alpaca_result
    )
    print(f"[SIGNAL] open_option_trade: trade_id={trade_id} msg={msg}", flush=True)

    if not trade_id:
        return

    g = candidate["greeks"]
    await send_telegram(
        f"🟢 <b>OPTION TRADE OPENED</b>\n"
        f"Strategy: {STRATEGY_NAMES.get(strategy_id, strategy_id)}\n"
        f"Contract: {candidate['symbol']}\n"
        f"Strike: ${candidate['strike']} | {candidate['moneyness']} | {candidate['option_type'].upper()}\n"
        f"Premium: ${alpaca_result['fill_price']:.2f} x {contracts} contracts = ${alpaca_result['fill_price']*100*contracts:.0f}\n"
        f"IV: {candidate['iv']*100:.1f}% | Delta: {g['delta']} | Theta: ${g['theta']:.3f}/day\n"
        f"Regime: {regime} | Confidence: {decision['confidence']:.0%}\n"
        f"Reason: {decision.get('reasoning', '')[:120]}"
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
