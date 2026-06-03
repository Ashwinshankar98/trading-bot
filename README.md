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

Three strategies live in `scripts/`. All are **SPY-only** — a warning label appears on-chart if you load them on any other ticker.

---

## TradingView Chart Visual Guide

This section explains every visual element you see when all three strategies are loaded on a SPY 5m chart.

---

### Lines on the Chart

| Line | Color | What it means |
|------|-------|---------------|
| **EMA 9** | Blue (thin) | Fast EMA — used in Strategy 1 (EMA Cross). When it crosses above EMA 21 = bullish momentum. |
| **EMA 21** | Orange (thick) | The key dynamic support/resistance level. Strategy 3 (Pullback) uses bounces off this line as entries. |
| **EMA 50** | Blue (thick) | Trend filter for Strategy 3. Price above = uptrend, price below = downtrend. |
| **EMA 200** | Gray (thin) | Long-term macro trend. All strategies use this for regime background coloring. |
| **VWAP** | Purple (thick) | Volume-Weighted Average Price — the fair value for the day. Entries require price to be on the correct side. |
| **ORB High** | Green dashed | Opening Range high (first 15 min). Strategy 2 only — a crossover above fires a buy signal. |
| **ORB Low** | Red dashed | Opening Range low (first 15 min). Strategy 2 only — a crossunder below fires a sell signal. |
| **SL line** | Red dotted | Active stop-loss level. Disappears when no position is open. |
| **TP line** | Green dotted | Active take-profit target. Disappears when no position is open. |

---

### Background Color (Chart Tint)

| Color | Meaning |
|-------|---------|
| Faint **green** tint | Uptrend / Bull regime (price above EMA 50 or EMA 200 depending on strategy) |
| Faint **red** tint | Downtrend / Bear regime |
| No tint | Ranging / neutral market |

This is just context — it does not fire any signal on its own.

---

### Shaded Boxes (Fair Value Gaps)

Fair Value Gaps (FVGs) are price imbalances where the market moved too fast and left an unfilled gap between candles. Institutions often return to fill these — making them high-probability entry zones.

| Box color | Meaning |
|-----------|---------|
| **Green box** | Bullish FVG — a gap below current price. Acts as support. A long entry near here has extra confluence. |
| **Red box** | Bearish FVG — a gap above current price. Acts as resistance. A short entry near here has extra confluence. |
| **Faded box** | Price has entered the zone (partially mitigated). Still relevant but weaker. |

Up to 5 boxes per direction are shown at a time. Boxes extend 20 bars to the right so you can see them clearly.

**How to read them:** When a buy signal fires and a green FVG box is nearby, the label will say `[FVG]` — meaning price is bouncing off institutional support. That's a stronger setup than a signal with no FVG.

---

### Triangle Markers (Liquidity Sweeps)

A liquidity sweep is when price briefly spikes beyond a swing high or low (hunting stops), then immediately snaps back. Smart money does this to fill orders before reversing. After a sweep, a strong move in the opposite direction often follows.

| Marker | Color | Meaning |
|--------|-------|---------|
| **Triangle UP** below bar | Aqua, labeled `SWEEP↑` | A bullish sweep — price wicked below a recent swing low and closed back above it. Expect upside. |
| **Triangle DOWN** above bar | Orange, labeled `SWEEP↓` | A bearish sweep — price wicked above a recent swing high and closed back below it. Expect downside. |

**How to read them:** If you see a `SWEEP↑` triangle just before a buy signal, the label will say `[SWEEP]`. This is the highest-quality entry — smart money already hunted the stops, the trap is set.

---

### Signal Labels

Labels appear directly on the chart at the exact bar where a signal fired.

| Label text | Color | Meaning |
|-----------|-------|---------|
| `BUY [FVG] RVOL 1.8x` | Green | Long entry signal. `[FVG]` = a Fair Value Gap confirmed it. RVOL shows how much above-average the volume was. |
| `BUY [SWEEP] RVOL 2.1x` | Green | Long entry confirmed by a prior liquidity sweep. |
| `BUY [FVG] [SWEEP] RVOL 3.0x` | Green | Both FVG and sweep confirmed — strongest setup. |
| `ORB BUY [FVG] RVOL 1.6x` | Green | Strategy 2: price broke above the Opening Range High with FVG confluence. |
| `PB BUY [IN FVG] RVOL 1.9x` | Green | Strategy 3: price pulled back to EMA 21 and is sitting inside a bullish FVG — prime entry zone. |
| `SELL ...` | Red | Short entry signal — same confluence tags apply. |
| `EXIT - SL HIT` | Gray | Position closed because price hit the stop loss. |
| `EXIT - TP HIT` | Gray | Position closed because price hit the take-profit target. |
| `EXIT - EOD` | Gray | Position closed at end of day (after 3:45 PM) regardless of P&L. |

