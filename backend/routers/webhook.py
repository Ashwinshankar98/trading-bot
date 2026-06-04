import os, json, asyncio
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from core.indicators import get_all_indicators, multi_factor_score
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
        print("[TELEGRAM] No token/chat_id configured — skipping notification", flush=True)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"})
        if not resp.json().get("ok"):
            print(f"[TELEGRAM] API error: {resp.text}", flush=True)
    except Exception as e:
        print(f"[TELEGRAM] Failed to send: {e}", flush=True)


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


@router.post("/test/pipeline")
async def test_pipeline(body: dict = None):
    """
    Dry-run end-to-end test: runs all 4 gates including Claude, sends Telegram,
    but does NOT submit any Alpaca order or write a trade to the DB.
    """
    if body is None:
        body = {}
    symbol      = body.get("symbol", "SPY").upper()
    signal      = body.get("signal", "buy").lower()
    strategy_id = body.get("strategy", "ema_pullback")

    print(f"[TEST] dry-run pipeline: {strategy_id} {signal.upper()} {symbol}", flush=True)

    indicators  = await asyncio.to_thread(get_all_indicators, symbol)
    global indicators_cache
    indicators_cache = indicators
    price       = indicators.get("price") or body.get("price", 0.0)
    regime_data = await asyncio.to_thread(detect_regime, symbol)
    account     = get_strategy_account(strategy_id)
    strategy    = get_active_strategy()
    factor      = multi_factor_score(indicators, signal)
    candidates: list = []

    result = {
        "mode": "dry_run",
        "symbol": symbol, "signal": signal, "price": price,
        "strategy": strategy_id,
        "regime": regime_data,
        "factor_score": factor,
        "gates": {}
    }

    # Gate 1
    vix = regime_data.get("vix") or 0
    result["gates"]["gate1_vix"] = {"pass": vix <= 30, "vix": vix}
    if vix > 30:
        await send_telegram(_gate_report(symbol, signal, price, strategy_id,
                                         regime_data, factor, candidates,
                                         final_status="[DRY RUN] REJECTED — VIX panic regime"))
        return {**result, "stopped_at": "gate1"}

    # Gate 2
    result["gates"]["gate2_factor"] = {"pass": factor["score"] >= 3, "score": factor["score"], "factors": factor["factors"]}
    if factor["score"] < 3:
        await send_telegram(_gate_report(symbol, signal, price, strategy_id,
                                         regime_data, factor, candidates,
                                         final_status=f"[DRY RUN] REJECTED — {factor['score']}/5 factors"))
        return {**result, "stopped_at": "gate2"}

    # Gate 3
    candidates = await asyncio.to_thread(get_option_candidates, price, signal)
    result["gates"]["gate3_options"] = {"pass": bool(candidates), "count": len(candidates)}
    if not candidates:
        await send_telegram(_gate_report(symbol, signal, price, strategy_id,
                                         regime_data, factor, candidates,
                                         final_status="[DRY RUN] REJECTED — no liquid options"))
        return {**result, "stopped_at": "gate3"}

    # Gate 4 — Claude (real call, no order placed)
    decision = await asyncio.to_thread(
        decide_options_trade, symbol, signal, indicators,
        regime_data, account, strategy, candidates, factor
    )
    threshold = max(strategy.get("entry_threshold", 0.60), 0.70)
    claude_ok = decision["action"] == "open" and decision["confidence"] >= threshold
    result["gates"]["gate4_claude"] = {
        "pass": claude_ok, "action": decision["action"],
        "confidence": decision["confidence"], "rr_ratio": decision.get("rr_ratio"),
        "reasoning": decision.get("reasoning")
    }
    result["decision"] = decision

    final = "[DRY RUN] WOULD OPEN — no order placed" if claude_ok else f"[DRY RUN] REJECTED — Claude {decision['confidence']:.0%}"
    await send_telegram(_gate_report(symbol, signal, price, strategy_id,
                                     regime_data, factor, candidates, decision,
                                     final_status=final))
    return {**result, "stopped_at": "none" if claude_ok else "gate4"}


