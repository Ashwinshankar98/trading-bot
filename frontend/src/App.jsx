import { useState, useEffect, useCallback } from "react";

const API = import.meta.env.VITE_API_URL || "https://trading-bot-production-8037.up.railway.app";

const STRATEGIES = {
  all: { name: "All Strategies", color: "#a78bfa", bg: "#1a1a3a" },
  ema_cross: { name: "EMA Cross + VWAP", color: "#60a5fa", bg: "#0d1a2a" },
  orb: { name: "Opening Range Breakout", color: "#4ade80", bg: "#0d2010" },
  ema_pullback: { name: "EMA 21 Pullback", color: "#fbbf24", bg: "#1f1500" },
};

function usePoll(fn, ms = 5000) {
  useEffect(() => { fn(); const id = setInterval(fn, ms); return () => clearInterval(id); }, [fn]);
}

function fmt(n, prefix = "$") {
  if (n == null) return "—";
  const v = parseFloat(n);
  return `${v >= 0 ? "" : "-"}${prefix}${Math.abs(v).toFixed(2)}`;
}

function pct(n) {
  if (n == null) return "—";
  return `${parseFloat(n) >= 0 ? "+" : ""}${parseFloat(n).toFixed(2)}%`;
}

function pnlColor(n) {
  if (n == null) return "#888";
  return parseFloat(n) > 0 ? "#4ade80" : parseFloat(n) < 0 ? "#f87171" : "#888";
}

// ── Strategy Card ─────────────────────────────────────────────────────────────
function StrategyCard({ s, active, onClick }) {
  const st = STRATEGIES[s.strategy_id] || STRATEGIES.all;
  const pnl = s.total_pnl || 0;
  const eq = s.equity || 10000;
  const bal = s.balance || 10000;
  const gain = eq - 10000;

  return (
    <div onClick={onClick} style={{
      background: active ? st.bg : "#0f0f1a",
      border: `1px solid ${active ? st.color : "#1e1e35"}`,
      borderRadius: 10, padding: "14px 16px", cursor: "pointer",
      transition: "all 0.15s",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 9, color: st.color, letterSpacing: 2, marginBottom: 3 }}>
            {s.strategy_id?.toUpperCase().replace("_", " ")}
          </div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#f1f5f9" }}>{s.name}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: pnlColor(gain) }}>
            {gain >= 0 ? "+" : ""}{fmt(gain)}
          </div>
          <div style={{ fontSize: 10, color: pnlColor(gain) }}>{pct(s.pnl_pct)}</div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 4, marginBottom: 8 }}>
        {[
          ["BALANCE", fmt(bal)],
          ["WIN RATE", s.total_trades > 0 ? `${s.win_rate}%` : "—"],
          ["TRADES", s.total_trades || 0],
        ].map(([k, v]) => (
          <div key={k} style={{ background: "#080810", borderRadius: 6, padding: "5px 7px" }}>
            <div style={{ fontSize: 8, color: "#555", letterSpacing: 1, marginBottom: 2 }}>{k}</div>
            <div style={{ fontSize: 12, color: "#e2e8f0", fontWeight: 600 }}>{v}</div>
          </div>
        ))}
      </div>
      {s.open_trades > 0 && (
        <div style={{ fontSize: 10, color: st.color, background: st.bg, padding: "2px 8px", borderRadius: 4, display: "inline-block" }}>
          {s.open_trades} open {s.open_trades === 1 ? "trade" : "trades"}
        </div>
      )}
    </div>
  );
}

