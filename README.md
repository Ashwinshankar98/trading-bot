# Trading Bot

An AI-powered paper trading bot that receives TradingView signals, runs them through a multi-stage quality filter, and uses Claude as a hedge fund quant to decide whether to execute SPY options trades on Alpaca.

---

## Trading Concepts Explained Simply

> This section explains every term used in this bot as if you have never traded before. Read this first before looking at the chart.

---

### What is SPY?

SPY is a stock that tracks the S&P 500 — basically the 500 biggest companies in America bundled into one. When the American economy does well, SPY goes up. When it does badly, SPY goes down. It is the most traded thing in the US stock market every day, which is why this bot focuses only on SPY.

---

### What are Options?

When you buy a regular stock, you own a piece of the company. Options are different — they are a *bet* on which direction the stock will move.

- A **Call option** is a bet that SPY will go UP. You make money if it rises.
- A **Put option** is a bet that SPY will go DOWN. You make money if it falls.

Options are cheaper than buying SPY directly, but they expire — so timing matters. The bot only buys options (calls or puts), never the stock itself.

---

### What Does Each Indicator Mean?

#### EMA — Exponential Moving Average

Think of the EMA as a **smoothed price line** that follows the market. Instead of showing every tiny wiggle, it shows the general direction price has been moving.

- **EMA 9** (blue, thin) — looks at the last 9 candles. Reacts fast to price changes.
- **EMA 21** (orange, thick) — looks at the last 21 candles. Moves more slowly.
- **EMA 50** (blue, thick) — looks at the last 50 candles. Shows the medium-term trend.
- **EMA 200** (gray, thin) — looks at the last 200 candles. Shows the big-picture trend.

**Analogy:** Imagine you are tracking how fast a car is going. EMA 9 is like checking the speedometer every second (very reactive). EMA 200 is like averaging your speed over the whole trip (very smooth). When the fast line is above the slow line, the car is accelerating — that is a bullish sign.

---

#### VWAP — Volume Weighted Average Price

VWAP is the **average price of SPY for today**, but weighted by how much was traded at each price. It resets to zero every morning.

**Analogy:** Imagine a food market where 1,000 people bought apples at $1.00 and only 10 people bought at $1.50. The "fair price" is much closer to $1.00 because most of the trading happened there. That is VWAP — the price where most of today's money changed hands.

- Price **above VWAP** = buyers are in control. Good time for longs (calls).
- Price **below VWAP** = sellers are in control. Good time for shorts (puts).

---

#### RSI — Relative Strength Index

RSI is a number from 0 to 100 that measures **how fast and how much price has moved recently**.

- **Above 70** = overbought (price went up too fast, likely to pull back — avoid buying here)
- **Below 30** = oversold (price went down too fast, likely to bounce — avoid shorting here)
- **40–65** = the sweet spot for a healthy long trade

**Analogy:** Think of RSI like a sprinter's energy level. If they have been running at full speed for a long time (RSI above 70), they are about to slow down. If they have barely moved (RSI below 30), they have energy left. The bot wants to enter when the runner is moving at a good sustainable pace — not exhausted, not idle.

---

#### MACD — Moving Average Convergence Divergence

MACD measures **momentum** — is the move gaining speed or losing it?

The important part is the **histogram** (the bars in the MACD window):
- **Histogram above zero and growing** = bullish momentum is building → good for calls
- **Histogram below zero and falling** = bearish momentum is building → good for puts

**Analogy:** MACD is like checking whether a ball rolling down a hill is speeding up or slowing down. Even if the ball is still going down, if it is slowing down, the move is losing steam.

---

#### ADX — Average Directional Index

ADX measures **how strong the current trend is**, on a scale of 0 to 100. It does NOT tell you direction (up or down) — only strength.

- **ADX below 20** = the market is choppy and ranging (no clear trend). The bot stays out.
- **ADX above 20** = the market is trending with conviction. Safe to trade.

**Analogy:** ADX is like checking whether the wind is blowing hard or barely at all. You would not try to fly a kite on a calm day. The bot only takes trades when the "wind" (trend) is strong enough to carry the trade.

