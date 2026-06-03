# Trading Bot

An AI-powered paper trading bot that receives TradingView signals, runs them through a multi-stage quality filter, and uses Claude as a hedge fund quant to decide whether to execute SPY options trades on Alpaca.

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
TradingView Alert (SPY 5m chart)
      │
      ▼
POST /webhook/tradingview
      │
      ├─ Log signal to DB immediately → return 200 to TradingView
      │
      └─ Background task:
            │
            ├─ Fetch live indicators: RSI, MACD, EMA, VWAP, ADX, ATR,
            │  RVOL, Fair Value Gaps, Liquidity Sweep
            │
            ├─ Detect market regime → trend + volatility + VIX + 10-yr yield
            │
            ├─ GATE 1 — VIX > 30?
            │     YES → Telegram: "❌ Gate 1 FAILED — panic regime"  → STOP
            │
            ├─ GATE 2 — Multi-factor score < 3/5?
            │     YES → Telegram: "❌ Gate 2 FAILED — X/5 factors"   → STOP
            │
            ├─ GATE 3 — No liquid options candidates?
            │     YES → Telegram: "❌ Gate 3 FAILED — no liquid opts" → STOP
            │
            ├─ GATE 4 — Claude confidence < 0.70?
            │     YES → Telegram: "❌ Gate 4 FAILED — XX% confidence" → STOP
            │
            ├─ Submit buy order to Alpaca
            ├─ Record trade in DB
            └─ Telegram: full gate summary + contract details
```

Every signal — whether it fires or gets rejected — produces a Telegram message showing exactly which gates passed and which failed.

---

## The 5-Factor Gate (Gate 2)

Before Claude is called, five technical factors are scored. The signal needs **at least 3/5** to proceed:

| Factor | Long (buy) | Short (sell) |
|--------|-----------|-------------|
| Momentum | RSI 40–70 AND MACD hist > 0 | RSI 30–60 AND MACD hist < 0 |
| Trend | EMA fast > EMA slow | EMA fast < EMA slow |
| VWAP | Price above VWAP | Price below VWAP |
| ADX | ADX > 20 (trending market) | ADX > 20 |
| SMC | Bullish FVG or bull sweep present | Bearish FVG or bear sweep present |

This gate runs before any API call to Claude — it blocks low-quality signals cheaply.

---

## What You See in Telegram (for every signal)

```
📡 BUY SPY @ $542.10  [EMA Cross + VWAP]
Regime: trending (bullish) | VIX: 18 | ATR: 0.8%

Gate Results:
  ✅ Gate 1 — VIX ≤ 30  (current: 18)
  ✅ Gate 2 — Score 4/5  (need ≥3)
    ✅  Momentum  (RSI=58  MACD hist=+)
    ✅  Trend  (EMA fast > slow)
    ✅  VWAP  (price above)
    ✅  ADX  (=27  need >20)
    ❌  FVG / Sweep  (none)
  ✅ Gate 3 — Options  (3 liquid candidates)
  ✅ Gate 4 — Claude  (confidence 82%  need ≥70%)
            R:R = 3.2:1
            "Bullish EMA cross with strong ADX confirms trend..."

🟢 OPENED

Contract: SPY250620C00542000
Strike: $542 | ATM | CALL
Premium: $2.45 × 2 = $490
IV: 18.3% | Delta: 0.52 | Theta: $-0.14/day
```

Rejected signals look the same but end with `🔴 REJECTED — reason`.

---

## TradingView Pine Scripts

Three strategies live in `scripts/`. All are **SPY-only** — an on-chart warning label appears if you load them on any other ticker.

### Strategy 1 — EMA Cross + FVG + Sweep (`strategy_1_ema_cross.pine`)
Triggers when EMA 9 crosses EMA 21 with VWAP, RSI, MACD, ADX, RVOL, and SMC confluence all aligned.

### Strategy 2 — ORB + FVG + Sweep (`strategy_2_orb.pine`)
Captures the Opening Range Breakout (first 15 minutes, 9:30–9:45). Fires when price breaks above/below the range with RVOL and SMC confluence. Best setup: the opposite side of the range is swept (inducement) before the breakout.

### Strategy 3 — EMA 21 Pullback + FVG + Sweep (`strategy_3_ema_pullback.pine`)
Triggers when price pulls back to EMA 21 in the direction of EMA 50 trend and bounces, confirmed by RSI, RVOL, and a nearby FVG or prior liquidity sweep.

### Visual Features (all 3 scripts)

| Feature | What you see |
|---------|-------------|
| FVG zones | Green/red shaded boxes for bullish/bearish Fair Value Gaps. Last 5 per direction. Box fades when price enters the zone (partially mitigated). |
| Sweep markers | Aqua `SWEEP↑` triangle below bar / orange `SWEEP↓` triangle above bar when a liquidity sweep occurs |
| Signal labels | Every entry shows `▲ BUY` or `▼ SELL` with which confluence fired: `📦 FVG`, `💧 SWEEP`, and RVOL value |
| Exit labels | `✖ EXIT` with reason: `SL HIT`, `TP HIT`, or `EOD` |
| Status table | Top-right corner — all factors live with teal (✓) / maroon (✗) color coding |
| Regime background | Subtle green tint = uptrend, red tint = downtrend |
| SL / TP lines | Dashed lines on chart tracking the active position's stop and target |

---

## How to Set Up in TradingView

### Step 1 — Add the scripts

1. Open TradingView → load **SPY** → set timeframe to **5 minutes**
2. Click **Pine Script Editor** (bottom panel) → paste a `.pine` file → **Save** → **Add to Chart**
3. Repeat for all 3 strategies (you can stack all 3 on the same chart)

### Step 2 — Create one alert per strategy

For each strategy indicator:

1. Click the **Alerts** clock icon → **Create Alert**
2. Fill in:

| Field | Value |
|-------|-------|
| Condition | Select the strategy name → **"Any alert() function call"** |
| Trigger | **Once Per Bar Close** |
| Webhook URL | `https://your-render-url.onrender.com/webhook/tradingview` |
| Message | Leave blank (each alert sends its own JSON payload) |