// ── Trade Row ─────────────────────────────────────────────────────────────────
function TradeRow({ trade, onClose }) {
  const st       = STRATEGIES[trade.strategy_id] || STRATEGIES.all;
  const isOpen   = trade.status === "open";
  const isOption = trade.asset_class === "option";
  const closedPnl = trade.pnl ?? null;
  const livePnl   = trade.live_pnl ?? null;
  const displayPnl   = isOpen ? livePnl : closedPnl;
  const displayPnlPct = isOpen ? trade.live_pnl_pct : trade.pnl_pct;

  return (
    <div style={{
      background: "#0f0f1a", border: "0.5px solid #1e1e35", borderRadius: 8,
      padding: "12px 14px", marginBottom: 8,
      borderLeft: `3px solid ${st.color}`,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 6 }}>
        {/* Left */}
        <div>
          <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 5, flexWrap: "wrap" }}>
            <span style={{ background: st.bg, color: st.color, fontSize: 9, padding: "2px 7px", borderRadius: 4, fontWeight: 700, letterSpacing: 1 }}>
              {st.name}
            </span>
            {isOption && (
              <span style={{ background: "#1a0a2e", color: "#c084fc", fontSize: 9, padding: "2px 7px", borderRadius: 4, fontWeight: 700, letterSpacing: 1 }}>
                OPTION
              </span>
            )}
            <span style={{ background: trade.side === "long" ? "#052e16" : "#2d0a0a", color: trade.side === "long" ? "#4ade80" : "#f87171", fontSize: 10, padding: "2px 7px", borderRadius: 4, fontWeight: 700 }}>
              {trade.side?.toUpperCase()}
            </span>
            <span style={{ fontSize: 12, fontWeight: 700, color: "#f1f5f9" }}>
              {isOption ? trade.option_symbol : trade.symbol}
            </span>
            <span style={{ fontSize: 10, color: isOpen ? "#4ade80" : "#555", background: isOpen ? "#052e16" : "#1a1a1a", padding: "1px 7px", borderRadius: 10 }}>
              {isOpen ? "● OPEN" : "CLOSED"}
            </span>
          </div>

          {/* Stock fields */}
          {!isOption && (
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              <span style={{ fontSize: 11, color: "#aaa" }}>Entry: <b style={{ color: "#e2e8f0" }}>${trade.entry_price}</b></span>
              {trade.exit_price && <span style={{ fontSize: 11, color: "#aaa" }}>Exit: <b style={{ color: "#e2e8f0" }}>${trade.exit_price}</b></span>}
              <span style={{ fontSize: 11, color: "#aaa" }}>Qty: <b style={{ color: "#e2e8f0" }}>{trade.quantity}</b></span>
              {trade.stop_loss && <span style={{ fontSize: 11, color: "#f87171" }}>SL: ${trade.stop_loss}</span>}
              {trade.take_profit && <span style={{ fontSize: 11, color: "#4ade80" }}>TP: ${trade.take_profit}</span>}
            </div>
          )}

          {/* Options fields */}
          {isOption && (() => {
            let greeks = {};
            try { greeks = JSON.parse(trade.indicators || "{}"); } catch {}
            return (
              <div>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 4 }}>
                  <span style={{ fontSize: 11, color: "#aaa" }}>Strike: <b style={{ color: "#e2e8f0" }}>${trade.strike}</b></span>
                  <span style={{ fontSize: 11, color: "#aaa" }}>Expiry: <b style={{ color: "#e2e8f0" }}>{trade.option_expiry}</b></span>
                  <span style={{ fontSize: 11, color: "#c084fc" }}>{trade.option_type?.toUpperCase()}</span>
                  <span style={{ fontSize: 11, color: "#aaa" }}>Contracts: <b style={{ color: "#e2e8f0" }}>{trade.contracts}</b></span>
                  <span style={{ fontSize: 11, color: "#aaa" }}>SPY @ entry: <b style={{ color: "#e2e8f0" }}>${trade.underlying_price}</b></span>
                </div>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 4 }}>
                  <span style={{ fontSize: 11, color: "#aaa" }}>Entry premium: <b style={{ color: "#e2e8f0" }}>${trade.entry_premium}</b></span>
                  {trade.current_premium && <span style={{ fontSize: 11, color: "#aaa" }}>Current: <b style={{ color: "#e2e8f0" }}>${trade.current_premium}</b></span>}
                  {trade.exit_premium && <span style={{ fontSize: 11, color: "#aaa" }}>Exit: <b style={{ color: "#e2e8f0" }}>${trade.exit_premium}</b></span>}
                  <span style={{ fontSize: 11, color: "#aaa" }}>Cost: <b style={{ color: "#e2e8f0" }}>${((trade.entry_premium || 0) * 100 * (trade.contracts || 1)).toFixed(0)}</b></span>
                </div>
                {(greeks.delta || greeks.iv) && (
                  <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                    {greeks.delta != null && <span style={{ fontSize: 10, color: "#555" }}>Δ {greeks.delta}</span>}
                    {greeks.theta != null && <span style={{ fontSize: 10, color: "#f87171" }}>θ ${greeks.theta?.toFixed(3)}/day</span>}
                    {greeks.iv != null && <span style={{ fontSize: 10, color: "#555" }}>IV {(greeks.iv * 100).toFixed(1)}%</span>}
                    {greeks.vega != null && <span style={{ fontSize: 10, color: "#555" }}>ν ${greeks.vega?.toFixed(3)}/1%</span>}
                  </div>
                )}
              </div>
            );
          })()}

          <div style={{ fontSize: 10, color: "#555", marginTop: 4 }}>
            {trade.entry_at?.slice(0, 16)} UTC
            {trade.exit_at ? ` → ${trade.exit_at?.slice(0, 16)} UTC` : ""}
          </div>
        </div>

        {/* Right — P&L */}
        <div style={{ textAlign: "right" }}>
          {displayPnl != null ? (
            <>
              <div style={{ fontSize: 20, fontWeight: 700, color: pnlColor(displayPnl) }}>
                {displayPnl >= 0 ? "+" : ""}{fmt(displayPnl)}
              </div>
              <div style={{ fontSize: 11, color: pnlColor(displayPnl) }}>
                {pct(displayPnlPct)}
              </div>
              {isOpen && <div style={{ fontSize: 9, color: "#555", marginTop: 2 }}>live</div>}
            </>
          ) : (
            <div style={{ fontSize: 11, color: "#555" }}>{isOpen ? "fetching..." : "—"}</div>
          )}
          {isOpen && (
            <button onClick={() => onClose(trade.id)} style={{
              marginTop: 6, background: "#2d0a0a", border: "0.5px solid #f87171",
              color: "#f87171", borderRadius: 5, padding: "4px 12px", fontSize: 10,
              fontFamily: "inherit", cursor: "pointer", letterSpacing: 1,
            }}>
              CLOSE →
            </button>
          )}
        </div>
      </div>

      {/* Reasoning */}
      {trade.llm_reasoning && (
        <div style={{ marginTop: 8, padding: "6px 10px", background: "#080810", borderRadius: 6, fontSize: 10, color: "#666", lineHeight: 1.5 }}>
          {trade.llm_reasoning.slice(0, 200)}{trade.llm_reasoning.length > 200 ? "..." : ""}
        </div>
      )}
    </div>
  );
}

