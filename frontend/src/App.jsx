import { useState, useEffect, useCallback } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

const API = "https://trading-bot-production-8037.up.railway.app";

const fmt = (n) => n?.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtPct = (n) => (n >= 0 ? "+" : "") + n?.toFixed(2) + "%";

function usePoll(fn, ms = 5000) {
  useEffect(() => {
    fn();
    const id = setInterval(fn, ms);
    return () => clearInterval(id);
  }, []);
}

export default function App() {
  const [account, setAccount] = useState(null);
  const [trades, setTrades]   = useState([]);
  const [tab, setTab]         = useState("open");
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetchAll = useCallback(async () => {
    try {
      const [acc, trd] = await Promise.all([
        fetch(`${API}/trades/account`).then(r => r.json()),
        fetch(`${API}/trades/?limit=100`).then(r => r.json()),
      ]);
      setAccount(acc);
      setTrades(trd);
      setLastUpdate(new Date());
      setLoading(false);
    } catch (e) {
      console.error(e);
    }
  }, []);

  usePoll(fetchAll, 5000);

  const open   = trades.filter(t => t.status === "open");
  const closed = trades.filter(t => t.status === "closed");

  const equityHistory = closed
    .slice()
    .sort((a, b) => new Date(a.exit_at) - new Date(b.exit_at))
    .reduce((acc, t, i) => {
      const prev = acc[i - 1]?.equity ?? 10000;
      acc.push({ time: t.exit_at?.slice(5, 16), equity: +(prev + (t.pnl || 0)).toFixed(2) });
      return acc;
    }, []);

  if (loading) return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", background: "#0a0a0f", color: "#fff", fontFamily: "'IBM Plex Mono', monospace" }}>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 13, color: "#4ade80", letterSpacing: 4, marginBottom: 8 }}>CONNECTING</div>
        <div style={{ fontSize: 11, color: "#555" }}>loading bot data...</div>
      </div>
    </div>
  );

  const pnlColor = (v) => v > 0 ? "#4ade80" : v < 0 ? "#f87171" : "#888";

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0f", color: "#e2e8f0", fontFamily: "'IBM Plex Mono', monospace", padding: "24px" }}>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 32 }}>
        <div>
          <div style={{ fontSize: 11, color: "#4ade80", letterSpacing: 6, marginBottom: 6 }}>SPY DAY TRADING BOT</div>
          <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: -1 }}>Dashboard</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 10, color: "#555", marginBottom: 4 }}>LAST UPDATE</div>
          <div style={{ fontSize: 12, color: "#888" }}>{lastUpdate?.toLocaleTimeString()}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, justifyContent: "flex-end", marginTop: 6 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#4ade80", animation: "pulse 2s infinite" }} />
            <div style={{ fontSize: 11, color: "#4ade80" }}>LIVE</div>
          </div>
        </div>
      </div>

      {/* Account metrics */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12, marginBottom: 32 }}>
        {[
          { label: "EQUITY",       value: `$${fmt(account?.equity)}`,          sub: "current value" },
          { label: "BALANCE",      value: `$${fmt(account?.balance)}`,          sub: "cash available" },
          { label: "TOTAL P&L",    value: `$${fmt(account?.total_pnl)}`,        sub: fmtPct((account?.total_pnl / 10000) * 100), color: pnlColor(account?.total_pnl) },
          { label: "OPEN P&L",     value: `$${fmt(account?.open_pnl)}`,         sub: "unrealised",    color: pnlColor(account?.open_pnl) },
          { label: "WIN RATE",     value: `${account?.win_rate?.toFixed(1)}%`,  sub: `${account?.total_trades} trades` },
          { label: "OPEN TRADES",  value: open.length,                          sub: `max 3` },
        ].map(({ label, value, sub, color }) => (
          <div key={label} style={{ background: "#111118", border: "1px solid #1e1e2e", borderRadius: 8, padding: "16px" }}>
            <div style={{ fontSize: 9, color: "#555", letterSpacing: 3, marginBottom: 8 }}>{label}</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: color || "#e2e8f0", marginBottom: 4 }}>{value}</div>
            <div style={{ fontSize: 10, color: "#555" }}>{sub}</div>
          </div>
        ))}
      </div>

      {/* Equity curve */}
      {equityHistory.length > 1 && (
        <div style={{ background: "#111118", border: "1px solid #1e1e2e", borderRadius: 8, padding: 20, marginBottom: 32 }}>
          <div style={{ fontSize: 9, color: "#555", letterSpacing: 3, marginBottom: 16 }}>EQUITY CURVE</div>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={equityHistory}>
              <XAxis dataKey="time" tick={{ fontSize: 9, fill: "#555" }} axisLine={false} tickLine={false} />
              <YAxis domain={["auto", "auto"]} tick={{ fontSize: 9, fill: "#555" }} axisLine={false} tickLine={false} width={70} tickFormatter={v => `$${v.toLocaleString()}`} />
              <Tooltip
                contentStyle={{ background: "#0a0a0f", border: "1px solid #1e1e2e", borderRadius: 6, fontSize: 11 }}
                formatter={v => [`$${fmt(v)}`, "Equity"]}
              />
              <ReferenceLine y={10000} stroke="#333" strokeDasharray="4 4" />
              <Line type="monotone" dataKey="equity" stroke="#4ade80" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Trades table */}
      <div style={{ background: "#111118", border: "1px solid #1e1e2e", borderRadius: 8, overflow: "hidden" }}>
        <div style={{ display: "flex", borderBottom: "1px solid #1e1e2e" }}>
          {["open", "closed"].map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: "12px 24px", fontSize: 10, letterSpacing: 3, fontFamily: "inherit",
              background: tab === t ? "#1e1e2e" : "transparent",
              color: tab === t ? "#4ade80" : "#555",
              border: "none", cursor: "pointer", textTransform: "uppercase"
            }}>
              {t} ({t === "open" ? open.length : closed.length})
            </button>
          ))}
        </div>

        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #1e1e2e" }}>
                {["Symbol", "Side", "Entry", "Exit", "Qty", "P&L", "P&L%", "Regime", "Entry time", tab === "closed" ? "Exit time" : "Status"].map(h => (
                  <th key={h} style={{ padding: "10px 16px", textAlign: "left", color: "#555", letterSpacing: 2, fontSize: 9, fontWeight: 400 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(tab === "open" ? open : closed).length === 0 ? (
                <tr><td colSpan={10} style={{ padding: 32, textAlign: "center", color: "#555", fontSize: 11 }}>
                  {tab === "open" ? "No open trades — waiting for market signals" : "No closed trades yet"}
                </td></tr>
              ) : (tab === "open" ? open : closed).map(t => (
                <tr key={t.id} style={{ borderBottom: "1px solid #0f0f18" }}>
                  <td style={{ padding: "12px 16px", color: "#e2e8f0", fontWeight: 700 }}>{t.symbol}</td>
                  <td style={{ padding: "12px 16px" }}>
                    <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 700, background: t.side === "long" ? "#052e16" : "#2d0a0a", color: t.side === "long" ? "#4ade80" : "#f87171" }}>
                      {t.side?.toUpperCase()}
                    </span>
                  </td>
                  <td style={{ padding: "12px 16px", color: "#888" }}>${fmt(t.entry_price)}</td>
                  <td style={{ padding: "12px 16px", color: "#888" }}>{t.exit_price ? `$${fmt(t.exit_price)}` : "—"}</td>
                  <td style={{ padding: "12px 16px", color: "#888" }}>{t.quantity?.toFixed(4)}</td>
                  <td style={{ padding: "12px 16px", color: pnlColor(t.pnl), fontWeight: 700 }}>{t.pnl != null ? `$${fmt(t.pnl)}` : "—"}</td>
                  <td style={{ padding: "12px 16px", color: pnlColor(t.pnl_pct) }}>{t.pnl_pct != null ? fmtPct(t.pnl_pct) : "—"}</td>
                  <td style={{ padding: "12px 16px" }}>
                    <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 10, background: "#1e1e2e", color: "#888" }}>{t.regime || "—"}</span>
                  </td>
                  <td style={{ padding: "12px 16px", color: "#555" }}>{t.entry_at?.slice(5, 16)}</td>
                  <td style={{ padding: "12px 16px", color: tab === "closed" ? "#555" : "#4ade80", fontSize: tab === "open" ? 10 : 11 }}>
                    {tab === "closed" ? t.exit_at?.slice(5, 16) : "● OPEN"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #0a0a0f; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: #0a0a0f; }
        ::-webkit-scrollbar-thumb { background: #1e1e2e; border-radius: 2px; }
      `}</style>
    </div>
  );
}
