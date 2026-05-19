import os, json
import anthropic

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def decide_trade(symbol: str, signal: str, indicators: dict,
                 regime: str, account: dict, strategy: dict) -> dict:
    """
    Ask Claude whether to act on a signal given current market context.
    Returns: { "action": "open"|"skip", "side": "long"|"short"|None,
                "confidence": 0-1, "reasoning": str }
    """
    prompt = f"""You are a disciplined algorithmic trading assistant managing a paper trading account.

Current market context:
- Symbol: {symbol}
- Signal received: {signal}
- Market regime: {regime}
- Indicators: {json.dumps(indicators, indent=2)}

Account status:
- Balance: ${account['balance']:.2f}
- Equity:  ${account['equity']:.2f}
- Starting balance was $10,000

Active strategy rules:
{json.dumps(strategy, indent=2)}

Your job: Decide whether to open a trade based on the signal and context.

Rules:
1. Only trade if the signal aligns with the regime filter in the strategy.
2. Skip if regime is 'volatile' unless the strategy explicitly allows it.
3. Consider indicator confluence — more indicators agreeing = higher confidence.
4. Be conservative — it is better to miss a trade than take a bad one.

Respond ONLY with valid JSON (no markdown, no explanation outside JSON):
{{
  "action": "open" or "skip",
  "side": "long" or "short" or null,
  "confidence": 0.0 to 1.0,
  "reasoning": "one concise paragraph explaining your decision"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text.strip()
    try:
        return json.loads(text)
    except Exception:
        return {"action": "skip", "side": None, "confidence": 0.0,
                "reasoning": f"JSON parse error: {text[:200]}"}

def decide_options_trade(
    symbol: str, signal: str, indicators: dict, regime: str,
    account: dict, strategy: dict, candidates: list
) -> dict:
    """
    Claude evaluates option candidates using Greeks + spread + market context.
    Returns: { action, chosen_contract, contracts, confidence, reasoning }
    """
    balance = account.get("balance", 10000)
    max_risk = balance * strategy.get("max_option_risk_pct", 0.05)

    candidates_text = ""
    for i, c in enumerate(candidates, 1):
        g = c["greeks"]
        candidates_text += f"""
  Contract {i}: {c['symbol']}
    Moneyness    : {c['moneyness']} | Strike: ${c['strike']}
    Bid/Ask      : ${c['bid']} / ${c['ask']} | Spread: {c['spread_pct']*100:.1f}% of mid
    Mid premium  : ${c['mid']} | Cost per contract: ${c['cost_per_contract']}
    IV           : {c['iv']*100:.1f}%
    Delta        : {g['delta']}  (${abs(g['delta'])*100:.1f} P&L per $1 SPY move)
    Gamma        : {g['gamma']}
    Theta        : ${g['theta']:.3f}/day  (time decay cost per day)
    Vega         : ${g['vega']:.3f}/1% IV move
    Expiry       : {c['expiry']}
"""

    prompt = f"""You are an expert options trader managing a paper trading account.
A TradingView signal just fired. Decide whether to buy an options contract and which one.

SIGNAL: {signal.upper()} on {symbol}
MARKET REGIME: {regime}
INDICATORS: {json.dumps(indicators, indent=2)}

ACCOUNT:
- Balance: ${balance:.2f}
- Max risk per trade: ${max_risk:.2f} (5% of balance)

OPTION CANDIDATES ({len(candidates)} ATM contracts, filtered for tight spreads):
{candidates_text}

DECISION FRAMEWORK:
1. SPREAD: Skip any contract where spread > 20% of mid — you lose edge before you start.
2. THETA: For 0DTE (today's expiry), theta is brutal. Only enter if signal is very strong (confidence > 0.75).
3. DELTA: ATM (~0.50 delta) gives balanced leverage. Only go deeper OTM if you expect a large move.
4. IV: If IV > 40%, options are expensive — size down or skip.
5. CONTRACTS: Max risk = ${max_risk:.2f}. Contracts = floor(max_risk / cost_per_contract). Min 1, max 5.
6. SIGNAL ALIGNMENT: 'buy' signal → calls. 'sell' signal → puts. Never fight the signal direction.
7. REGIME: In 'volatile' regime, skip unless IV is already elevated and you expect a breakout.

Respond ONLY with valid JSON (no markdown):
{{
  "action": "open" or "skip",
  "chosen_contract": "{candidates[0]['symbol'] if candidates else ''}" or null,
  "contracts": 1,
  "confidence": 0.0 to 1.0,
  "reasoning": "concise paragraph covering: why this contract, spread assessment, theta risk, how many contracts and why"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.content[0].text.strip()
    try:
        return json.loads(text)
    except Exception:
        return {"action": "skip", "chosen_contract": None, "contracts": 0,
                "confidence": 0.0, "reasoning": f"JSON parse error: {text[:200]}"}


def write_post_mortem(trade: dict, indicators_at_entry: dict) -> dict:
    """After a trade closes, ask Claude to write a post-mortem."""
    outcome = "WIN" if (trade.get("pnl") or 0) > 0 else "LOSS"
    prompt = f"""A paper trade just closed. Write a brief post-mortem.

Trade details:
- Symbol: {trade['symbol']}
- Side: {trade['side']}
- Entry: ${trade['entry_price']} → Exit: ${trade.get('exit_price', 'N/A')}
- PnL: ${trade.get('pnl', 0):.2f} ({trade.get('pnl_pct', 0):.1f}%)
- Outcome: {outcome}
- Regime at entry: {trade.get('regime', 'unknown')}
- Indicators at entry: {json.dumps(indicators_at_entry, indent=2)}
- Original reasoning: {trade.get('llm_reasoning', 'N/A')}

Respond ONLY with valid JSON:
{{
  "what_worked": "what went right (or N/A if loss)",
  "what_failed": "what went wrong (or N/A if win)",
  "market_notes": "brief observation about market conditions"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.content[0].text.strip()
    try:
        return json.loads(text)
    except Exception:
        return {"what_worked": "N/A", "what_failed": text[:200], "market_notes": ""}
