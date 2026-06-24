import { useEffect, useRef, useState } from "react";
import {
  approveMutation, getState, rejectMutation, resetDemo, startReplay, subscribe,
} from "./lib/api";
import { INTERNAL_COLUMNS, TRACKER_COLUMNS } from "./lib/types";
import type { Mutation, TrackerRow } from "./lib/types";

interface LogLine { t: string; msg: string; }

export default function App() {
  const [rows, setRows] = useState<TrackerRow[]>([]);
  const [pending, setPending] = useState<Mutation[]>([]);
  const [log, setLog] = useState<LogLine[]>([]);
  const [connected, setConnected] = useState(false);
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [flash, setFlash] = useState<Set<string>>(new Set());
  const logEndRef = useRef<HTMLDivElement>(null);

  function addLog(msg: string) {
    setLog((l) => [...l, { t: new Date().toLocaleTimeString(), msg }].slice(-200));
  }

  useEffect(() => {
    getState().then((s) => { setRows(s.rows); setPending(s.pending); setRunning(s.replay_running); });
    const off = subscribe(
      (type, data) => {
        setConnected(true);
        switch (type) {
          case "hello":
          case "state":
            if (data.rows) setRows(data.rows);
            if (data.pending) setPending(data.pending);
            if (typeof data.replay_running === "boolean") setRunning(data.replay_running);
            break;
          case "proposal":
            setPending((p) => [...p.filter((m) => m.mutation_id !== data.mutation_id), data]);
            addLog(`proposed ${data.classification}: ${data.agent_note}`);
            break;
          case "recon":
            setSummary(data.summary);
            addLog(`reconciled ${data.shipment_id}: ${data.summary}`);
            break;
          case "mutation_status":
            setPending((p) => p.map((m) => m.mutation_id === data.mutation_id ? { ...m, status: data.status } : m)
                                .filter((m) => m.status === "pending"));
            break;
          case "committed": {
            const rid = data.row?.row_id;
            if (rid) {
              setFlash((f) => new Set(f).add(rid));
              setTimeout(() => setFlash((f) => { const n = new Set(f); n.delete(rid); return n; }), 1800);
            }
            addLog(`committed: ${data.row?.customer_po ?? rid} (${data.classification})`);
            break;
          }
          case "email_received": addLog(`email in: ${data.subject ?? data.packet_id}`); break;
          case "triage": addLog(`triage: ${data.decision} — ${data.reason ?? ""}`); break;
          case "extract": addLog(`extract: ${data.message ?? ""}`); break;
          case "log": addLog(data.message ?? ""); break;
          case "done": setRunning(false); addLog("replay complete."); break;
          case "error": addLog(`ERROR: ${data.message ?? "unknown"}`); break;
        }
      },
      () => setConnected(false),
    );
    return off;
  }, []);

  useEffect(() => { logEndRef.current?.scrollIntoView(); }, [log]);

  async function onReplay(mode: "live" | "replay") {
    setRunning(true);
    try { await startReplay(mode); } catch (e) { addLog(String(e)); setRunning(false); }
  }
  async function onReset() {
    await resetDemo(); setPending([]); setSummary(null); setLog([]);
    const s = await getState(); setRows(s.rows);
  }

  const visiblePending = pending.filter((m) => m.status === "pending");

  return (
    <div className="app">
      <div className="topbar">
        <h1>Carrystar · Real-Time Order Agent</h1>
        <span className="sub">v1 skeleton — live order reconciliation</span>
        <div className="spacer" />
        <span className={`dot${connected ? " live" : ""}`} />
        <span className="sub">{connected ? "stream live" : "connecting…"}</span>
        <button className="primary" disabled={running} onClick={() => onReplay("replay")}>▶ Replay (cached)</button>
        <button className="ghost" disabled={running} onClick={() => onReplay("live")}>Run live</button>
        <button className="ghost" onClick={onReset}>Reset</button>
      </div>

      <div className="body">
        <div className="main">
          {summary && <div className="summary-banner">⚠ {summary}</div>}
          <h2 className="section-title">Tracker — {rows.length} rows · {rows.reduce((a, r) => a + r.ctn_qty, 0)} ctn</h2>
          <table>
            <thead>
              <tr>{TRACKER_COLUMNS.map((c) => (
                <th key={c} className={INTERNAL_COLUMNS.includes(c) ? "internal" : ""}>{c}</th>
              ))}</tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.row_id} className={`row-${r.status_color}${flash.has(r.row_id) ? " just-committed" : ""}`}>
                  {TRACKER_COLUMNS.map((c) => (
                    <td key={c}
                        className={`${c === "ctn_qty" || c === "pc_qty" ? "num" : ""}${INTERNAL_COLUMNS.includes(c) ? " internal" : ""}`}>
                      {String((r as any)[c] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="side">
          <div className="proposals">
            <h2 className="section-title">Pending proposals · {visiblePending.length}</h2>
            {visiblePending.length === 0 && <div className="empty">No pending proposals. Start a replay to stream order emails through the agent.</div>}
            {visiblePending.map((m) => (
              <div key={m.mutation_id} className={`card ${m.classification}`}>
                <div className="head">
                  <span className={`tag ${m.classification}`}>{m.classification.replace("_", " ")}</span>
                  <span className="conf">conf {(m.confidence * 100).toFixed(0)}%</span>
                </div>
                <div className="note">{m.agent_note}</div>
                <ul className="sources">
                  {m.sources.map((s, i) => <li key={i}>↳ {s.doc_name} — {s.locator}</li>)}
                </ul>
                <div className="actions">
                  <button className="approve" onClick={() => approveMutation(m.mutation_id)}>Approve</button>
                  <button className="reject" onClick={() => rejectMutation(m.mutation_id)}>Reject</button>
                </div>
              </div>
            ))}
          </div>
          <div className="log">
            {log.map((l, i) => <div key={i} className="line"><b>{l.t}</b> {l.msg}</div>)}
            <div ref={logEndRef} />
          </div>
        </div>
      </div>
    </div>
  );
}