---

#### RVOL — Relative Volume

RVOL compares **today's volume to the 20-bar average**. It tells you whether the current move has real participation behind it.

- **RVOL 1.0x** = average volume — nothing special
- **RVOL 1.5x** = 50% more volume than normal — the market has conviction
- **RVOL 3.0x** = three times normal — a major move with strong institutional participation

**The bot requires RVOL ≥ 1.5x** on every signal. A breakout on low volume is a fake-out. A breakout on high volume is real.

**Analogy:** Imagine a vote. If only 10 out of 1,000 people vote, the result means nothing. If 900 people vote, the result is decisive. RVOL is the "voter turnout" of the market.

---

#### Fair Value Gap (FVG)

A Fair Value Gap is a **price zone that was skipped over** because the market moved too fast. It looks like an empty space between three candles on the chart — the body of the middle candle did not overlap with the candles on either side.

- **Bullish FVG** (green box) = price shot up so fast it left a gap below. The market will often come back to fill it. When price pulls back to this zone, it acts as **support** — a great place to buy.
- **Bearish FVG** (red box) = price dropped so fast it left a gap above. That gap acts as **resistance** — a great place to sell.

**Analogy:** Imagine a crowd rushing out of a building so fast that they left bags behind on certain floors. At some point, people will come back to pick up the bags. FVGs are those "forgotten floors" — price tends to revisit them.

---

#### Liquidity Sweep

A liquidity sweep is when price **briefly spikes past a key level to trigger other people's stop losses**, then immediately reverses.

Here is what actually happens:
1. A lot of retail traders place stop-loss orders just below a recent swing low (the obvious "safe" level).
2. Big institutions (smart money) push price down just enough to trigger all those stops — collecting cheap shares.
3. Once the stops are filled, there is no more selling pressure, and price rockets back up.

- **Bullish sweep** (aqua triangle, `SWEEP↑`) = price wicked below a swing low then closed back above it. The trap is set. A strong move UP usually follows.
- **Bearish sweep** (orange triangle, `SWEEP↓`) = price wicked above a swing high then closed back below it. A strong move DOWN usually follows.

**Analogy:** Imagine a casino that briefly lowers a game's payout to make people cash out their chips cheap — then immediately raises it again. The casino got everyone's chips at a discount. Smart money does the same thing with stop losses.

---

#### Opening Range (ORB — Strategy 2 only)

The **Opening Range** is the high and low price of SPY during the first 15 minutes of the market day (9:30 AM – 9:45 AM). This range is important because it captures the initial reaction to overnight news and sets the tone for the day.

- **ORB High** (green dashed line) = the ceiling of the first 15 minutes
- **ORB Low** (red dashed line) = the floor of the first 15 minutes

After 9:45 AM, if price breaks out above the ORB High with strong volume, it signals that buyers have won the morning battle and the day is likely to trend up. The reverse is true for a break below the ORB Low.

---

### Why Does a BUY Signal Fire?

A BUY signal means the bot has detected a high-quality long setup. Here are the three specific scenarios, one per strategy.

---

#### Scenario A — EMA Cross BUY (Strategy 1)

**What it means in plain English:** The fast-moving average just crossed above the slow-moving average, price is above fair value, momentum is positive, and institutional buying (FVG or sweep) is present. Everything is pointing up at the same time.

**All of these must be true simultaneously:**

| Condition | Why it matters |
|-----------|---------------|
| EMA 9 crossed above EMA 21 | The short-term trend just flipped bullish |
| Price is above VWAP | Buyers are in control of today's session |
| RSI is between 50–70 | Momentum is bullish but not overextended |
| MACD histogram is positive and rising | The move is gaining speed |
| ADX is above 20 | The market is actually trending, not choppy |
| RVOL is ≥ 1.5× | Real volume is behind this move |
| A bullish FVG or recent bull sweep is present | Institutional footprint confirms the move |

**Example:** SPY has been ranging, then a big green candle causes EMA 9 to cross above EMA 21. Volume is 2× normal. There is a green FVG box right below current price acting as support. RSI is 58, MACD is ticking up. → `BUY [FVG] RVOL 2.0x` label appears.

