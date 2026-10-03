import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, Link, useParams } from "react-router-dom";
import "./App.css";

const API = import.meta.env.VITE_API || "http://localhost:8000";
const get = (p) => fetch(API + p).then((r) => r.json());
const post = (p, body) =>
  fetch(API + p, { method: "POST", headers: { "Content-Type": "application/json" }, body: body && JSON.stringify(body) })
    .then((r) => r.json());
const LABEL = {
  clinical_urgent: "CLINICAL", not_authorised: "NOT AUTHORISED", ambiguous_patient: "AMBIGUOUS PATIENT",
  medical_advice: "MEDICAL ADVICE", out_of_scope: "OUT OF SCOPE"
};

function Queue() {
  const [stats, setStats] = useState({}), [rows, setRows] = useState([]);
  const load = () => { get("/stats").then(setStats); get("/handoffs").then(setRows); };
  useEffect(load, []);
  const pct = stats.total ? Math.round((100 * stats.completed) / stats.total) : 0;
  return (
    <div>
      <h1>Handoff Queue <span className="pill">{stats.open} OPEN</span></h1>
      <p className="muted">Sunrise Clinic, Dehradun — conversations the agent escalated</p>
      <div className="cards">
        <div className="card"><small>CONVERSATIONS</small><b>{stats.total}</b></div>
        <div className="card"><small>COMPLETED BY AGENT</small><b>{stats.completed}</b><i>{pct}%</i></div>
        <div className="card"><small>ESCALATED</small><b>{stats.escalated}</b><i>{stats.open} still open</i></div>
        <div className="card"><small>URGENT</small><b>{stats.urgent}</b><i>clinical, unresolved</i></div>
      </div>
      <h3>Open handoffs</h3>
      <table>
        <thead><tr><th>CONVERSATION</th><th>CALLER SAID</th><th>REASON</th><th></th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.conversation_id}>
              <td><Link to={`/c/${r.conversation_id}`}>{r.conversation_id}</Link></td>
              <td>“{r.caller_said}”</td>
              <td><span className={`badge ${r.reason}`}>{LABEL[r.reason]}</span></td>
              <td><button onClick={() => post(`/handoffs/${r.conversation_id}/resolve`).then(load)}>Resolve</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Detail() {
  const { id } = useParams();
  const [c, setC] = useState(null), [stable, setStable] = useState(null);
  useEffect(() => { get("/conversations").then((all) => setC(all[id])); }, [id]);
  useEffect(() => {
    if (!c) return;
    Promise.all([1, 2, 3].map(() => post("/agent/run", { conversation_id: id, today: "2026-10-01", turns: c.turns })))
      .then((rs) => setStable(new Set(rs.map((r) => r.terminal_state + r.escalation_reason)).size === 1));
  }, [c]);
  if (!c) return <p>Loading…</p>;
  const r = c.result;
  return (
    <div>
      <h1>Conversation {id} <span className={`pill ${r.escalation_reason || ""}`}>{r.terminal_state.toUpperCase()}</span></h1>
      <div className="two">
        <div>
          <h3>Transcript and tool calls</h3>
          {c.turns.map((t, i) => <div key={i} className="bubble caller"><small>CALLER</small> {t}</div>)}
          {r.tool_calls.map((t, i) => (
            <div key={i} className="bubble tool"><small>TOOL</small>
              <code>{t.name}({JSON.stringify(t.arguments)})</code>
              <code>→ {JSON.stringify(t.result).slice(0, 300)}</code></div>
          ))}
          <div className="bubble agent"><small>AGENT</small> {r.reply}</div>
          {r.terminal_state === "escalated" && <div className="alert">Booking flow abandoned. No appointment was created.</div>}
        </div>
        <div className="card">
          <h3>Outcome</h3>
          {["terminal_state", "escalation_reason", "patient_id", "appointment_id"].map((k) => (
            <div key={k} className="kv"><span>{k}</span><code>{String(r[k])}</code></div>))}
          <div className="kv"><span>tool_calls</span><code>{r.tool_calls.length}</code></div>
          <div className="kv"><span>turns</span><code>{r.metrics.turns}</code></div>
          <div className="kv"><span>tokens</span><code>{r.metrics.tokens}</code></div>
          <p>DETERMINISM: {stable === null ? "checking…" : stable ? "STABLE across 3 runs" : "UNSTABLE"}</p>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="layout">
        <nav>
          <b>Sunrise Clinic</b>
          <NavLink to="/">Handoff Queue</NavLink>
          <NavLink to="/c/cv_0011">Conversation Detail</NavLink>
        </nav>
        <main><Routes><Route path="/" element={<Queue />} /><Route path="/c/:id" element={<Detail />} /></Routes></main>
      </div>
    </BrowserRouter>
  );
}