// ── Strategy × Ticker Matrix ──────────────────────────────────────────────────
function PnlMatrix({ matrix }) {
  const symbols    = [...new Set(matrix.map(r => r.symbol))].sort();
  const stratIds   = ["ema_cross", "orb", "ema_pullback"];
  const stratLabels = { ema_cross: "EMA Cross", orb: "ORB", ema_pullback: "EMA Pullback" };

  if (matrix.length === 0) return null;

  const cell = (sid, sym) => matrix.find(r => r.strategy_id === sid && r.symbol === sym);

  return (
    <div style={{ padding: "0 24px 16px" }}>
      <div style={{ fontSize: 9, color: "#555", letterSpacing: 3, marginBottom: 10 }}>
        STRATEGY × TICKER MATRIX
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: "6px 10px", color: "#555", fontSize: 9, letterSpacing: 2, borderBottom: "0.5px solid #1e1e35" }}>
                STRATEGY
              </th>
              {symbols.map(sym => (
                <th key={sym} style={{ textAlign: "center", padding: "6px 14px", color: "#a78bfa", fontSize: 11, fontWeight: 700, borderBottom: "0.5px solid #1e1e35", minWidth: 120 }}>
                  {sym}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {stratIds.map(sid => {
              const st = STRATEGIES[sid];
              return (
                <tr key={sid}>
                  <td style={{ padding: "8px 10px", color: st?.color || "#aaa", fontSize: 10, fontWeight: 700, borderBottom: "0.5px solid #0f0f1a", whiteSpace: "nowrap" }}>
                    {stratLabels[sid]}
                  </td>
                  {symbols.map(sym => {
                    const c = cell(sid, sym);
                    if (!c) return (
                      <td key={sym} style={{ textAlign: "center", padding: "8px 14px", color: "#333", borderBottom: "0.5px solid #0f0f1a" }}>
                        —
                      </td>
                    );
                    const pnl = c.total_pnl || 0;
                    return (
                      <td key={sym} style={{ textAlign: "center", padding: "8px 14px", borderBottom: "0.5px solid #0f0f1a", background: "#0a0a14" }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: pnlColor(pnl) }}>
                          {pnl >= 0 ? "+" : ""}{fmt(pnl)}
                        </div>
                        <div style={{ fontSize: 9, color: "#555", marginTop: 2 }}>
                          {c.trades}T · {c.win_rate}% WR
                        </div>
                        {c.open_trades > 0 && (
                          <div style={{ fontSize: 9, color: "#4ade80", marginTop: 1 }}>
                            {c.open_trades} open
                          </div>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}


// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [account, setAccount] = useState(null);
  const [strategies, setStrategies] = useState([]);
  const [trades, setTrades] = useState([]);
  const [matrix, setMatrix] = useState([]);
  const [stratFilter, setStratFilter] = useState("all");
  const [statusTab, setStatusTab] = useState("open");
  const [lastUpdate, setLastUpdate] = useState(null);
  const [closePrice, setClosePrice] = useState({});

  const fetchAll = useCallback(async () => {
    try {
      const [acct, strats, tradeData, matrixData] = await Promise.all([
        fetch(`${API}/trades/account`).then(r => r.json()),
        fetch(`${API}/trades/strategies`).then(r => r.json()),
        fetch(`${API}/trades/?limit=200`).then(r => r.json()),
        fetch(`${API}/trades/matrix`).then(r => r.json()),
      ]);
      setAccount(acct);
      setStrategies(Array.isArray(strats) ? strats : []);
      setTrades(Array.isArray(tradeData) ? tradeData : []);
      setMatrix(Array.isArray(matrixData) ? matrixData : []);
      setLastUpdate(new Date());
    } catch (e) { console.error(e); }
  }, []);

  usePoll(fetchAll, 5000);

  const handleClose = async (trade_id) => {
    const price = parseFloat(closePrice[trade_id] || prompt(`Exit price for trade #${trade_id}?`));
    if (!price) return;
    await fetch(`${API}/trades/${trade_id}/close?price=${price}`, { method: "POST" });
    fetchAll();
  };

  const filtered = trades.filter(t => {
    const stratOk = stratFilter === "all" || t.strategy_id === stratFilter;
    const statusOk = statusTab === "all" || t.status === statusTab;
    return stratOk && statusOk;
  });

  const totalGain = (account?.equity || 30000) - 30000;
  const startingCap = 30000;

  return (
    <div style={{ minHeight: "100vh", background: "#080810", color: "#e2e8f0", fontFamily: "'IBM Plex Mono', monospace" }}>

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div style={{ padding: "20px 24px 16px", borderBottom: "0.5px solid #1e1e35", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <div>
          <div style={{ fontSize: 9, color: "#a78bfa", letterSpacing: 6, marginBottom: 4 }}>TRADING BOT</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>Paper Trading Dashboard</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 28, fontWeight: 700, color: pnlColor(totalGain) }}>
            {totalGain >= 0 ? "+" : ""}{fmt(totalGain)}
          </div>
          <div style={{ fontSize: 11, color: pnlColor(totalGain) }}>
            {pct((totalGain / startingCap) * 100)} total return
          </div>
          <div style={{ fontSize: 9, color: "#555", marginTop: 2 }}>
            {lastUpdate?.toLocaleTimeString()} · refreshes 5s
          </div>
        </div>
      </div>

      {/* ── Portfolio summary bar ───────────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, padding: "14px 24px" }}>
        {[
          ["TOTAL CAPITAL", fmt(account?.equity || 30000), "#a78bfa"],
          ["TOTAL P&L", fmt(account?.total_pnl), pnlColor(account?.total_pnl)],
          ["WIN RATE", account?.total_trades > 0 ? `${account.win_rate}%` : "—", "#4ade80"],
          ["TOTAL TRADES", account?.total_trades || 0, "#60a5fa"],
        ].map(([label, val, color]) => (
          <div key={label} style={{ background: "#0f0f1a", border: "0.5px solid #1e1e35", borderRadius: 8, padding: "12px 14px" }}>
            <div style={{ fontSize: 8, color: "#555", letterSpacing: 2, marginBottom: 4 }}>{label}</div>
            <div style={{ fontSize: 18, fontWeight: 700, color }}>{val}</div>
          </div>
        ))}
      </div>

      {/* ── Strategy breakdown cards ────────────────────────────────────────── */}
      <div style={{ padding: "0 24px 16px" }}>
        <div style={{ fontSize: 9, color: "#555", letterSpacing: 3, marginBottom: 10 }}>STRATEGY PERFORMANCE</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
          {strategies.map(s => (
            <StrategyCard
              key={s.strategy_id}
              s={s}
              active={stratFilter === s.strategy_id}
              onClick={() => setStratFilter(prev => prev === s.strategy_id ? "all" : s.strategy_id)}
            />
          ))}
        </div>
      </div>

      {/* ── Strategy × Ticker Matrix ───────────────────────────────────────── */}
      <PnlMatrix matrix={matrix} />

      {/* ── Trade list ─────────────────────────────────────────────────────── */}
      <div style={{ padding: "0 24px 24px" }}>
        {/* Filter bar */}
        <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
          <div style={{ fontSize: 9, color: "#555", letterSpacing: 3, marginRight: 4 }}>FILTER:</div>

          {/* Status tabs */}
          {["open", "closed", "all"].map(s => (
            <button key={s} onClick={() => setStatusTab(s)} style={{
              padding: "4px 12px", fontSize: 9, letterSpacing: 2, fontFamily: "inherit",
              background: statusTab === s ? "#1e1e35" : "transparent",
              color: statusTab === s ? "#a78bfa" : "#555",
              border: `0.5px solid ${statusTab === s ? "#a78bfa" : "#1e1e35"}`,
              borderRadius: 20, cursor: "pointer", textTransform: "uppercase",
            }}>{s}</button>
          ))}

          <div style={{ width: 1, height: 16, background: "#1e1e35", margin: "0 4px" }} />

          {/* Strategy filter */}
          <button onClick={() => setStratFilter("all")} style={{
            padding: "4px 12px", fontSize: 9, letterSpacing: 2, fontFamily: "inherit",
            background: stratFilter === "all" ? "#1e1e35" : "transparent",
            color: stratFilter === "all" ? "#a78bfa" : "#555",
            border: `0.5px solid ${stratFilter === "all" ? "#a78bfa" : "#1e1e35"}`,
            borderRadius: 20, cursor: "pointer",
          }}>ALL STRATEGIES</button>

          {strategies.map(s => {
            const st = STRATEGIES[s.strategy_id];
            return (
              <button key={s.strategy_id} onClick={() => setStratFilter(prev => prev === s.strategy_id ? "all" : s.strategy_id)} style={{
                padding: "4px 12px", fontSize: 9, letterSpacing: 1, fontFamily: "inherit",
                background: stratFilter === s.strategy_id ? st.bg : "transparent",
                color: stratFilter === s.strategy_id ? st.color : "#555",
                border: `0.5px solid ${stratFilter === s.strategy_id ? st.color : "#1e1e35"}`,
                borderRadius: 20, cursor: "pointer", whiteSpace: "nowrap",
              }}>{st?.name || s.strategy_id}</button>
            );
          })}

          <span style={{ marginLeft: "auto", fontSize: 9, color: "#555" }}>
            {filtered.length} trade{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Trades */}
        {filtered.length === 0 ? (
          <div style={{ textAlign: "center", padding: 40, color: "#555", fontSize: 12 }}>
            <div style={{ marginBottom: 8 }}>No trades yet</div>
            <div style={{ fontSize: 10, color: "#333" }}>
              Test the pipeline: POST /webhook/test
            </div>
          </div>
        ) : (
          filtered.map(t => (
            <TradeRow key={t.id} trade={t} onClose={handleClose} />
          ))
        )}
      </div>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #080810; }
      `}</style>
    </div>
  );
}