---

#### Scenario B — ORB BUY (Strategy 2)

**What it means in plain English:** In the first 15 minutes, SPY established a range. At some point during the day, price broke above the top of that range on strong volume — meaning buyers have decisively won. Even better if price previously dipped below the range bottom (swept the lows) before breaking out — that was smart money loading up cheap before the real move.

**All of these must be true simultaneously:**

| Condition | Why it matters |
|-----------|---------------|
| It is after 9:45 AM (ORB is set) | The opening range is locked and valid |
| Price just crossed above ORB High | The morning ceiling was broken by buyers |
| RVOL is ≥ 1.5× | This is a genuine breakout, not a fake |
| A bullish FVG, bull sweep, or ORB low was swept | Smart money confirmation |

**Best setup:** Price dips below the ORB low early in the morning (sweeping the lows, triggering all the stop losses of people who went long at the open), then rockets back up and breaks above the ORB high. The table will show "ORB Low Swept" in teal. → `ORB BUY [SWEEP] RVOL 1.9x` label appears.

---

#### Scenario C — Pullback BUY (Strategy 3)

**What it means in plain English:** SPY is in an uptrend (above EMA 50). Price pulled back and touched EMA 21, then bounced back above it. This is not a random bounce — it happened right at a bullish FVG (institutional support zone) or right after a liquidity sweep (smart money loaded up). The pullback is over and the trend is resuming.

**All of these must be true simultaneously:**

| Condition | Why it matters |
|-----------|---------------|
| Price is above EMA 50 | The medium-term trend is up |
| EMA 21 is rising | The dynamic support line is still pointing up |
| Price touched EMA 21 and closed back above it | The pullback just ended — entry timing is perfect |
| RSI is between 40–65 | Not overextended — there is room to run |
| RVOL is ≥ 1.5× | Real buying volume on the bounce |
| A bullish FVG is nearby OR a bull sweep just happened | Smart money is supporting the bounce |

**Example:** SPY has been trending up all morning. Price pulls back and taps EMA 21 at 10:30 AM. Right at that EMA level, there is a green FVG box (institutional support). Price bounces off both the EMA and the FVG simultaneously. RSI is 52, RVOL is 1.7×. → `PB BUY [IN FVG] RVOL 1.7x` label appears.

---

### Why Does a SELL Signal Fire?

SELL signals work exactly like BUY signals but in reverse. Instead of buying calls (bet on price going up), the bot buys puts (bet on price going down). All the same conditions apply, mirrored:

- EMA 9 crosses **below** EMA 21 (Strategy 1)
- Price crosses **below** ORB Low (Strategy 2)
- Price is below EMA 50, pulls back up to EMA 21, and **gets rejected** back down (Strategy 3)
- Price is **below** VWAP
- A **bearish** FVG (red box) is acting as resistance above
- A **bear sweep** just happened (price briefly spiked above a high then came back down)

---

### Why Does the Bot Skip a Signal?

Even when TradingView fires an alert, the bot may decide not to trade. Here is why:

| Reason | What it means in plain English |
|--------|-------------------------------|
| VIX > 30 | The market is in panic mode. Options are extremely expensive and directional bets fail. The bot sits out entirely. |
| Score < 3/5 factors | Not enough indicators are agreeing. A signal where only 2 out of 5 things line up is a coin flip — the bot ignores it. |
| No liquid options | The specific options contract the bot wants to buy has too wide a bid-ask spread. Buying it would guarantee a loss at entry. |
| Claude confidence < 70% | Even if all indicators are green, Claude's final judgment is not confident enough. The bot would rather miss a trade than take a bad one. |

---

### Quick Examples for Every Term

Real numbers so you can recognise these on a live chart.

**EMA example**
> SPY is at $542. EMA 9 = $541.20, EMA 21 = $540.80. EMA 9 is above EMA 21 → bullish alignment. On the previous bar, EMA 9 was at $540.70 — it just crossed above EMA 21. That crossover is what fires the Strategy 1 buy signal.