@router.post("/test/claude")
async def test_claude(body: dict = None):
    """
    Test Claude (Gate 4) directly with live indicators + real options candidates.
    Skips Gates 1-3. No Alpaca order placed. Sends Telegram with the decision.
    """
    if body is None:
        body = {}
    symbol      = body.get("symbol", "SPY").upper()
    signal      = body.get("signal", "buy").lower()
    strategy_id = body.get("strategy", "ema_pullback")

    print(f"[TEST] direct Claude test: {strategy_id} {signal.upper()} {symbol}", flush=True)

    indicators  = await asyncio.to_thread(get_all_indicators, symbol)
    global indicators_cache
    indicators_cache = indicators
    price       = indicators.get("price") or 0.0
    regime_data = await asyncio.to_thread(detect_regime, symbol)
    account     = get_strategy_account(strategy_id)
    strategy    = get_active_strategy()
    factor      = multi_factor_score(indicators, signal)

    candidates  = await asyncio.to_thread(get_option_candidates, price, signal)
    if not candidates:
        return {"status": "error", "reason": "No option candidates — market may be closed"}

    print(f"[TEST] Calling Claude with {len(candidates)} candidates...", flush=True)
    decision = await asyncio.to_thread(
        decide_options_trade, symbol, signal, indicators,
        regime_data, account, strategy, candidates, factor
    )
    print(f"[TEST] Claude responded: action={decision['action']} confidence={decision['confidence']}", flush=True)

    threshold = max(strategy.get("entry_threshold", 0.60), 0.70)
    claude_ok  = decision["action"] == "open" and decision["confidence"] >= threshold
    final      = "[CLAUDE TEST] WOULD OPEN" if claude_ok else f"[CLAUDE TEST] SKIP — {decision['confidence']:.0%} confidence"

    await send_telegram(_gate_report(symbol, signal, price, strategy_id,
                                     regime_data, factor, candidates, decision,
                                     final_status=final))
    return {
        "status":     "ok",
        "symbol":     symbol, "signal": signal, "price": price,
        "candidates": len(candidates),
        "decision":   decision,
        "would_open": claude_ok,
    }


@router.post("/test/reject")
async def test_reject(body: dict = None):
    """Force a Gate 2 rejection notification to verify Telegram is working."""
    if body is None:
        body = {}
    symbol      = body.get("symbol", "SPY").upper()
    signal      = body.get("signal", "buy").lower()
    strategy_id = body.get("strategy", "ema_pullback")
    price       = body.get("price", 0.01)

    fake_regime = {"regime": "ranging", "trend": "sideways", "vix": 16.0,
                   "adx": 15.0, "atr_pct": 0.20, "volatility": "low", "volume": "below_avg"}
    fake_factor = {"score": 1, "factors": {"momentum": False, "trend": False,
                                            "vwap": False, "adx_trending": False,
                                            "fvg_or_sweep": True}}
    global indicators_cache
    indicators_cache = {"rsi": 45, "adx": 15, "macd": {"histogram": -0.1}}

    await send_telegram(_gate_report(symbol, signal, price, strategy_id,
                                     fake_regime, fake_factor, [],
                                     final_status="[TEST] REJECTED — Gate 2 forced failure"))
    return {"status": "test_reject_sent", "symbol": symbol, "signal": signal}


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

    if not symbol_trades:
        S = STRATEGY_NAMES.get(strategy_id, strategy_id)
        print(f"[SIGNAL] CLOSE received but no open trades for {symbol} / {strategy_id}", flush=True)
        await send_telegram(
            f"📭 <b>CLOSE signal — no open trades</b>\n"
            f"Strategy: {S} | {symbol} @ ${price:.2f}\n"
            f"Signal received but no position was open to close."
        )
        return

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
            pm = await asyncio.to_thread(write_post_mortem, trade_row, trade.get("indicators") or {})
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


