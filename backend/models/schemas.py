from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class WebhookPayload(BaseModel):
    secret: str
    symbol: str
    signal: str          # "buy" | "sell" | "close"
    price: float
    indicators: Optional[dict] = {}
    timeframe: Optional[str] = "1h"

class TradeOut(BaseModel):
    id: int
    symbol: str
    side: str
    status: str
    entry_price: float
    exit_price: Optional[float]
    quantity: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    pnl: Optional[float]
    pnl_pct: Optional[float]
    entry_at: str
    exit_at: Optional[str]
    strategy_ver: int
    llm_reasoning: Optional[str]
    regime: Optional[str]

class AccountOut(BaseModel):
    balance: float
    equity: float
    open_pnl: float
    total_pnl: float
    win_rate: float
    total_trades: int
    updated_at: str

class StrategyVersionOut(BaseModel):
    version: int
    rules: str
    rationale: Optional[str]
    win_rate: Optional[float]
    sample_size: Optional[int]
    created_at: str
    is_active: bool
