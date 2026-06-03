# Trading Bot

An AI-powered paper trading bot that receives TradingView signals, runs them through a multi-stage quality filter, and uses Claude as a hedge fund quant to decide whether to execute options trades.

## Stack

| Layer | Tech |
|-------|------|
| Backend API | FastAPI (Python) — hosted on Render |
| Database | SQLite (local) → Supabase (production) |
| Dashboard | React — hosted on Vercel |
| AI Brain | Claude Sonnet 4.6 (trade decisions + weekly self-improvement) |
| Alerts | Telegram |
| Market Data | yfinance + TradingView webhooks |
| Options Execution | Alpaca paper trading API |

---

## How It Works — The Full Pipeline

```
TradingView Alert
      │
      ▼
POST /webhook/tradingview
      │
      ├─ [1] Log signal to DB immediately → return 200 to TradingView
      │
      └─ Background task starts:
            │
            ├─ Fetch live indicators (RSI, MACD, EMA cross, VWAP, Bollinger, ADX, ATR)
            │
            ├─ Detect market regime → trend + volatility + volume + VIX + 10-yr yield
            │
            ├─ GATE 1: VIX > 30? → SKIP (panic market, options pricing unreliable)
            │
            ├─ GATE 2: Multi-factor score < 2/4? → SKIP (momentum + trend + VWAP + ADX)
            │
            ├─ Fetch live ATM options candidates from Alpaca
            │
            ├─ CLAUDE (hedge fund quant mode):
            │     - Reviews all 4 regime dimensions
            │     - Reviews macro context (VIX, 10-yr yield)
            │     - Reviews 4-factor alignment score
            │     - Reviews each option's greeks (delta, theta, IV, spread)
            │     - Enforces 3:1 reward-to-risk (stop = -50% premium, target = +150%)
            │     - Returns: action, contract, contracts, confidence, rr_ratio, reasoning
            │
            ├─ GATE 3: Confidence < 0.70? → SKIP
            │
            ├─ Submit buy order to Alpaca
            │
            ├─ Record trade in DB with full context
            │
            └─ Send Telegram alert
```

### What "Signals" Are

You set up strategies in TradingView (EMA Cross, ORB, EMA Pullback). Each strategy fires an alert when its conditions trigger. That alert hits the webhook with:
```json
{
  "secret": "your-secret",
  "symbol": "SPY",
  "signal": "buy",
  "price": 548.20,
  "strategy": "ema_cross"
}
```

Claude does **not** generate the signal — TradingView does. Claude's job is to **decide whether the signal is worth acting on** given the current market context.

---

## Quality Gates (What's New)

Before Claude is even called, two hard gates filter out low-quality signals:

### Gate 1 — VIX Gate
If the VIX (fear index) is above 30, the whole signal is dropped. In panic markets, options premiums are inflated and directional plays fail.

### Gate 2 — Multi-Factor Score (≥ 2/4 required)
Four technical factors are scored and the signal must get at least 2/4:

| Factor | Long (buy) condition | Short (sell) condition |
|--------|---------------------|----------------------|
| Momentum | RSI 40–70 AND MACD histogram > 0 | RSI 30–60 AND MACD histogram < 0 |
| Trend | EMA fast > EMA slow | EMA fast < EMA slow |
| VWAP | Price above VWAP | Price below VWAP |
| ADX | ADX > 20 (market is trending, not choppy) | ADX > 20 |

If fewer than 2 pass → signal is skipped without calling Claude (saves tokens, blocks bad trades).

### Gate 3 — Confidence Threshold (≥ 0.70)
Claude's confidence score must be 0.70 or higher. Previously this was 0.60. Missing good trades is better than taking bad ones.

---

## Market Regime Detection

Every signal now triggers a full market regime analysis before Claude is called:

```json
{
  "regime":    "trending | ranging | volatile",
  "trend":     "bull | bear | sideways",
  "volatility": "low | medium | high",
  "volume":    "above_avg | normal | below_avg",
  "vix":       18.5,
  "tnx_10yr":  4.32,
  "adx":       28.4,
  "atr_pct":   1.2,
  "recommended_strategies": ["ema_cross", "momentum"],
  "avoid": ["mean_reversion", "range_trading"]
}
```

Claude sees all of this and uses it to decide:
- Don't buy calls if trend is `bear`
- Don't enter any directional trade if regime is `volatile`
- Strategy recommendations tell Claude what's working right now

---

## Claude — Hedge Fund Quant Mode

Claude's system prompt instructs it to act as a **hedge fund quantitative options trader**:

