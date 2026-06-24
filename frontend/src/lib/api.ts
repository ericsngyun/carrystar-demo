// REST + SSE client for the Carrystar backend.
import type { StateSnapshot } from "./types";

const BASE = "/api";

export async function getState(): Promise<StateSnapshot> {
  const r = await fetch(`${BASE}/state`);
  return r.json();
}

export async function startReplay(mode: "live" | "replay", stepSeconds?: number) {
  const r = await fetch(`${BASE}/replay/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, step_seconds: stepSeconds }),
  });
  if (!r.ok) throw new Error(`replay/start failed: ${r.status}`);
  return r.json();
}

export async function approveMutation(id: string, edits?: Record<string, unknown>) {
  const r = await fetch(`${BASE}/mutations/${id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ edits: edits ?? null }),
  });
  if (!r.ok) throw new Error(`approve failed: ${r.status}`);
  return r.json();
}

export async function rejectMutation(id: string) {
  const r = await fetch(`${BASE}/mutations/${id}/reject`, { method: "POST" });
  if (!r.ok) throw new Error(`reject failed: ${r.status}`);
  return r.json();
}

export async function resetDemo() {
  const r = await fetch(`${BASE}/reset`, { method: "POST" });
  return r.json();
}

// Subscribe to the SSE stream. Returns a cleanup function.
export function subscribe(
  onEvent: (type: string, data: any) => void,
  onError?: (e: Event) => void,
): () => void {
  const es = new EventSource(`${BASE}/stream`);
  const types = [
    "hello", "email_received", "triage", "extract", "recon",
    "proposal", "mutation_status", "committed", "state", "log", "done", "error",
  ];
  for (const t of types) {
    es.addEventListener(t, (ev) => {
      const msg = ev as MessageEvent;
      onEvent(t, msg.data ? JSON.parse(msg.data) : {});
    });
  }
  if (onError) es.onerror = onError;
  return () => es.close();
}
