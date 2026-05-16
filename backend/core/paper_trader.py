import json
from database import get_connection
from datetime import datetime, timezone, time
import pytz


def is_market_open() -> bool:
    """Only trade between 9:45am and 3:45pm Eastern, Mon-Fri."""
    eastern = pytz.timezone("US/Eastern")
    now = datetime.now(eastern)
    
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    
    market_open  = time(9, 45)
    market_close = time(15, 45)
    current_time = now.time()
    
    return market_open <= current_time <= market_close

def get_account():
    conn = get_connection()
    row = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
    conn.close()
    return dict(row)

def get_active_strategy():
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM strategy_versions WHERE is_active = 1"
    ).fetchone()
    conn.close()
    return json.loads(row["rules"]) if row else {}

def get_open_trades():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trades WHERE status = 'open'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def open_trade(symbol, side, entry_price, indicators, reasoning, regime):
    strategy = get_active_strategy()
    account  = get_account()

    max_open = strategy.get("max_open_trades", 3)
    open_trades = get_open_trades()

    if len(open_trades) >= max_open:
        return None, f"Max open trades ({max_open}) reached"

    position_pct = strategy.get("position_size_pct", 0.10)
    capital      = account["balance"] * position_pct
    quantity     = round(capital / entry_price, 6)

    sl_pct = strategy.get("stop_loss_pct", 0.02)
    tp_pct = strategy.get("take_profit_pct", 0.04)

    if side == "long":
        stop_loss   = round(entry_price * (1 - sl_pct), 4)
        take_profit = round(entry_price * (1 + tp_pct), 4)
    else:
        stop_loss   = round(entry_price * (1 + sl_pct), 4)
        take_profit = round(entry_price * (1 - tp_pct), 4)

    conn = get_connection()
    strategy_ver = conn.execute(
        "SELECT version FROM strategy_versions WHERE is_active = 1"
    ).fetchone()["version"]

    cur = conn.execute("""
        INSERT INTO trades
            (symbol, side, entry_price, quantity, stop_loss, take_profit,
             indicators, llm_reasoning, regime, strategy_ver)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol, side, entry_price, quantity,
        stop_loss, take_profit,
        json.dumps(indicators), reasoning, regime, strategy_ver
    ))

    conn.execute("""
        INSERT INTO signals (symbol, source, signal_type, payload, acted_on)
        VALUES (?, 'internal', ?, ?, 1)
    """, (symbol, side, json.dumps({"price": entry_price})))

    conn.commit()
    trade_id = cur.lastrowid
    conn.close()

    return trade_id, "ok"

def close_trade(trade_id, exit_price):
    conn = get_connection()
    trade = conn.execute(
        "SELECT * FROM trades WHERE id = ? AND status = 'open'", (trade_id,)
    ).fetchone()

    if not trade:
        conn.close()
        return None, "Trade not found or already closed"

    trade = dict(trade)
    quantity = trade["quantity"]

    if trade["side"] == "long":
        pnl = (exit_price - trade["entry_price"]) * quantity
    else:
        pnl = (trade["entry_price"] - exit_price) * quantity

    pnl_pct = round((pnl / (trade["entry_price"] * quantity)) * 100, 2)
    pnl     = round(pnl, 4)

    conn.execute("""
        UPDATE trades
        SET status='closed', exit_price=?, pnl=?, pnl_pct=?, exit_at=datetime('now')
        WHERE id=?
    """, (exit_price, pnl, pnl_pct, trade_id))

    conn.execute("""
        UPDATE account
        SET balance = balance + ?, equity = equity + ?, updated_at = datetime('now')
        WHERE id = 1
    """, (pnl, pnl))

    conn.commit()
    conn.close()
    return pnl, "ok"

def update_equity(current_prices: dict):
    """Recalculate equity based on current mark-to-market prices."""
    open_trades = get_open_trades()
    open_pnl = 0.0

    for t in open_trades:
        price = current_prices.get(t["symbol"])
        if not price:
            continue
        if t["side"] == "long":
            open_pnl += (price - t["entry_price"]) * t["quantity"]
        else:
            open_pnl += (t["entry_price"] - price) * t["quantity"]

    conn = get_connection()
    balance = conn.execute("SELECT balance FROM account WHERE id=1").fetchone()["balance"]
    conn.execute("""
        UPDATE account SET equity = ?, updated_at = datetime('now') WHERE id = 1
    """, (round(balance + open_pnl, 2),))
    conn.commit()
    conn.close()