**VWAP example**
> It is 11 AM. Most of the morning's trading happened between $539–$541. VWAP is sitting at $540.50. SPY is now at $542 → price is above VWAP → buyers are in control → the bot will only consider long trades (calls), not short trades (puts).

**RSI example**
> After a strong rally, RSI reaches 74. The bot will NOT fire a buy signal because RSI > 70 means the move is overextended — there are likely no buyers left to push it higher, and a pullback is coming. If RSI was 58, it would pass the check.

**MACD example**
> The MACD histogram was at −0.05 two bars ago, −0.02 last bar, and is now +0.03. It just crossed above zero and is rising → bullish momentum is building → MACD check passes. If the histogram was positive but shrinking (0.10 → 0.06 → 0.02), momentum is fading and the check would fail.

**ADX example**
> It is 9:50 AM and SPY has barely moved since the open. ADX = 12. The market is choppy with no clear direction. Even if EMA 9 crosses EMA 21, the bot ignores it because ADX < 20 means the "trend" has no real conviction behind it. At 10:30 AM a strong move happens and ADX climbs to 28 → the bot is now willing to trade.

**RVOL example**
> The average 5-minute volume for SPY at 10 AM is about 800,000 shares. On a particular bar, volume is 1,500,000 shares — that is 1.87× the average. RVOL = 1.87x → passes the ≥1.5 requirement. A breakout on this bar is real. If volume was only 600,000 (RVOL = 0.75x), the same breakout would be ignored as a fake-out.

**FVG example**
> At 10:05 AM, three candles form: Candle 1 high = $541.00, Candle 2 is a big bullish bar, Candle 3 low = $541.80. Because Candle 3's low ($541.80) is above Candle 1's high ($541.00), there is a gap between $541.00 and $541.80 that was never traded. That zone is a Bullish FVG — shown as a green box on the chart. When price later pulls back to $541.20 and bounces, the bot recognises this as institutional support and the label will show `[FVG]`.

**Liquidity Sweep example**
> Between 10:00 and 10:15 AM, SPY bounced off $540.00 twice, creating a clear swing low. Many retail traders place their stop losses just below that level at $539.80. At 10:30 AM, a single candle spikes down to $539.60 (below the swing low, triggering all those stops) then immediately closes back up at $540.30. That spike is a bull sweep — shown as an aqua `SWEEP↑` triangle. The stops have been taken, the sellers are exhausted, and price is free to move up. A buy signal in the next few bars carries a `[SWEEP]` tag.

**ORB example**
> SPY opens at 9:30 AM at $540. In the first 15 minutes it trades between $539.50 (ORB Low) and $541.00 (ORB High). At 9:45 AM the range is locked — you see a green dashed line at $541 and a red dashed line at $539.50. At 10:15 AM a strong bar closes at $541.40, crossing above the $541 green line on 2.1× volume. That is the ORB BUY signal. Stop loss = ORB Low ($539.50), take profit = $541 + ($541 − $539.50) = $542.50.

---

### Complete Trade Walkthrough — From Signal to Exit

Here is a full example of what happens from the moment TradingView sees a setup to the moment the trade closes.

**Setup: Strategy 1 (EMA Cross BUY) at 10:22 AM**

```
Time:      10:22 AM
SPY price: $542.10

Chart shows:
  - EMA 9 (541.80) just crossed above EMA 21 (541.60)       ✅ EMA cross
  - Price ($542.10) is above VWAP ($540.90)                 ✅ Above VWAP
  - RSI = 57                                                 ✅ In range (50–70)
  - MACD histogram = +0.08 and rising                        ✅ Bullish
  - ADX = 26                                                 ✅ Trending (>20)
  - RVOL = 2.1×                                              ✅ High volume
  - Green FVG box at $541.00–$541.50 (price bouncing off it) ✅ FVG present
  → Status table: 7/7 rows teal. SIGNAL = BUY
  → Label on chart: "BUY [FVG] RVOL 2.1x"
```

**Step 1 — TradingView fires the alert**

