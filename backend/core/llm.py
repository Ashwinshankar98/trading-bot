import os, json
import anthropic

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Cached system prompt — hedge fund quant persona (slide 1, 3, 8)
_OPTIONS_SYSTEM = """\
You are a hedge fund quantitative options trader. Capital preservation is your first mandate.

ENTRY CRITERIA — every condition must be satisfied to open a trade:
1. Signal direction aligns with macro trend. No calls in bear trend; no puts in bull trend unless volatility regime.
2. Minimum reward-to-risk = 3:1 (stop = -50% of premium, target = +150% of premium).
3. IV < 45% — expensive options erode edge before the move happens.
4. Bid-ask spread < 15% of mid — wide spread is a guaranteed loss at entry.
5. Confidence ≥ 0.70 — skip marginal setups; missing a trade costs nothing.
6. Multi-factor score ≥ 2/4 (momentum, trend, VWAP, ADX must mostly agree).

SIZING RULES:
- Max risk per trade = 5% of account balance.
- Contracts = floor(max_risk / (mid_premium × 100)). Min 1, max 5.

SKIP IMMEDIATELY IF:
- VIX > 30 (panic regime, options pricing is unreliable).
- Signal direction contradicts the macro trend.
- Fewer than 2 factors are aligned.
- Only 0DTE available and confidence < 0.80 (theta kills marginal plays).\
"""


def decide_trade(symbol: str, signal: str, indicators: dict,
                 regime_data: dict, account: dict, strategy: dict) -> dict:
    """
    Decide whether to act on a stock signal. Returns action/side/confidence/reasoning.
    regime_data: rich dict from detect_regime() (has .regime, .trend, .vix, etc.)
    """
    regime_str = regime_data.get("regime", "ranging") if isinstance(regime_data, dict) else str(regime_data)
    trend      = regime_data.get("trend", "sideways")  if isinstance(regime_data, dict) else "sideways"
    vix        = regime_data.get("vix")                if isinstance(regime_data, dict) else None

    prompt = f"""Market snapshot:
Symbol: {symbol} | Signal: {signal.upper()} | Regime: {regime_str} | Trend: {trend}
VIX: {vix} | ADX: {regime_data.get("adx") if isinstance(regime_data, dict) else "N/A"}

Account: ${account['balance']:.0f} | Equity: ${account['equity']:.0f}

Indicators:
{json.dumps(indicators, indent=2)}

Strategy rules:
{json.dumps(strategy, indent=2)}

Should I open a trade? Apply the hedge fund entry criteria.
Respond ONLY with valid JSON:
{{"action":"open" or "skip","side":"long" or "short" or null,"confidence":0.0-1.0,"reasoning":"concise paragraph"}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.content[0].text.strip()
    try:
        return json.loads(text)
    except Exception:
        return {"action": "skip", "side": None, "confidence": 0.0,
                "reasoning": f"JSON parse error: {text[:200]}"}


def decide_options_trade(
    symbol: str, signal: str, indicators: dict, regime_data: dict,
    account: dict, strategy: dict, candidates: list,
    factor_score: dict = None
) -> dict:
    """
    Hedge-fund-quality options decision engine (slides 1, 3, 4, 5, 8, 11).
    Uses prompt caching on the system message for token efficiency.
    regime_data: rich dict from detect_regime() (has trend, vix, tnx_10yr, etc.)
    factor_score: multi_factor_score() result dict.
    Returns: {action, chosen_contract, contracts, confidence, rr_ratio, reasoning}
    """
    if isinstance(regime_data, dict):
        regime_str  = regime_data.get("regime", "ranging")
        trend       = regime_data.get("trend", "sideways")
        vol_level   = regime_data.get("volatility", "medium")
        vol_label   = regime_data.get("volume", "normal")
        adx_val     = regime_data.get("adx")
        atr_pct     = regime_data.get("atr_pct")
        vix         = regime_data.get("vix")
        tnx         = regime_data.get("tnx_10yr")
        recommended = regime_data.get("recommended_strategies", [])
        avoid       = regime_data.get("avoid", [])
    else:
        regime_str  = str(regime_data)
        trend = vol_level = vol_label = "unknown"
        adx_val = atr_pct = vix = tnx = None
        recommended = avoid = []

    balance  = account.get("balance", 10000)
    max_risk = balance * strategy.get("max_option_risk_pct", 0.05)

    # Compact candidate summary
    cand_lines = []
    for i, c in enumerate(candidates, 1):
        g = c.get("greeks", {})
        cand_lines.append(
            f"  [{i}] {c['symbol']} | {c['moneyness']} {c['option_type'].upper()} "
            f"${c['strike']} exp {c['expiry']} | "
            f"mid ${c['mid']:.2f} spread {c['spread_pct']*100:.1f}% | "
            f"IV {c.get('iv',0)*100:.1f}% delta {g.get('delta','?')} "
            f"theta ${g.get('theta',0):.3f}/day | "
            f"cost/contract ${c['cost_per_contract']:.0f}"
        )
    candidates_text = "\n".join(cand_lines)

    fs = factor_score or {}
    factor_summary = (
        f"{fs.get('score',0)}/5 aligned "
        f"(momentum={fs.get('factors',{}).get('momentum')}, "
        f"trend={fs.get('factors',{}).get('trend')}, "
        f"vwap={fs.get('factors',{}).get('vwap')}, "
        f"adx={fs.get('factors',{}).get('adx_trending')}, "
        f"fvg_sweep={fs.get('factors',{}).get('fvg_or_sweep')})"
    )

    prompt = f"""Signal: {signal.upper()} on {symbol}

