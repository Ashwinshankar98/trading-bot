import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent / "trading_bot.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.executescript("""
    -- ── Account ─────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS account (
        id          INTEGER PRIMARY KEY DEFAULT 1,
        balance     REAL    NOT NULL DEFAULT 10000.0,
        equity      REAL    NOT NULL DEFAULT 10000.0,
        updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    INSERT OR IGNORE INTO account (id, balance, equity) VALUES (1, 10000.0, 10000.0);

    -- ── Trades ──────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS trades (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol          TEXT    NOT NULL,
        side            TEXT    NOT NULL CHECK(side IN ('long','short')),
        status          TEXT    NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
        entry_price     REAL    NOT NULL,
        exit_price      REAL,
        quantity        REAL    NOT NULL,
        stop_loss       REAL,
        take_profit     REAL,
        pnl             REAL,
        pnl_pct         REAL,
        entry_at        TEXT    NOT NULL DEFAULT (datetime('now')),
        exit_at         TEXT,
        strategy_ver    INTEGER NOT NULL DEFAULT 1,
        indicators      TEXT,   -- JSON snapshot of indicator values at entry
        llm_reasoning   TEXT,   -- Claude's reasoning for this trade
        regime          TEXT    -- trending / ranging / volatile
    );

    -- ── Trade journal (post-mortem per closed trade) ─────────────
    CREATE TABLE IF NOT EXISTS trade_journal (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id    INTEGER NOT NULL REFERENCES trades(id),
        what_worked TEXT,
        what_failed TEXT,
        market_notes TEXT,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- ── Strategy versions ────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS strategy_versions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        version         INTEGER NOT NULL UNIQUE,
        rules           TEXT    NOT NULL,  -- JSON: indicator weights, thresholds
        rationale       TEXT,              -- Claude's written explanation
        win_rate        REAL,
        avg_winner      REAL,
        avg_loser       REAL,
        sample_size     INTEGER,
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        is_active       INTEGER NOT NULL DEFAULT 0
    );

    INSERT OR IGNORE INTO strategy_versions
        (version, rules, rationale, is_active)
    VALUES (
        1,
        '{
            "indicators": {
                "rsi": {"weight": 0.25, "oversold": 30, "overbought": 70},
                "macd": {"weight": 0.25},
                "ema_cross": {"weight": 0.20, "fast": 9, "slow": 21},
                "vwap": {"weight": 0.15},
                "bollinger": {"weight": 0.15, "period": 20, "std": 2}
            },
            "entry_threshold": 0.60,
            "position_size_pct": 0.10,
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.04,
            "max_open_trades": 3,
            "regime_filters": {
                "trending":  ["ema_cross", "macd", "vwap"],
                "ranging":   ["rsi", "bollinger"],
                "volatile":  []
            }
        }',
        'Initial strategy — baseline settings based on commonly used indicator weights.',
        1
    );

    -- ── Signals log ─────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS signals (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol      TEXT NOT NULL,
        source      TEXT NOT NULL,   -- tradingview / internal
        signal_type TEXT NOT NULL,   -- buy / sell / close
        payload     TEXT,            -- raw JSON from webhook
        acted_on    INTEGER DEFAULT 0,
        received_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)

    conn.commit()
    conn.close()
    print(f"[DB] Initialised at {DB_PATH}")

if __name__ == "__main__":
    init_db()