That's 3 alerts total — one per strategy.

> The scripts send the webhook payload themselves via `alert()`. You don't type anything into the "Message" field.

### Step 3 — Verify it's working

After the market opens, send a test signal:
```bash
curl -X POST https://your-api.onrender.com/webhook/test \
  -H "Content-Type: application/json" \
  -d '{"symbol":"SPY","side":"long","price":542.00,"strategy":"ema_cross"}'
```

You should get a Telegram message and see a test trade in the dashboard.

---

## Market Regime Detection

Every signal triggers a full regime analysis:

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
- No calls in a bear trend; no puts in a bull trend (unless volatility regime)
- Skip if VIX > 30 (panic market, options pricing unreliable)
- Recommended strategies tell Claude what's working right now

---

## Claude — Hedge Fund Quant Mode

Claude's system prompt gives it a hedge fund quantitative options trader persona. **All conditions must pass before it opens a trade:**

1. Signal direction matches macro trend
2. Minimum 3:1 reward-to-risk (stop = −50% premium, target = +150% premium)
3. IV < 45%
4. Bid-ask spread < 15% of mid
5. Confidence ≥ 0.70
6. Multi-factor score ≥ 2/5

**Prompt caching** is used on the system message — repeated calls within 5 minutes reuse the cached context, saving ~40% tokens.

---

## Self-Improvement (Weekly)

Every Monday at 9 AM ET, Claude reviews the past week's performance across all 3 strategies and updates the shared strategy rules. The `entry_threshold` is never allowed below 0.70. The improved strategy is saved to the DB and activated automatically.

---

## API Endpoints

### Webhooks
| Endpoint | Description |
|----------|-------------|
| `POST /webhook/tradingview` | Receive TradingView alert, run gate pipeline |
| `POST /webhook/test` | Force open a test trade (bypasses Claude) |

### Trades
| Endpoint | Description |
|----------|-------------|
| `GET /trades/` | Trade history with filtering |
| `GET /trades/account` | Total capital and P&L |
| `GET /trades/strategies` | Per-strategy breakdown |
| `GET /trades/matrix` | P&L matrix (strategy × ticker) |
| `GET /trades/{id}/journal` | Claude's post-mortem for a trade |

### Strategy & Backtesting
| Endpoint | Description |
|----------|-------------|
| `GET /strategy/backtest/{symbol}` | Historical EMA-cross backtest (CAGR, Sharpe, drawdown, win rate) |
| `POST /strategy/monte-carlo` | 1000-path Monte Carlo simulation |
| `GET /strategy/monte-carlo/from-history` | Monte Carlo using actual closed trade stats |

---

## Project Structure

```
trading-bot/
├── backend/
│   ├── main.py                  # FastAPI app + APScheduler
│   ├── database.py              # SQLite schema
│   ├── core/
│   │   ├── indicators.py        # RSI, MACD, EMA, VWAP, ADX, ATR,
│   │   │                        # RVOL, FVG detection, liquidity sweep
│   │   ├── regime.py            # Rich market regime detection
│   │   ├── llm.py               # Claude hedge fund quant (prompt-cached)
│   │   ├── backtester.py        # Historical backtest + Monte Carlo
│   │   ├── options.py           # Alpaca options chain + order submission
│   │   ├── paper_trader.py      # Virtual account + trade recording
│   │   └── improver.py          # Weekly self-improvement cycle
│   └── routers/
│       ├── webhook.py           # Signal handler + 4 quality gates + Telegram
│       ├── trades.py            # Trade history + account endpoints
│       ├── strategy.py          # Strategy + backtest + Monte Carlo endpoints
│       └── improve.py           # Manual improvement trigger
├── frontend/                    # React dashboard
├── scripts/
│   ├── strategy_1_ema_cross.pine     # EMA Cross + FVG + Sweep [SPY Only]
│   ├── strategy_2_orb.pine           # ORB + FVG + Sweep [SPY Only]
│   └── strategy_3_ema_pullback.pine  # EMA 21 Pullback + FVG + Sweep [SPY Only]
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
source venv/bin/activate
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
# WEBHOOK_SECRET=mysecret123
# TELEGRAM_BOT_TOKEN=
# TELEGRAM_CHAT_ID=
```

### 3. Run locally
```bash
cd backend
uvicorn main:app --reload --port 8000
```

API docs: http://localhost:8000/docs
