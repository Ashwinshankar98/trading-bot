import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from database import init_db
from routers import webhook, trades, strategy

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

@app.on_event("startup")
def startup():
    init_db()
    print("[App] Trading bot started")

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}

@app.get("/")
def root():
    return {
        "message": "Trading Bot API",
        "docs": "/docs",
        "health": "/health"
    }
