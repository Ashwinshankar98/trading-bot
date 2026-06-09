import json
import os
import re
import anthropic
import httpx
from fastapi import APIRouter, BackgroundTasks
from core.improver import run_improvement_cycle
from database import get_connection

router = APIRouter(prefix="/improve", tags=["improve"])


async def _send_telegram(message: str):
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"})


async def _run_and_notify(lookback_days: int = 7):
    result = run_improvement_cycle(lookback_days)

    if result["status"] == "skipped":
        await _send_telegram(
            f"🤖 <b>Self-Improvement: Skipped</b>\n"
            f"Reason: {result['reason']}"
        )
        return

    changes = result.get("changes", [])
    changes_text = "\n".join(
        f"  • {c['parameter']}: {c['old']} → {c['new']} ({c['reason']})"
        for c in changes
    ) if changes else "  • No parameter changes"

    stats_lines = []
    for s in result.get("stats", []):
        if s.get("sample_size", 0) > 0:
            stats_lines.append(
                f"  {s['strategy_name']}: {s['sample_size']} trades, "
                f"{s['win_rate']*100:.0f}% WR, ${s['total_pnl']:.2f} P&L"
            )

    await _send_telegram(
        f"🧠 <b>Strategy Updated → v{result['new_version']}</b>\n\n"
        f"<b>Performance this week:</b>\n" +
        ("\n".join(stats_lines) or "  No data") +
        f"\n\n<b>Changes:</b>\n{changes_text}\n\n"
        f"<b>Rationale:</b> {result['rationale']}"
    )


@router.post("/run")
async def trigger_improvement(background_tasks: BackgroundTasks, lookback_days: int = 7):
    """Manually trigger the self-improvement cycle."""
    background_tasks.add_task(_run_and_notify, lookback_days)
    return {"status": "started", "lookback_days": lookback_days}


@router.get("/history")
def improvement_history():
    """Return all strategy versions."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM strategy_versions ORDER BY version DESC"
    ).fetchall()
    conn.close()
    return [
        {
            **dict(r),
            "rules": json.loads(r["rules"])
        }
        for r in rows
    ]


@router.get("/current")
def current_strategy():
    """Return the currently active strategy rules."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM strategy_versions WHERE is_active=1"
    ).fetchone()
    conn.close()
    if not row:
        return {"error": "no active strategy"}
    return {**dict(row), "rules": json.loads(row["rules"])}


# ─── Weekly trade review (read-only, no auto-changes) ────────────────────────

def _get_review_trades(lookback_days: int) -> list:
    conn = get_connection()
    rows = conn.execute("""
        SELECT t.*, j.what_worked, j.what_failed, j.market_notes
        FROM trades t
        LEFT JOIN trade_journal j ON j.trade_id = t.id
        WHERE t.status = 'closed'
          AND t.exit_at >= datetime('now', ? || ' days')
        ORDER BY t.entry_at ASC
    """, (f"-{lookback_days}",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _compute_patterns(trades: list) -> dict:
    wins   = [t for t in trades if (t.get("pnl") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl") or 0) <= 0]

    # Max consecutive loss streak
    max_streak = cur = 0
    for t in trades:
        if (t.get("pnl") or 0) <= 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0

    def avg(lst, key):
        vals = [json.loads(t.get("indicators") or "{}").get(key)
                for t in lst if json.loads(t.get("indicators") or "{}").get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    return {
        "total": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(trades), 3) if trades else 0,
        "total_pnl": round(sum(t.get("pnl") or 0 for t in trades), 2),
        "max_consecutive_losses": max_streak,
        "avg_iv_wins":    avg(wins,   "iv"),
        "avg_iv_losses":  avg(losses, "iv"),
    }


def _claude_review(trades: list, patterns: dict) -> dict:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    lines = []
    for t in trades:
        ind = json.loads(t.get("indicators") or "{}")
        pnl = t.get("pnl") or 0
        lines.append(
            f"  [{'WIN' if pnl > 0 else 'LOSS'}] {t['strategy_id']} "
            f"{(t.get('option_type') or '?').upper()} "
            f"entry={t.get('entry_premium','?')} exit={t.get('exit_premium','?')} "
            f"PnL=${pnl:.0f} IV={ind.get('iv','?')} "
            f"at={t['entry_at'][:16]} "
            f"| failed: {(t.get('what_failed') or 'N/A')[:80]}"
        )

    prompt = f"""You are reviewing a paper trading bot's recent options trades.
Diagnose what went wrong and suggest improvements. Do NOT apply changes — the human decides.

STATS:
{json.dumps(patterns, indent=2)}

TRADES (chronological):
{chr(10).join(lines)}

Answer:
1. What patterns do losing trades share? (RSI, RVOL, timing, streak structure)
2. What made winners different?
3. Was this a market-driven reversal or a repeatable system flaw?
4. Give 2-3 specific, measurable suggestions the human can choose to implement.

Respond ONLY with valid JSON (no markdown):
{{
  "loss_patterns": "paragraph",
  "win_patterns": "paragraph",
  "market_assessment": "paragraph",
  "suggestions": [
    {{"change": "what", "current_value": "x", "suggested_value": "y", "expected_impact": "..."}}
  ]
}}"""

    resp = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.content[0].text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text.strip())
    return json.loads(text.strip())


async def run_weekly_review(lookback_days: int = 7):
    print(f"[REVIEW] Starting weekly review ({lookback_days}d)", flush=True)
    trades = _get_review_trades(lookback_days)
    if len(trades) < 3:
        await _send_telegram(f"📊 <b>Weekly Review</b>\nNot enough trades ({len(trades)}) to review.")
        return {"status": "skipped", "reason": f"only {len(trades)} trades"}

    patterns = _compute_patterns(trades)
    analysis = _claude_review(trades, patterns)

    suggestions = analysis.get("suggestions", [])
    sug_lines   = "\n".join(
        f"  • <b>{s['change']}</b>: {s.get('current_value','?')} → {s.get('suggested_value','?')}\n"
        f"    {s.get('expected_impact','')}"
        for s in suggestions
    ) or "  None"

    msg = (
        f"📊 <b>Weekly Review — last {lookback_days} days</b>\n"
        f"Trades: {patterns['total']} | WR: {patterns['win_rate']*100:.0f}% | "
        f"P&amp;L: ${patterns['total_pnl']:.2f} | Max loss streak: {patterns['max_consecutive_losses']}\n\n"
        f"<b>Loss patterns:</b>\n{analysis.get('loss_patterns','')[:400]}\n\n"
        f"<b>Win patterns:</b>\n{analysis.get('win_patterns','')[:300]}\n\n"
        f"<b>Market assessment:</b>\n{analysis.get('market_assessment','')[:300]}\n\n"
        f"<b>Suggestions (you decide):</b>\n{sug_lines}\n\n"
        f"Nothing was changed. Reply to act on a suggestion."
    )
    await _send_telegram(msg)
    print("[REVIEW] Done", flush=True)
    return {"status": "ok", "patterns": patterns, "analysis": analysis}


@router.post("/review")
async def trigger_review(background_tasks: BackgroundTasks, lookback_days: int = 7):
    """Manually trigger the weekly trade review (read-only, no parameter changes)."""
    background_tasks.add_task(run_weekly_review, lookback_days)
    return {"status": "started", "lookback_days": lookback_days}
