import { useState, useEffect, useRef } from "react";
import "./App.css";

const pill = (s) => ({
  executed:{bg:"#14331f",c:"#22c55e"}, pending_confirmation:{bg:"#3a2c0e",c:"#f59e0b"},
  failed:{bg:"#3a1414",c:"#ef4444"}, success:{bg:"#16233f",c:"#3b82f6"},
  declined:{bg:"#2b2030",c:"#c084fc"},
}[s] || {bg:"#1e2740",c:"#94a3b8"});

const ago = (t) => {
  const s = Math.floor((Date.now() - new Date(t)) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s/60)}m ago`;
  return `${Math.floor(s/3600)}h ago`;
};

function humanResult(tool, resultStr) {
  if (!resultStr) return ["No result recorded."];
  let d; try { d = JSON.parse(resultStr); } catch { return [resultStr]; }
  const L = [];
  if (tool === "get_gke_cluster_status") {
    const c = (d.clusters && d.clusters[0]) || {};
    if (d.project) L.push(`Project: ${d.project}`);
    L.push(`Clusters found: ${d.cluster_count ?? (d.clusters?.length || 0)}`);
    if (c.name) L.push(`Cluster: ${c.name}`);
    if (c.status) L.push(`Status: ${c.status}`);
    if (c.node_count != null) L.push(`Nodes running: ${c.node_count}`);
    if (c.location) L.push(`Location: ${c.location}`);
    if (c.k8s_version) L.push(`Kubernetes version: ${c.k8s_version}`);
    return L;
  }
  if (tool === "scale_gke_node_pool") {
    if (d.action) L.push(`Action: ${d.action}`);
    if (d.change) L.push(`Change: ${d.change}`);
    if (d.node_pool) L.push(`Node pool: ${d.node_pool}`);
    if (d.cluster) L.push(`Cluster: ${d.cluster}`);
    if (d.confirm_token) L.push(`Awaiting human confirmation`);
    if (d.status) L.push(`Result: ${d.status}`);
    if (d.reason) L.push(`Reason: ${d.reason}`);
    if (d.error) L.push(`Error: ${d.error}`);
    return L;
  }
  return Object.entries(d).map(([k, v]) =>
    `${k.replace(/_/g, " ")}: ${typeof v === "object" ? JSON.stringify(v) : v}`);
}


export default function App() {
  const [logs, setLogs] = useState([]);
  const [stats, setStats] = useState({});
  const [health, setHealth] = useState({});
  const [msgs, setMsgs] = useState([{role:"ai", text:"Hi! Ask me about your infrastructure — e.g. \"what's my cluster status?\" or \"scale default-pool to 4 nodes\"."}]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [approval, setApproval] = useState(null);
  const [filter, setFilter] = useState("all");
  const endRef = useRef(null);
  const [openId, setOpenId] = useState(null);


  const load = async () => {
    const [a, s, h] = await Promise.all([
      fetch("/api/audit").then(r=>r.json()),
      fetch("/api/stats").then(r=>r.json()),
      fetch("/api/health").then(r=>r.json()),
    ]);
    setLogs(a.logs || []); setStats(s); setHealth(h);
  };
  useEffect(() => { load(); const t=setInterval(load,4000); return ()=>clearInterval(t); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({behavior:"smooth"}); }, [msgs]);

  const handle = (res) => {
    if (res.type === "approval_required") { setApproval(res); }
    else { setMsgs(m => [...m, {role:"ai", text:res.text}]); }
  };

  const sendMsg = async () => {
    if (!input.trim() || busy) return;
    const text = input; setInput(""); setBusy(true);
    setMsgs(m => [...m, {role:"me", text}]);
    try {
      const res = await fetch("/ai/chat",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({message:text})}).then(r=>r.json());
      handle(res);
    } catch { setMsgs(m => [...m, {role:"ai", text:"Error reaching the AI host."}]); }
    setBusy(false); load();
  };

  const decide = async (approved) => {
    const a = approval; setApproval(null); setBusy(true);
    setMsgs(m => [...m, {role:"tool", text:`${approved?"✅ Approved":"❌ Denied"}: ${a.tool}`}]);
    const res = await fetch("/ai/approve",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({approved})}).then(r=>r.json());
    handle(res); setBusy(false); load();
  };

  const shown = logs.filter(l =>
    filter==="all" ? true :
    filter==="writes" ? l.action_type==="write" || l.tool_name==="scale_gke_node_pool" :
    filter==="reads" ? l.action_type==="read" :
    l.status==="pending_confirmation");

  const up = health.status === "RUNNING";

  return (
    <div className="app">
      {/* LEFT: CHAT */}
      <div className="chat">
        <div className="chat-head">🤖 <span>Infra</span> Copilot</div>
        <div className="msgs">
          {msgs.map((m,i)=>(<div key={i} className={`bubble ${m.role}`}>{m.text}</div>))}
          {busy && <div className="bubble ai">…thinking</div>}
          <div ref={endRef}/>
        </div>
        <div className="composer">
          <input value={input} onChange={e=>setInput(e.target.value)}
            onKeyDown={e=>e.key==="Enter"&&sendMsg()} placeholder="Ask about your infrastructure…"/>
          <button onClick={sendMsg}>Send</button>
        </div>
      </div>

      {/* RIGHT: OBSERVABILITY */}
      <div className="main">
        <h1 className="h1">MCP Infrastructure Hub</h1>

        <div className="health" style={{borderColor: up?"#1c7d3f":"#3a1414"}}>
          <div className="dot" style={{color: up?"var(--green)":"var(--grey)"}}/>
          <div>
            <div style={{fontWeight:800}}>
              {health.known ? `${health.name} — ${health.status}` : "Cluster status unknown"}
            </div>
            <div style={{color:"var(--muted)",fontSize:13}}>
              {health.known ? `${health.nodes} nodes · ${health.location}` : "Ask the copilot for status"}
            </div>
          </div>
        </div>

        <div className="cards">
          {[["total","Total Actions","var(--blue)"],["executed","Writes Executed","var(--green)"],
            ["pending","Pending Approvals","var(--amber)"],["failed","Failures","var(--red)"]]
            .map(([k,l,c])=>(
            <div className="card" key={k}>
              <div className="n" style={{color:c}}>{stats[k] ?? 0}</div>
              <div className="l">{l}</div>
            </div>))}
        </div>

        <div style={{display:"flex",gap:8,marginBottom:12}}>
          {["all","reads","writes","pending"].map(f=>(
            <button key={f} onClick={()=>setFilter(f)}
              style={{background:filter===f?"var(--blue)":"var(--panel2)",color:"#fff",
                border:"1px solid var(--line)",padding:"6px 14px",borderRadius:999,cursor:"pointer",
                textTransform:"capitalize",fontSize:13}}>{f}</button>))}
        </div>
        <div className="feed">
          <div className="row head"><div>ID</div><div>Question / Action</div><div>Status</div><div>When</div></div>
          {shown.map(l=>{
            const p=pill(l.status); const open=openId===l.id;
            return (
              <div key={l.id}>
                <div className="row" style={{cursor:"pointer"}} onClick={()=>setOpenId(open?null:l.id)}>
                  <div className="mono" style={{color:"var(--muted)"}}>#{l.id}</div>
                  <div>
                    <div>{l.user_prompt ? `💬 "${l.user_prompt}"` : <span style={{color:"var(--muted)"}}>(direct tool call)</span>}</div>
                    <div className="mono" style={{color:"var(--muted)",fontSize:12,marginTop:3}}>→ {l.tool_name} {JSON.stringify(l.arguments)}</div>
                  </div>
                  <div><span className="pill" style={{background:p.bg,color:p.c}}>{l.status}</span></div>
                  <div style={{color:"var(--muted)",fontSize:13}}>{ago(l.called_at)} <span style={{marginLeft:6}}>{open?"▲":"▼"}</span></div>
                </div>
                {open && (
                  <div style={{padding:"10px 18px 16px 78px",background:"var(--bg)",borderTop:"1px solid var(--line)"}}>
                    <div style={{color:"var(--muted)",fontSize:11,textTransform:"uppercase",letterSpacing:".5px",marginBottom:8}}>Result</div>
                    <div style={{lineHeight:1.8,fontSize:14}}>
                      {humanResult(l.tool_name, l.result).map((line,i)=>(<div key={i}>{line}</div>))}
                    </div>

                  </div>
                )}
              </div>
            );
          })}
        </div>

      </div>

      {/* APPROVAL MODAL */}
      {approval && (
        <div className="overlay">
          <div className="modal">
            <h3><span className="warn">⚠ Approval required</span></h3>
            <p>The AI wants to <b>execute a write action</b> on your infrastructure:</p>
            <div className="mono" style={{background:"var(--bg)",padding:12,borderRadius:10,margin:"12px 0"}}>
              {approval.tool}<br/>
              node_pool: {approval.args.node_pool}<br/>
              → node_count: <b style={{color:"var(--amber)"}}>{approval.args.node_count}</b>
            </div>
            <div className="btns">
              <button className="btn-ok" onClick={()=>decide(true)}>Approve</button>
              <button className="btn-no" onClick={()=>decide(false)}>Deny</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