---

### Status Table (Top-Right Corner)

The table updates in real time on every bar. It shows the current value of every factor the strategy checks. **Teal = passing, Maroon = failing.**

#### Strategy 1 — EMA Cross

| Row | What it shows | Pass condition |
|-----|--------------|----------------|
| Ticker | Current chart symbol | Must be SPY |
| RVOL | Relative Volume (current vol ÷ 20-bar avg) | ≥ 1.5× |
| RSI (14) | Momentum oscillator | 40–70 for longs |
| MACD Hist | MACD histogram direction | Positive (bullish) or negative (bearish) |
| EMA 9 vs 21 | Fast vs slow EMA relationship | Fast > Slow for longs |
| vs VWAP | Price relative to daily VWAP | Above for longs |
| ADX | Trend strength (0–100) | > 20 (market is trending) |
| Bull FVG | Bars since last bullish FVG formed | Within last 15 bars |
| Bear FVG | Bars since last bearish FVG formed | Within last 15 bars |
| Liq Sweep | Most recent sweep direction | Bull or Bear sweep within 5 bars |
| **SIGNAL** | Current signal state | BUY / SELL / WAITING |
| **Regime** | Macro trend based on EMA 200 + ADX | BULL TREND / BEAR TREND / RANGING |

#### Strategy 2 — ORB

Same table structure, with these ORB-specific rows replacing some:

| Row | What it shows | Pass condition |
|-----|--------------|----------------|
| ORB Set | Whether the 9:30–9:45 range is locked | Shows High / Low prices once set |
| ORB Range | Size of the Opening Range in dollars | Informational |
| Price Zone | Where price is relative to the range | Above ORB / Inside Range / Below ORB |
| Liq Sweep | General sweep + ORB-specific sweep | "ORB Low Swept" = best bull setup |

#### Strategy 3 — EMA 21 Pullback

| Row | What it shows | Pass condition |
|-----|--------------|----------------|
| Trend | Price vs EMA 50 | Uptrend for longs |
| EMA21 Slope | Is EMA 21 rising or falling | Rising for longs |
| PB Bounce | Did price touch and bounce off EMA 21 | "Bounced above EMA21" |
| RSI (14) | Must be in pullback zone, not overextended | 40–65 for longs |
| RVOL | Relative Volume | ≥ 1.5× |
| vs VWAP | Price relative to VWAP | Above for longs |
| In FVG Zone | Is price currently sitting inside a FVG | "In Bull FVG" = prime entry |
| Recent FVG | Bars since last FVG formed | Within last 15 bars |
| Liq Sweep | Was there a sweep before the bounce | Within last 5 bars |
| **SIGNAL** | Current signal state | PB BUY / PB SELL / WAITING |
| **Macro** | Price vs EMA 200 | BULL / BEAR |

---

### How to Read the Chart at a Glance

1. **Check the background** — green tint means the trend is with you for longs, red for shorts
2. **Check the status table** — count how many rows are teal. More teal = stronger setup
3. **Look for FVG boxes** — a green box near current price is support for a long
4. **Look for SWEEP triangles** — a recent `SWEEP↑` before a long signal = highest quality entry
5. **Read the signal label** — it tells you exactly what confluence fired (`[FVG]`, `[SWEEP]`, RVOL)
6. **Watch the SL/TP lines** — once a position is open, the red line is your stop, green is your target

---

### Strategy 1 — EMA Cross + FVG + Sweep (`strategy_1_ema_cross.pine`)
Triggers when EMA 9 crosses EMA 21 with VWAP, RSI, MACD, ADX, RVOL, and SMC confluence all aligned.

### Strategy 2 — ORB + FVG + Sweep (`strategy_2_orb.pine`)
Captures the Opening Range Breakout (first 15 minutes, 9:30–9:45). Fires when price breaks above/below the range with RVOL and SMC confluence. Best setup: the opposite side of the range is swept (inducement) before the breakout.

### Strategy 3 — EMA 21 Pullback + FVG + Sweep (`strategy_3_ema_pullback.pine`)
Triggers when price pulls back to EMA 21 in the direction of EMA 50 trend and bounces, confirmed by RSI, RVOL, and a nearby FVG or prior liquidity sweep.

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