def _gate_report(symbol: str, signal: str, price: float, strategy_id: str,
                  regime_data: dict, factor: dict, candidates: list,
                  decision: dict = None, final_status: str = "REJECTED") -> str:
    """
    Build a Telegram message showing every gate's pass/fail result.
    Sent for every buy/sell signal — tells the user exactly what happened.
    """
    T   = lambda b: "✅" if b else "❌"
    S   = STRATEGY_NAMES.get(strategy_id, strategy_id)
    vix = regime_data.get("vix") or 0
    f   = factor.get("factors", {})
    sc  = factor.get("score", 0)

    vix_ok    = vix == 0 or vix <= 30
    factor_ok = sc >= 3
    opts_ok   = bool(candidates)

    lines = [
        f"📡 <b>{signal.upper()} {symbol} @ ${price:.2f}</b>  [{S}]",
        f"Regime: <b>{regime_data.get('regime','?')}</b> ({regime_data.get('trend','?')}) "
        f"| VIX: {vix if vix else '?'} | ATR: {regime_data.get('atr_pct','?')}%",
        "",
        "<b>Gate Results:</b>",
        f"  {T(vix_ok)} Gate 1 — VIX ≤ 30  (current: {vix})",
        f"  {T(factor_ok)} Gate 2 — Score {sc}/5  (need ≥3)",
        f"    {T(f.get('momentum'))}  Momentum  (RSI={indicators_cache.get('rsi','?')}  MACD hist={'+ ' if (indicators_cache.get('macd') or {}).get('histogram',0) > 0 else '-'})",
        f"    {T(f.get('trend'))}  Trend  (EMA fast {'&gt;' if f.get('trend') else '&lt;'} slow)",
        f"    {T(f.get('vwap'))}  VWAP  (price {'above' if f.get('vwap') else 'below'})",
        f"    {T(f.get('adx_trending'))}  ADX  (={indicators_cache.get('adx','?')}  need &gt;20)",
        f"    {T(f.get('fvg_or_sweep'))}  FVG / Sweep  ({'active' if f.get('fvg_or_sweep') else 'none'})",
    ]

    if factor_ok:
        lines.append(f"  {T(opts_ok)} Gate 3 — Options  ({len(candidates)} liquid candidates)")

    if decision:
        conf       = decision.get("confidence", 0)
        threshold  = 0.70
        claude_ok  = decision["action"] == "open" and conf >= threshold
        lines += [
            f"  {T(claude_ok)} Gate 4 — Claude  (confidence {conf:.0%}  need ≥70%)",
            f"            R:R = {decision.get('rr_ratio','?')}:1",
            f"            \"{decision.get('reasoning','')[:120].replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')}\"",
        ]

    lines += ["", f"{'🟢' if final_status == 'OPENED' else '🔴'} <b>{final_status}</b>"]
    return "\n".join(lines)


# Module-level cache so _gate_report can access current indicators
# (set at the start of each signal processing call)
indicators_cache: dict = {}


