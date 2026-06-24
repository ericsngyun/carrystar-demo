# Carrystar — Real-Time Order Agent (v1 skeleton)

Replays real Carrystar order emails through an agent loop that **triages →
parses → reconciles → proposes** tracker mutations. A human approves; approved
mutations **commit** to the store and visibly update the on-screen tracker and a
mirror `.xlsx`.

**Hero beat (real data, two acts):** the Ross `CS02411883` thread.
- **Act 1 — the catch.** The order export, the original BOL, and the pick slip
  all show **662 ctn across 5 POs**; the tracker holds **559 / 4**. The agent
  flags PO `11667250` (103 ctn, heather grey) as missing, with full provenance.
- **Act 2 — the retract.** Lina's follow-up email arrives: *"we will NOT be
  shipping PO 11667250 on this load — it ships in July; disregard the pick slip"*
  plus a **revised BOL** (559/4). The agent reads it and **withdraws its own
  proposal** (or, if you already approved it, proposes a compensating removal).
  The tracker is correctly **559/4**.

The point: a naïve system — or a human speed-reading 50 threads a day — would
have added 103 cancelled cartons. The agent caught the follow-up. It never
auto-commits; every change passes a human gate.

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

Demo flow:
1. **Replay thread** → streams Act 1 (the order email). PO `11667250` surfaces
   as a pending, fully-sourced proposal.
2. (Optional) **Approve** it to show the commit motion (559 → 662, row flashes in).
3. **Next email ▸** → streams Act 2 (the revision). The agent retracts the
   proposal (or proposes a removal if you approved it). Tracker back to 559/4.

`CARRYSTAR_DEV_SEAM=1` (default) uses the dev stub carrying the real Ross thread.
`CARRYSTAR_USE_LLM=1` enables live model calls for triage; off by default for
offline rehearsal. The numeric reconciliation is deterministic either way.

Real source data for **all six accounts** (Ross, two ASN shipments, Fred Meyer,
Fashion Nova, Kohl's) is staged under `data/emails/<account>/` with a
`MANIFEST.json`; the live demo stays focused on the Ross hero thread.