MARKET REGIME (slide 4):
  Regime: {regime_str} | Trend: {trend} | Volatility: {vol_level} | Volume: {vol_label}
  ADX: {adx_val} | ATR%: {atr_pct}% | VIX: {vix} | 10-yr: {tnx}%
  Recommended strategies: {recommended}
  Avoid: {avoid}

MULTI-FACTOR SCORE (slide 5): {factor_summary}

TECHNICALS:
  RSI: {indicators.get('rsi')} | MACD histogram: {(indicators.get('macd') or {}).get('histogram')}
  EMA fast/slow: {(indicators.get('ema_cross') or {}).get('ema_fast')}/{(indicators.get('ema_cross') or {}).get('ema_slow')}
  VWAP: {indicators.get('vwap')} | Price: {indicators.get('price')}
  Bollinger %B: {(indicators.get('bollinger') or {}).get('pct_b')}
  RVOL: {indicators.get('rvol')} (1h bars vs 20-bar avg; >1.5 = conviction)

SMC STRUCTURE (1h timeframe):
  Fair Value Gaps — Bullish (support below): {(indicators.get('fvg') or {}).get('bullish')}
  Fair Value Gaps — Bearish (resistance above): {(indicators.get('fvg') or {}).get('bearish')}
  Liquidity Sweep: bull_sweep={((indicators.get('sweep') or {})).get('bull_sweep')} bear_sweep={((indicators.get('sweep') or {})).get('bear_sweep')} level={((indicators.get('sweep') or {})).get('level')} bars_ago={((indicators.get('sweep') or {})).get('bars_ago')}
  (Bull sweep = smart money hunted stops below a swing low → expect upside; Bear sweep = inverse)

ACCOUNT: ${balance:.0f} | Max risk per trade: ${max_risk:.0f}

OPTION CANDIDATES:
{candidates_text}

RISK-REWARD (slide 3): Stop = -50% premium, Target = +150% premium → 3:1 R:R.
Compute cost and max risk for each contract. Only proceed if all entry criteria met.

Respond ONLY with valid JSON (no markdown):
{{
  "action": "open" or "skip",
  "chosen_contract": "OCC symbol or null",
  "contracts": 1,
  "confidence": 0.0-1.0,
  "rr_ratio": 3.0,
  "reasoning": "concise paragraph: why this setup, spread/IV/theta assessment, macro context, what could break it"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=[{"type": "text", "text": _OPTIONS_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.content[0].text.strip()
    try:
        return json.loads(text)
    except Exception:
        return {"action": "skip", "chosen_contract": None, "contracts": 0,
                "confidence": 0.0, "rr_ratio": 0.0,
                "reasoning": f"JSON parse error: {text[:200]}"}


def write_post_mortem(trade: dict, indicators_at_entry: dict) -> dict:
    """After a trade closes, write a brief post-mortem. Uses prompt caching."""
    outcome = "WIN" if (trade.get("pnl") or 0) > 0 else "LOSS"
    prompt = f"""Trade closed ({outcome}):
{trade['symbol']} | {trade['side']} | Entry ${trade['entry_price']} → Exit ${trade.get('exit_price','?')}
PnL: ${trade.get('pnl',0):.2f} ({trade.get('pnl_pct',0):.1f}%) | Regime: {trade.get('regime','?')}
Original reasoning: {trade.get('llm_reasoning','N/A')}

Respond ONLY with valid JSON:
{{"what_worked":"...","what_failed":"...","market_notes":"..."}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.content[0].text.strip()
    try:
        return json.loads(text)
    except Exception:
        return {"what_worked": "N/A", "what_failed": text[:200], "market_notes": ""}
