import { useState, useEffect } from "react";

const API = "";
function statusColor(status) {
  if (status === "executed") return "#16a34a";           // green
  if (status === "pending_confirmation") return "#d97706"; // amber
  if (status === "failed") return "#dc2626";             // red
  return "#6b7280";                                       // grey (reads)
}

export default function App() {
  const [logs, setLogs] = useState([]);
  const [stats, setStats] = useState(null);

  async function loadData() {
    const [auditRes, statsRes] = await Promise.all([
      fetch(`${API}/api/audit`),
      fetch(`${API}/api/stats`),
    ]);
    setLogs((await auditRes.json()).logs);
    setStats(await statsRes.json());
  }

  useEffect(() => {
    loadData();                                  // load once on mount
    const t = setInterval(loadData, 5000);       // auto-refresh every 5s
    return () => clearInterval(t);               // cleanup on unmount
  }, []);

  return (
    <div style={{ fontFamily: "system-ui", maxWidth: 1000, margin: "2rem auto" }}>
      <h1>MCP Infra Hub — AI Action Feed</h1>

      {stats && (
        <p style={{ color: "#374151" }}>
          Total AI actions logged: <strong>{stats.total_actions}</strong>
        </p>
      )}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "2px solid #e5e7eb" }}>
            <th>ID</th><th>Tool</th><th>Status</th><th>Arguments</th><th>Time</th>
          </tr>
        </thead>
        <tbody>
          {logs.map((row) => (
            <tr key={row.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
              <td>{row.id}</td>
              <td>{row.tool_name}</td>
              <td>
                <span style={{
                  color: "white", background: statusColor(row.status),
                  padding: "2px 8px", borderRadius: 12, fontSize: 12,
                }}>
                  {row.status}
                </span>
              </td>
              <td><code>{JSON.stringify(row.arguments)}</code></td>
              <td>{new Date(row.called_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

