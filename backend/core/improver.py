import json
import os
import anthropic
from database import get_connection

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

STRATEGY_IDS = ["ema_cross", "orb", "ema_pullback"]
STRATEGY_NAMES = {
    "ema_cross":    "EMA Cross + VWAP",
    "orb":          "Opening Range Breakout",
    "ema_pullback": "EMA 21 Pullback",
}
MIN_TRADES_TO_IMPROVE = 5  # don't improve on tiny samples


def _get_performance_stats(strategy_id: str, lookback_days: int = 7) -> dict:
    """Compute win rate, avg P&L, regime breakdown for a strategy."""
    conn = get_connection()
    trades = conn.execute("""
        SELECT t.*, j.what_worked, j.what_failed, j.market_notes
        FROM trades t
        LEFT JOIN trade_journal j ON j.trade_id = t.id
        WHERE t.strategy_id = ?
          AND t.status = 'closed'
          AND t.exit_at >= datetime('now', ? || ' days')
        ORDER BY t.exit_at DESC
    """, (strategy_id, f"-{lookback_days}")).fetchall()
    conn.close()

    trades = [dict(r) for r in trades]
    if not trades:
        return {"strategy_id": strategy_id, "sample_size": 0}

    wins   = [t for t in trades if (t["pnl"] or 0) > 0]
    losses = [t for t in trades if (t["pnl"] or 0) <= 0]

    avg_winner = round(sum(t["pnl"] for t in wins)   / len(wins),   2) if wins   else 0
    avg_loser  = round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else 0
    win_rate   = round(len(wins) / len(trades), 3)
    total_pnl  = round(sum(t["pnl"] or 0 for t in trades), 2)

    # Regime breakdown
    regime_stats = {}
    for t in trades:
        r = t.get("regime") or "unknown"
        if r not in regime_stats:
            regime_stats[r] = {"trades": 0, "wins": 0, "pnl": 0}
        regime_stats[r]["trades"] += 1
        regime_stats[r]["wins"]   += 1 if (t["pnl"] or 0) > 0 else 0
        regime_stats[r]["pnl"]    += t["pnl"] or 0

    # Recent post-mortems (last 10)
    post_mortems = []
    for t in trades[:10]:
        if t.get("what_worked") or t.get("what_failed"):
            post_mortems.append({
                "outcome":      "WIN" if (t["pnl"] or 0) > 0 else "LOSS",
                "pnl":          t["pnl"],
                "regime":       t.get("regime"),
                "what_worked":  t.get("what_worked"),
                "what_failed":  t.get("what_failed"),
                "market_notes": t.get("market_notes"),
            })

    return {
        "strategy_id":  strategy_id,
        "strategy_name": STRATEGY_NAMES.get(strategy_id, strategy_id),
        "sample_size":  len(trades),
        "win_rate":     win_rate,
        "total_pnl":    total_pnl,
        "avg_winner":   avg_winner,
        "avg_loser":    avg_loser,
        "regime_stats": regime_stats,
        "post_mortems": post_mortems,
    }


def _get_current_rules() -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT version, rules FROM strategy_versions WHERE is_active=1"
    ).fetchone()
    conn.close()
    return {"version": row["version"], "rules": json.loads(row["rules"])} if row else {}


