import { useEffect, useRef, useState } from "react";
import {
  approveMutation, getState, rejectMutation, resetDemo, startReplay, subscribe,
} from "./lib/api";
import { INTERNAL_COLUMNS, TRACKER_COLUMNS } from "./lib/types";
import type { Mutation, TrackerRow } from "./lib/types";

interface LogLine { t: string; msg: string; kind: string; }

// easeOutCubic tween so the carton KPI visibly counts up on commit.
function useAnimatedNumber(target: number, ms = 850): number {
  const [val, setVal] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    const start = performance.now();
    const a = from.current;
    if (a === target) return;
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / ms);
      const e = 1 - Math.pow(1 - p, 3);
      setVal(Math.round(a + (target - a) * e));
      if (p < 1) raf = requestAnimationFrame(tick);
      else from.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return val;
}

export default function App() {
  const [rows, setRows] = useState<TrackerRow[]>([]);
  const [pending, setPending] = useState<Mutation[]>([]);
  const [leaving, setLeaving] = useState<Set<string>>(new Set());
  const [log, setLog] = useState<LogLine[]>([]);
  const [connected, setConnected] = useState(false);
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [flash, setFlash] = useState<Set<string>>(new Set());
  const [pulse, setPulse] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);

  function addLog(msg: string, kind = "") {
    setLog((l) => [...l, { t: new Date().toLocaleTimeString(), msg, kind }].slice(-200));
  }

  useEffect(() => {
    getState().then((s) => { setRows(s.rows); setPending(s.pending); setRunning(s.replay_running); });
    return subscribe(
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
            addLog(`proposed · ${String(data.classification).replace("_", " ")} · ${data.agent_note}`, "proposal");
            break;
          case "recon":
            setSummary(data.summary);
            addLog(`reconciled ${data.shipment_id} — ${data.summary}`, "recon");
            break;
          case "mutation_status":
            setLeaving((s) => new Set(s).add(data.mutation_id));
            setTimeout(() => {
              setPending((p) => p.filter((m) => m.mutation_id !== data.mutation_id));
              setLeaving((s) => { const n = new Set(s); n.delete(data.mutation_id); return n; });
            }, 360);
            break;
          case "committed": {
            const rid = data.row?.row_id;
            if (rid) {
              setFlash((f) => new Set(f).add(rid));
              setPulse(true);
              setTimeout(() => setFlash((f) => { const n = new Set(f); n.delete(rid); return n; }), 2000);
              setTimeout(() => setPulse(false), 1200);
            }
            addLog(`committed PO ${data.row?.customer_po ?? rid} (${String(data.classification).replace("_", " ")})`, "committed");
            break;
          }
          case "email_received": addLog(`email in — ${data.subject ?? data.packet_id}`, "email"); break;
          case "triage": addLog(`triage [${data.model}] → ${data.decision}: ${data.reason ?? ""}`, "triage"); break;
          case "extract": addLog(`extract — ${data.message ?? ""}`, "extract"); break;
          case "log": addLog(data.message ?? "", "log"); break;
          case "done": setRunning(false); addLog("replay complete.", "log"); break;
          case "error": addLog(`ERROR: ${data.message ?? "unknown"}`, "error"); break;
        }
      },
      () => setConnected(false),
    );
  }, []);

  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [log]);

  async function onReplay(mode: "live" | "replay") {
    setRunning(true);
    try { await startReplay(mode); } catch (e) { addLog(String(e), "error"); setRunning(false); }
  }
  async function onReset() {
    await resetDemo(); setPending([]); setSummary(null); setLog([]);
    const s = await getState(); setRows(s.rows);
  }

  const visiblePending = pending.filter((m) => m.status === "pending");
  const totalCtn = rows.reduce((a, r) => a + r.ctn_qty, 0);
  const animatedCtn = useAnimatedNumber(totalCtn);
  const shipments = new Set(rows.map((r) => r.shipment_id)).size;

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <h1>Carrystar</h1>
          <span className="tag">Real-Time Order Agent · v1</span>
        </div>
        <div className="spacer" />
        <div className="status"><span className={`dot${connected ? " live" : ""}`} />{connected ? "stream live" : "connecting…"}</div>
        <button className="primary" disabled={running} onClick={() => onReplay("replay")}>▶ Replay</button>
        <button className="ghost" disabled={running} onClick={() => onReplay("live")}>Run live</button>
        <button className="ghost" onClick={onReset}>Reset</button>
      </div>

      <div className="kpis">
        <div className="kpi"><div className="label">Shipments</div><div className="value">{shipments}</div></div>
        <div className={`kpi${pulse ? " pulse" : ""}`}>
          <div className="label">Cartons reconciled</div>
          <div className="value">{animatedCtn.toLocaleString()}</div>
        </div>
        <div className="kpi"><div className="label">Tracker rows</div><div className="value">{rows.length}</div></div>
        <div className="kpi"><div className="label">Pending review</div><div className="value">{visiblePending.length}</div></div>
      </div>

      <div className="body">
        <div className="main">
          {summary && <div className="summary-banner"><span className="icon">⚠</span><span>{summary}</span></div>}
          <h2 className="section-title">Tracker <span className="count-pill">mirrors customer sheet · 14 cols</span></h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>{TRACKER_COLUMNS.map((c) => (
                  <th key={c} className={INTERNAL_COLUMNS.includes(c) ? "internal" : ""}>{c.replace(/_/g, " ")}</th>
                ))}</tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.row_id} className={`row-${r.status_color}${flash.has(r.row_id) ? " just-committed" : ""}`}>
                    {TRACKER_COLUMNS.map((c) => (
                      <td key={c} className={`${c === "ctn_qty" || c === "pc_qty" ? "num" : ""}${c === "customer_po" ? " po" : ""}${INTERNAL_COLUMNS.includes(c) ? " internal" : ""}`}>
                        {String((r as any)[c] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="side">
          <div className="proposals">
            <h2 className="section-title">Pending proposals <span className="count-pill">{visiblePending.length}</span></h2>
            {visiblePending.length === 0 && (
              <div className="empty">No pending proposals.<br />Hit <b>Replay</b> to stream the order email through the agent.</div>
            )}
            {visiblePending.map((m) => (
              <ProposalCard
                key={m.mutation_id} m={m} leaving={leaving.has(m.mutation_id)}
                onApprove={() => approveMutation(m.mutation_id)}
                onReject={() => rejectMutation(m.mutation_id)}
              />
            ))}
          </div>
          <div className="log">
            <div className="log-title">Agent activity</div>
            {log.map((l, i) => (
              <div key={i} className={`line kind-${l.kind}`}><span className="ts">{l.t}</span><span>{l.msg}</span></div>
            ))}
            <div ref={logEndRef} />
          </div>
        </div>
      </div>
    </div>
  );
}

function ProposalCard({ m, leaving, onApprove, onReject }: {
  m: Mutation; leaving: boolean; onApprove: () => void; onReject: () => void;
}) {
  const cls = m.classification;
  const pr = m.proposed_row;
  return (
    <div className={`card ${cls}${leaving ? " leaving" : ""}`}>
      <div className="head">
        <span className={`tag ${cls}`}>{cls.replace(/_/g, " ")}</span>
        <span className="conf">confidence <b>{(m.confidence * 100).toFixed(0)}%</b></span>
      </div>
      <p className="note">{m.agent_note}</p>

      {m.type === "add_row" && pr && (
        <div className="rowpreview">
          <span className="k">PO</span><span className="v">{pr.customer_po}</span>
          <span className="k">Cartons</span><span className="v">{pr.ctn_qty}</span>
          <span className="k">Style</span><span className="v">{pr.style || "—"}</span>
          <span className="k">Container</span><span className="v">{pr.container || "—"}</span>
          <span className="k">Import PO</span><span className="v">{pr.import_po || "—"}</span>
        </div>
      )}
      {m.type === "update_field" && (
        <div className="rowpreview diff">
          <span className="k">{m.field}</span>
          <span className="v"><span className="old">{m.old_value || "∅"}</span><span className="arrow">→</span><span className="new">{m.new_value}</span></span>
        </div>
      )}

      <ul className="sources">
        {m.sources.map((s, i) => (
          <li key={i} className="src"><span className="doc">{s.doc_name}</span><span className="loc">{s.locator}</span></li>
        ))}
      </ul>
      <div className="actions">
        <button className="approve" disabled={leaving} onClick={onApprove}>Approve</button>
        <button className="reject" disabled={leaving} onClick={onReject}>Reject</button>
      </div>
    </div>
  );
}