The Pine Script sends this JSON to the bot's server:
```json
{
  "secret": "mysecret123",
  "symbol": "SPY",
  "signal": "buy",
  "price": 542.10,
  "strategy": "ema_cross"
}
```

**Step 2 — Backend immediately returns 200 to TradingView, starts background processing**

The bot logs the signal to the database and spins up a background task so TradingView does not time out waiting.

**Step 3 — Gate 1: VIX check**

> VIX = 17.2 → below 30 ✅ — proceed

**Step 4 — Gate 2: Multi-factor score**

The bot fetches live indicators from yfinance (1h bars):
```
Momentum (RSI 57, MACD +):  ✅
Trend (EMA fast > slow):     ✅
VWAP (price above):          ✅
ADX (26 > 20):               ✅
FVG/Sweep (bull FVG active): ✅
Score: 5/5 → passes (need ≥3)
```

**Step 5 — Gate 3: Options candidates**

The bot checks Alpaca for liquid SPY call options near the $542 strike:
```
[1] SPY260620C00542000 | ATM CALL | $2.45 mid | spread 3.2% | IV 18% | delta 0.51
[2] SPY260620C00545000 | OTM CALL | $1.20 mid | spread 5.1% | IV 19% | delta 0.38
→ 2 liquid candidates found ✅
```

**Step 6 — Gate 4: Claude decides**

Claude reviews everything and responds:
```json
{
  "action": "open",
  "chosen_contract": "SPY260620C00542000",
  "contracts": 2,
  "confidence": 0.83,
  "rr_ratio": 3.1,
  "reasoning": "ATM call on bullish EMA cross with 5/5 factor
                alignment. FVG at $541.00 provides strong support.
                IV at 18% is well below the 45% threshold. R:R of
                3.1:1 satisfies entry criteria. Main risk: broad
                market softness if VIX spikes intraday."
}
```
Confidence 83% → above 70% threshold ✅

**Step 7 — Order placed on Alpaca**

```
Buy 2 contracts of SPY260620C00542000 @ $2.45
Total cost: $2.45 × 100 × 2 = $490
Stop loss:  −50% of premium = $1.225/contract → close if price drops to $1.23
Take profit: +150% of premium = $6.125/contract → close if price reaches $6.13
```

**Step 8 — Telegram notification sent**

```
📡 BUY SPY @ $542.10  [EMA Cross + VWAP]
Regime: trending (bullish) | VIX: 17.2 | ATR: 0.9%

Gate Results:
  ✅ Gate 1 — VIX ≤ 30  (current: 17.2)
  ✅ Gate 2 — Score 5/5  (need ≥3)
    ✅  Momentum  RSI=57 MACD hist=+
    ✅  Trend  EMA fast > slow
    ✅  VWAP  price above
    ✅  ADX  =26 need >20
    ✅  FVG / Sweep  active
  ✅ Gate 3 — Options  (2 liquid candidates)
  ✅ Gate 4 — Claude  (confidence 83%  need ≥70%)
            R:R = 3.1:1

🟢 OPENED

Contract: SPY260620C00542000
Strike: $542 | ATM | CALL
Premium: $2.45 × 2 = $490
IV: 18.0% | Delta: 0.51 | Theta: $-0.12/day
```

**Step 9 — Trade runs, then closes**

SPY rallies to $544.80. The option premium rises to $6.20.
Take profit is triggered (> $6.125). The close signal fires:

```
Close: SPY260620C00542000 @ $6.20
PnL: ($6.20 − $2.45) × 100 × 2 = +$750
```

Telegram sends: `🔴 TRADE CLOSED — SPY CALL | Exit: $6.20 | PnL: +$750.00 ✅ WIN`

Claude then writes a post-mortem:
```json
{
  "what_worked": "FVG confluence provided clean support, EMA cross
                  timing was precise, volume confirmed the move.",
  "what_failed":  "Nothing — all criteria held throughout the trade.",
  "market_notes": "Bull trend day with low VIX. EMA cross strategies
                   perform best in these conditions."
}
```

That post-mortem is saved to the database and visible in the dashboard under the trade's journal tab.

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
