import os
from datetime import date
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

load_dotenv()

from database import init_db, get_connection
from routers import webhook, trades, strategy, improve
from routers.improve import run_weekly_review
from core.improver import run_improvement_cycle
from core.paper_trader import close_option_trade

app = FastAPI(
    title="Trading Bot API",
    description="AI-powered paper trading bot with self-improvement",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "https://trading-bot-three-blond.vercel.app",
    "http://localhost:5173",
    ],   # tighten this once dashboard URL is known
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router)
app.include_router(trades.router)
app.include_router(strategy.router)
app.include_router(improve.router)

scheduler = AsyncIOScheduler()


async def eod_force_close():
    """
    Force-close any open option trades whose expiry is today or earlier.
    Runs at 3:50 PM ET — options stop trading at 4 PM, so exit premium = 0
    for expired positions (they become worthless or were exercised by broker).
    """
    today = date.today().isoformat()
    conn  = get_connection()
    expiring = conn.execute("""
        SELECT id, option_symbol, option_expiry, entry_premium, contracts, strategy_id
        FROM trades
        WHERE status = 'open'
          AND asset_class = 'option'
          AND option_expiry <= ?
    """, (today,)).fetchall()
    conn.close()

    if not expiring:
        print("[EOD] No expiring options to force-close", flush=True)
        return

    from routers.webhook import send_telegram, STRATEGY_NAMES
    for row in expiring:
        trade = dict(row)
        print(f"[EOD] Force-closing expired option trade id={trade['id']} {trade['option_symbol']}", flush=True)
        # Try to get current market quote first; fall back to 0 if unavailable
        exit_premium = 0.0
        try:
            from core.options import get_current_option_quote
            quote = get_current_option_quote(trade["option_symbol"])
            if quote and quote > 0:
                exit_premium = quote
        except Exception:
            pass

        pnl, msg = close_option_trade(trade["id"], exit_premium)
        S = STRATEGY_NAMES.get(trade["strategy_id"], trade["strategy_id"])
        await send_telegram(
            f"⏰ <b>EOD FORCE-CLOSE</b>\n"
            f"Strategy: {S}\n"
            f"Option: {trade['option_symbol']} (expired {trade['option_expiry']})\n"
            f"Exit premium: ${exit_premium:.2f} | PnL: ${pnl:.2f}"
        )
        print(f"[EOD] Closed id={trade['id']} pnl={pnl}", flush=True)


@app.on_event("startup")
async def startup():
    init_db()

    # Weekly self-improvement: every Monday at 9:00 AM ET
    scheduler.add_job(
        run_improvement_cycle,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="America/New_York"),
        id="weekly_improvement",
        replace_existing=True,
    )

    # Daily EOD force-close: 3:50 PM ET — catches any options expiring today
    scheduler.add_job(
        eod_force_close,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=50, timezone="America/New_York"),
        id="eod_force_close",
        replace_existing=True,
    )

    # Weekly trade review: every Friday at 4:30 PM ET — diagnose the week, no auto-changes
    scheduler.add_job(
        run_weekly_review,
        CronTrigger(day_of_week="fri", hour=16, minute=30, timezone="America/New_York"),
        id="weekly_review",
        replace_existing=True,
    )

    scheduler.start()
    print("[App] Trading bot started")
    print("[App] Schedulers: weekly improvement (Mon 9 AM ET), EOD force-close (3:50 PM ET), weekly review (Fri 4:30 PM ET)")

@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok", "version": "1.0.0"}

@app.get("/")
def root():
    return {
        "message": "Trading Bot API",
        "docs": "/docs",
        "health": "/health"
    }