def _ask_claude_for_improvements(all_stats: list, current_rules: dict) -> dict:
    """Feed performance data to Claude and get updated strategy rules."""
    prompt = f"""You are a quantitative trading analyst reviewing a paper trading bot's weekly performance.

Your job: analyze performance across 3 strategies and suggest parameter improvements to the shared strategy rules.

CURRENT ACTIVE RULES (version {current_rules.get('version', 1)}):
{json.dumps(current_rules.get('rules', {}), indent=2)}

WEEKLY PERFORMANCE BY STRATEGY:
{json.dumps(all_stats, indent=2)}

PARAMETERS YOU CAN ADJUST:
- entry_threshold (0.50–0.80): how selective Claude is. Raise if too many losses, lower if missing good trades.
- position_size_pct (0.05–0.20): position sizing as % of account balance.
- stop_loss_pct (0.01–0.05): stop loss distance as % of entry price.
- take_profit_pct (0.02–0.08): take profit distance as % of entry price.
- indicator weights (rsi, macd, ema_cross, vwap, bollinger): must sum to 1.0.
- regime_filters: which indicators to use in trending/ranging/volatile markets.

RULES FOR YOUR RESPONSE:
1. Only suggest changes supported by the data. If sample size < {MIN_TRADES_TO_IMPROVE} for a strategy, note it but don't over-optimize.
2. Be conservative — small adjustments (±0.05 on thresholds, ±0.01 on pcts).
3. If win rate > 60% and avg_winner > abs(avg_loser), the strategy is working — don't over-tune.
4. If win rate < 40%, raise entry_threshold first before touching other params.

Respond ONLY with valid JSON (no markdown, no text outside JSON):
{{
  "updated_rules": {{ ... complete updated rules JSON ... }},
  "rationale": "2-3 sentence summary of what changed and why",
  "changes": [
    {{"parameter": "entry_threshold", "old": 0.60, "new": 0.65, "reason": "win rate below 40%"}}
  ],
  "skip_reason": null
}}

If no changes are warranted, set "changes" to [] and explain in "rationale". Set "skip_reason" to a string if you're skipping due to insufficient data."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text.strip()
    try:
        return json.loads(text)
    except Exception:
        return {
            "updated_rules": current_rules.get("rules", {}),
            "rationale": f"JSON parse error from Claude: {text[:200]}",
            "changes": [],
            "skip_reason": "parse_error"
        }


def _save_new_version(updated_rules: dict, rationale: str, all_stats: list) -> int:
    """Save new strategy version and mark it active."""
    conn = get_connection()

    # Deactivate current version
    conn.execute("UPDATE strategy_versions SET is_active=0")

    # Compute aggregate stats for record
    total_trades = sum(s.get("sample_size", 0) for s in all_stats)
    all_wins     = [s for s in all_stats if s.get("sample_size", 0) > 0]
    avg_wr       = round(sum(s.get("win_rate", 0) for s in all_wins) / len(all_wins), 3) if all_wins else None
    avg_winner   = round(sum(s.get("avg_winner", 0) for s in all_wins) / len(all_wins), 2) if all_wins else None
    avg_loser    = round(sum(s.get("avg_loser", 0)  for s in all_wins) / len(all_wins), 2) if all_wins else None

    next_ver = (conn.execute("SELECT MAX(version) as v FROM strategy_versions").fetchone()["v"] or 0) + 1

    conn.execute("""
        INSERT INTO strategy_versions
            (version, rules, rationale, win_rate, avg_winner, avg_loser, sample_size, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
    """, (next_ver, json.dumps(updated_rules), rationale, avg_wr, avg_winner, avg_loser, total_trades))

    conn.commit()
    conn.close()
    return next_ver


def run_improvement_cycle(lookback_days: int = 7) -> dict:
    """
    Full self-improvement cycle. Returns a summary dict.
    Called weekly by APScheduler or manually via /improve/run.
    """
    print("[IMPROVE] Starting self-improvement cycle...", flush=True)

    # 1. Gather performance stats per strategy
    all_stats = [_get_performance_stats(sid, lookback_days) for sid in STRATEGY_IDS]
    total_trades = sum(s.get("sample_size", 0) for s in all_stats)

    print(f"[IMPROVE] Analyzed {total_trades} trades across {len(STRATEGY_IDS)} strategies", flush=True)

    if total_trades < MIN_TRADES_TO_IMPROVE:
        print(f"[IMPROVE] Skipping — only {total_trades} trades (min {MIN_TRADES_TO_IMPROVE})", flush=True)
        return {
            "status": "skipped",
            "reason": f"Only {total_trades} closed trades in the last {lookback_days} days. Minimum is {MIN_TRADES_TO_IMPROVE}.",
            "stats":  all_stats,
        }

    # 2. Get current rules
    current_rules = _get_current_rules()
    print(f"[IMPROVE] Current strategy version: {current_rules.get('version')}", flush=True)

    # 3. Ask Claude for improvements
    result = _ask_claude_for_improvements(all_stats, current_rules)
    print(f"[IMPROVE] Claude rationale: {result.get('rationale', '')[:120]}", flush=True)

    if result.get("skip_reason"):
        return {
            "status":      "skipped",
            "reason":      result["skip_reason"],
            "rationale":   result.get("rationale"),
            "stats":       all_stats,
        }

    # 4. Save new version
    new_ver = _save_new_version(result["updated_rules"], result["rationale"], all_stats)
    print(f"[IMPROVE] Saved strategy version {new_ver}", flush=True)

    return {
        "status":       "improved",
        "new_version":  new_ver,
        "rationale":    result["rationale"],
        "changes":      result.get("changes", []),
        "stats":        all_stats,
        "updated_rules": result["updated_rules"],
    }
