import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

load_dotenv()

from database import init_db
from routers import webhook, trades, strategy, improve
from core.improver import run_improvement_cycle

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
    scheduler.start()
    print("[App] Trading bot started")
    print("[App] Self-improvement scheduler running (Mondays 9 AM ET)")

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