**Entry criteria (all must pass):**
1. Signal direction matches macro trend
2. Minimum 3:1 reward-to-risk ratio
3. IV < 45% (don't buy expensive options)
4. Bid-ask spread < 15% of mid
5. Confidence ≥ 0.70
6. Multi-factor score ≥ 2/4

**R:R enforcement:**
- Stop loss = −50% of premium paid
- Take profit = +150% of premium paid
- Effective R:R = 3:1 on every trade

**Prompt caching:** The system prompt is cached by the Anthropic API, so repeated calls within 5 minutes reuse the cached context — reducing token usage by ~40%.

---

## Self-Improvement (Weekly)

Every Monday at 9 AM ET, Claude reviews the past week's performance across all 3 strategies and updates the shared strategy rules. It acts as a **quant analyst** targeting:
- Higher Sharpe ratio
- Lower drawdown
- entry_threshold is never allowed below 0.70

The improvement cycle saves a new versioned strategy to the DB and activates it automatically.

---

## New API Endpoints

### Backtesting (Slide 2)
```
GET /strategy/backtest/{symbol}?period_years=2&fast=9&slow=21&sl_pct=0.02&tp_pct=0.04
```
Returns historical performance of the EMA-cross strategy:
- CAGR, Sharpe ratio, max drawdown, win rate
- Profit factor (avg win × wins / avg loss × losses)
- Long vs short win rates
- When the strategy performs best and what breaks it

Example:
```bash
curl https://your-api.onrender.com/strategy/backtest/SPY?period_years=2
```

### Monte Carlo Simulation (Slide 9)
```
POST /strategy/monte-carlo?win_rate=0.40&avg_win_pct=4.0&avg_loss_pct=-2.0&n_trades=50
```
Runs 1000 simulated paths with the given statistics and shows:
- Probability of losing money
- P5/P25/P50/P75/P95 return distribution
- Worst and best case
- Robustness assessment (robust / moderate / fragile)

### Monte Carlo from Real History
```
GET /strategy/monte-carlo/from-history?strategy_id=all
```
Same simulation but automatically uses your actual closed trade win rate, avg win, and avg loss.

---

## What You See in the Dashboard

The dashboard reads from these endpoints:

| Dashboard section | Endpoint |
|------------------|----------|
| Total capital / P&L | `GET /trades/account` |
| Strategy breakdown cards | `GET /trades/strategies` |
| P&L matrix (strategy × ticker) | `GET /trades/matrix` |
| Trade list with filtering | `GET /trades/` |
| Trade reasoning (Claude's explanation) | `GET /trades/{id}/journal` |

**What changes visually with the new pipeline:**
- Fewer trades overall (multi-factor gate + higher confidence threshold will skip more signals)
- Higher quality trades that do get through (Claude has richer context)
- Telegram alerts now include: regime + trend + VIX + factor score + R:R ratio
- No new dashboard UI panels yet — the backtest and Monte Carlo are API-only for now

---

## Project Structure

```
trading-bot/
├── backend/
│   ├── main.py                  # FastAPI app + APScheduler
│   ├── database.py              # SQLite schema + connection
│   ├── core/
│   │   ├── paper_trader.py      # Virtual account + trade recording
│   │   ├── indicators.py        # RSI, MACD, EMA, VWAP, Bollinger, ADX, ATR
│   │   │                        # + volume_analysis, get_macro_indicators, multi_factor_score
│   │   ├── regime.py            # Rich market regime detection (trend/volatility/volume/VIX)
│   │   ├── llm.py               # Claude hedge fund quant (prompt-cached, R:R enforced)
│   │   ├── backtester.py        # Historical backtest + Monte Carlo simulation
│   │   ├── options.py           # Alpaca options chain + order submission
│   │   └── improver.py          # Weekly self-improvement cycle
│   ├── routers/
│   │   ├── webhook.py           # TradingView signal handler + 3 quality gates
│   │   ├── trades.py            # Trade history + account summary endpoints
│   │   ├── strategy.py          # Strategy versions + backtest + Monte Carlo endpoints
│   │   └── improve.py           # Manual improvement trigger + history
│   └── models/
│       └── schemas.py
├── frontend/                    # React dashboard
├── scripts/
│   └── weekly_review.py
├── requirements.txt
├── render.yaml
└── .env.example
```

---

## Setup

### 1. Clone and install
```bash
git clone <your-repo-url>
cd trading-bot/backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Fill in:
# ANTHROPIC_API_KEY=
# ALPACA_API_KEY=
# ALPACA_SECRET_KEY=
# ALPACA_BASE_URL=https://paper-api.alpaca.markets
# WEBHOOK_SECRET=
# TELEGRAM_BOT_TOKEN=
# TELEGRAM_CHAT_ID=
```

### 3. Run locally
```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 4. API docs
- Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/health

---

## TradingView Alert Setup

In TradingView, set each alert's webhook URL to:
```
https://your-api.onrender.com/webhook/tradingview?symbol=SPY
```

Alert message body (JSON):
```json
{
  "secret": "your-webhook-secret",
  "symbol": "{{ticker}}",
  "signal": "buy",
  "price": {{close}},
  "strategy": "ema_cross"
}
```

Strategy values: `ema_cross`, `orb`, `ema_pullback`
Signal values: `buy`, `sell`, `close`
