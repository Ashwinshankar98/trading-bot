# Trading Bot

An AI-powered paper trading bot with self-improvement capabilities.

## Stack
- **Backend**: FastAPI (Python) — hosted on Render
- **Database**: SQLite (local) → Supabase (production)
- **Dashboard**: React — hosted on Vercel
- **LLM**: Claude Sonnet 4 (reasoning + weekly strategy review)
- **Alerts**: Telegram
- **Data**: yfinance / TradingView webhooks

## Project Structure
```
trading-bot/
├── backend/
│   ├── main.py              # FastAPI app entry point
│   ├── database.py          # DB connection + table setup
│   ├── core/
│   │   ├── paper_trader.py  # Virtual $10k account logic
│   │   ├── indicators.py    # RSI, MACD, EMA, VWAP, etc.
│   │   ├── regime.py        # Market regime detection
│   │   └── llm.py           # Claude reasoning layer
│   ├── routers/
│   │   ├── webhook.py       # TradingView webhook receiver
│   │   ├── trades.py        # Trade history endpoints
│   │   └── strategy.py      # Strategy version endpoints
│   └── models/
│       └── schemas.py       # Pydantic models
├── frontend/                # React dashboard (Step 9)
├── scripts/
│   └── weekly_review.py     # Self-improvement cron job
├── requirements.txt
├── render.yaml              # Render deployment config
└── .env.example
```

## Setup

### 1. Clone and install
```bash
git clone <your-repo-url>
cd trading-bot
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Fill in your API keys in .env
```

### 3. Run locally
```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 4. Visit
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health
