import json
from database import get_connection

STRATEGY_IDS = ["ema_cross", "orb", "ema_pullback"]

def get_strategy_account(strategy_id: str) -> dict:
    conn = get_connection()
    row  = conn.execute(
        "SELECT * FROM strategy_accounts WHERE strategy_id = ?", (strategy_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else {"balance": 10000.0, "equity": 10000.0}

def get_all_strategy_accounts() -> list:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM strategy_accounts ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_account():
    """Legacy — returns combined totals across all strategies."""
    accounts = get_all_strategy_accounts()
    total_balance = sum(a["balance"] for a in accounts)
    total_equity  = sum(a["equity"]  for a in accounts)
    conn = get_connection()
    conn.execute("""
        UPDATE account SET balance=?, equity=?, updated_at=datetime('now') WHERE id=1
    """, (total_balance, total_equity))
    conn.commit()
    conn.close()
    return {"balance": total_balance, "equity": total_equity}

def get_active_strategy():
    conn = get_connection()
    row = conn.execute("SELECT * FROM strategy_versions WHERE is_active=1").fetchone()
    conn.close()
    return json.loads(row["rules"]) if row else {}

def get_open_trades(strategy_id: str = None):
    conn = get_connection()
    if strategy_id:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status='open' AND strategy_id=?", (strategy_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM trades WHERE status='open'").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def open_trade(symbol, side, entry_price, indicators, reasoning, regime,
               strategy_id: str = "ema_cross"):
    account  = get_strategy_account(strategy_id)
    strategy = get_active_strategy()

    max_open    = strategy.get("max_open_trades", 3)
    open_trades = get_open_trades(strategy_id)

    if len(open_trades) >= max_open:
        return None, f"Max open trades ({max_open}) reached for {strategy_id}"

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
        "SELECT version FROM strategy_versions WHERE is_active=1"
    ).fetchone()["version"]

    cur = conn.execute("""
        INSERT INTO trades
            (symbol, side, entry_price, quantity, stop_loss, take_profit,
             indicators, llm_reasoning, regime, strategy_ver, strategy_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol, side, entry_price, quantity,
        stop_loss, take_profit,
        json.dumps(indicators), reasoning, regime,
        strategy_ver, strategy_id
    ))

    conn.execute("""
        INSERT INTO signals (symbol, source, signal_type, payload, acted_on)
        VALUES (?, ?, ?, ?, 1)
    """, (symbol, f"strategy:{strategy_id}", side, json.dumps({"price": entry_price})))

    conn.commit()
    trade_id = cur.lastrowid
    conn.close()
    return trade_id, "ok"

def close_trade(trade_id, exit_price):
    conn = get_connection()
    trade = conn.execute(
        "SELECT * FROM trades WHERE id=? AND status='open'", (trade_id,)
    ).fetchone()

    if not trade:
        conn.close()
        return None, "Trade not found or already closed"

    trade    = dict(trade)
    quantity = trade["quantity"]
    strategy_id = trade.get("strategy_id", "ema_cross")

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

    # Update strategy account balance
    conn.execute("""
        UPDATE strategy_accounts
        SET balance = balance + ?, equity = equity + ?, updated_at=datetime('now')
        WHERE strategy_id = ?
    """, (pnl, pnl, strategy_id))

    conn.commit()
    conn.close()
    return pnl, "ok"

def update_equity(current_prices: dict):
    open_trades = get_open_trades()
    strategy_pnl = {sid: 0.0 for sid in STRATEGY_IDS}

    for t in open_trades:
        price = current_prices.get(t["symbol"])
        if not price:
            continue
        if t["side"] == "long":
            pnl = (price - t["entry_price"]) * t["quantity"]
        else:
            pnl = (t["entry_price"] - price) * t["quantity"]
        sid = t.get("strategy_id", "ema_cross")
        strategy_pnl[sid] = strategy_pnl.get(sid, 0) + pnl

    conn = get_connection()
    for sid, open_pnl in strategy_pnl.items():
        balance = conn.execute(
            "SELECT balance FROM strategy_accounts WHERE strategy_id=?", (sid,)
        ).fetchone()
        if balance:
            conn.execute("""
                UPDATE strategy_accounts SET equity=?, updated_at=datetime('now')
                WHERE strategy_id=?
            """, (round(balance["balance"] + open_pnl, 2), sid))
    conn.commit()
    conn.close()