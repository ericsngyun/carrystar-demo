# Carrystar — Real-Time Order Agent (v1 skeleton)

Replays real Carrystar order emails through an agent loop that **triages →
parses → reconciles → proposes** tracker mutations. A human approves; approved
mutations **commit** to the store and visibly update the on-screen tracker and a
mirror `.xlsx`.

**Hero beat (real data):** the Ross `CS02411883` catch — the BOL and order
export both show **662 ctn across 5 POs**, but the tracker holds **559 ctn /
4 POs**. PO `11667250` (103 ctn) is missing, and the agent flags it with full
provenance.

> Local, screenshared demo. No live M365/tenant email, no live workbook sync,
> no external carrier feeds — those are pilot / phase 2–3. This is the skeleton.

## Architecture

```
data/emails/<packet>/        real inbound packets (Ross CS02411883 staged)
carrystar/
  contracts.py               FROZEN schemas (WS-0, Claude-owned, read-only for Codex)
  interfaces.py              FROZEN seam Protocols for parsers/store/replay
  config.py                  env-driven settings + model routing
  api/                       FastAPI: SSE stream, replay control, human gate (WS-0)
  engine/reconcile.py        reconciliation engine — the Ross catch (WS-3)
  loop/orchestrator.py       LangGraph agent loop + LiteLLM routing (WS-4)
  llm/router.py              LiteLLM model router (WS-4)
  seams/                     DI registry + Claude dev stub (real Ross data)
frontend/                    React/Vite review console (WS-6)
```

### Workstreams
| WS | What | Owner | Status |
|----|------|-------|--------|
| WS-0 | Contracts + scaffold + seams + API | Claude | this repo |
| WS-1 | Parsers (xlsx/docx/pdf) | **Codex** | seam frozen, impl pending |
| WS-2 | Store (SQLite) + xlsx mirror | **Codex** | seam frozen, impl pending |
| WS-3 | Reconciliation engine | Claude | this repo |
| WS-4 | Agent loop (LangGraph + LiteLLM) | Claude | this repo |
| WS-5 | Replay harness + run cache | **Codex** | seam frozen, impl pending |
| WS-6 | Review console (real-time UI) | Claude | this repo |
| WS-7 | Fixtures + tests | **Codex** | pending |

Until Codex's WS-1/2/5 land, a **Claude-owned dev stub**
(`carrystar/seams/dev_stub.py`) serves the verified-real Ross packet so the loop,
store, and UI run end-to-end. See `docs/HANDOFF_CODEX.md`.

## Run it

```bash
# backend (terminal 1)
uv venv && uv pip install -e ".[dev]"
uv run uvicorn carrystar.api.main:app --reload --port 8000

# frontend (terminal 2)
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Click **Replay (cached)** to stream the Ross packet through the agent and watch
the missing PO surface as a pending proposal. Approve it to commit.

`CARRYSTAR_DEV_SEAM=1` (default) uses the dev stub. `CARRYSTAR_USE_LLM=1`
enables live model calls for triage/parse; off by default for offline rehearsal.