async def _process_signal_inner(symbol: str, signal: str, price: float, strategy_id: str):
    global indicators_cache

    # ── Close signal ──────────────────────────────────────────────────────────
    if signal == "close":
        await _close_trades_for_strategy(symbol, price, strategy_id)
        return

    # ── Buy / Sell — fetch market context ────────────────────────────────────
    print(f"[SIGNAL] {strategy_id} {signal.upper()} {symbol} @ {price:.2f}", flush=True)
    indicators = await asyncio.to_thread(get_all_indicators, symbol)
    indicators_cache = indicators                          # used by _gate_report
    regime_data = await asyncio.to_thread(detect_regime, symbol)
    account     = get_strategy_account(strategy_id)
    strategy    = get_active_strategy()
    print(f"[SIGNAL] Regime: {regime_data}", flush=True)

    # Pre-compute factor score so _gate_report always has it even on early exits
    factor = multi_factor_score(indicators, signal)
    candidates: list = []     # filled later if gates pass

    # ── Gate 1: VIX ──────────────────────────────────────────────────────────
    vix = regime_data.get("vix") or 0
    if vix > 30:
        print(f"[SIGNAL] ❌ Gate 1 FAILED — VIX={vix}", flush=True)
        await send_telegram(_gate_report(symbol, signal, price, strategy_id,
                                         regime_data, factor, candidates,
                                         final_status="REJECTED — VIX panic regime"))
        return

    # ── Gate 2: Multi-factor ─────────────────────────────────────────────────
    print(f"[SIGNAL] Multi-factor {factor['score']}/5 — {factor['factors']}", flush=True)
    if factor["score"] < 3:
        print(f"[SIGNAL] ❌ Gate 2 FAILED — {factor['score']}/5 factors", flush=True)
        await send_telegram(_gate_report(symbol, signal, price, strategy_id,
                                         regime_data, factor, candidates,
                                         final_status=f"REJECTED — only {factor['score']}/5 factors aligned"))
        return

    # ── Gate 3: Options candidates ───────────────────────────────────────────
    print(f"[SIGNAL] Fetching options candidates...", flush=True)
    candidates = await asyncio.to_thread(get_option_candidates, price, signal)
    print(f"[SIGNAL] {len(candidates)} candidates", flush=True)
    if not candidates:
        print("[SIGNAL] ❌ Gate 3 FAILED — no liquid options", flush=True)
        await send_telegram(_gate_report(symbol, signal, price, strategy_id,
                                         regime_data, factor, candidates,
                                         final_status="REJECTED — no liquid options available"))
        return

    # ── Gate 4: Claude ───────────────────────────────────────────────────────
    decision = await asyncio.to_thread(
        decide_options_trade, symbol, signal, indicators,
        regime_data, account, strategy, candidates, factor
    )
    print(f"[SIGNAL] Claude: action={decision['action']} confidence={decision['confidence']:.2f} "
          f"rr={decision.get('rr_ratio','?')}", flush=True)

    threshold = max(strategy.get("entry_threshold", 0.60), 0.70)
    if decision["action"] != "open" or decision["confidence"] < threshold:
        print(f"[SIGNAL] ❌ Gate 4 FAILED — confidence={decision['confidence']:.2f}", flush=True)
        await send_telegram(_gate_report(symbol, signal, price, strategy_id,
                                         regime_data, factor, candidates, decision,
                                         final_status=f"REJECTED — Claude {decision['confidence']:.0%} confidence"))
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
    side       = "long"   # always buying options (calls for buy, puts for sell)
    regime_str = regime_data.get("regime", "ranging") if isinstance(regime_data, dict) else str(regime_data)
    trade_id, msg = open_option_trade(
        symbol, side, price, candidate, decision, regime_str, strategy_id, alpaca_result
    )
    print(f"[SIGNAL] open_option_trade: trade_id={trade_id} msg={msg}", flush=True)

    if not trade_id:
        return

    g = candidate["greeks"]
    gate_summary = _gate_report(symbol, signal, price, strategy_id,
                                 regime_data, factor, candidates, decision,
                                 final_status="OPENED")
    await send_telegram(
        gate_summary + "\n\n"
        f"<b>Contract:</b> {candidate['symbol']}\n"
        f"Strike: ${candidate['strike']} | {candidate['moneyness']} | {candidate['option_type'].upper()}\n"
        f"Premium: ${alpaca_result['fill_price']:.2f} × {contracts} = ${alpaca_result['fill_price']*100*contracts:.0f}\n"
        f"IV: {candidate['iv']*100:.1f}% | Delta: {g['delta']} | Theta: ${g['theta']:.3f}/day"
    )


@router.post("/tradingview")
async def tradingview_webhook(
    payload: dict,
    background_tasks: BackgroundTasks,
    symbol: str = Query(default=None, description="Ticker override — set in webhook URL as ?symbol=SPY"),
):
    if payload.get("secret") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    raw_symbol  = payload.get("symbol", "")
    # Use URL query param when Pine Script placeholder wasn't substituted
    if symbol:
        resolved_symbol = symbol.upper()
    elif raw_symbol and "{{" not in raw_symbol:
        resolved_symbol = raw_symbol.upper()
    else:
        raise HTTPException(status_code=400, detail=f"Unresolved ticker placeholder: {raw_symbol!r}. Add ?symbol=SPY to the webhook URL.")

    symbol      = resolved_symbol
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
