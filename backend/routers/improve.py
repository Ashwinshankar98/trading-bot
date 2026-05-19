import json
import os
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
