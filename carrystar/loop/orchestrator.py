"""WS-4 — Agent loop.

LangGraph state machine, one run per inbound email:

    triage ─(is_order?)─▶ extract ─▶ reconcile ─▶ propose ─▶ END
       │                                                      ▲
       └─(not order)─────────────────────────────────────────┘
                                                       human gate ⇢ commit
                                                       (external, via the API —
                                                        there is NO auto-commit)

Model calls (triage / parse repair) route through LiteLLM (carrystar/llm), but
the spine is deterministic: with CARRYSTAR_USE_LLM off the loop runs fully
offline on heuristics + the parser seam. The graph stops at `propose`; approved
mutations commit out-of-band through AppState.approve -> the store seam.
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from carrystar.api.events import Event, EventType
from carrystar.config import settings
from carrystar.contracts import ParsedDoc, ReconResult
from carrystar.engine.reconcile import reconcile
from carrystar.llm.router import triage_email
from carrystar.loop.merge import merge_parsed_docs
from carrystar.seams import registry


class LoopState(TypedDict, total=False):
    packet: Any
    step: float
    is_order: bool
    merged_doc: ParsedDoc
    recon: ReconResult


def build_graph(app_state):
    bus = app_state.bus

    async def triage(state: LoopState) -> dict:
        packet = state["packet"]
        step = state.get("step", 0.0)
        await bus.publish(Event(EventType.EMAIL_RECEIVED, {
            "packet_id": packet.packet_id,
            "account": packet.account,
            "subject": packet.subject,
        }))
        await asyncio.sleep(step * 0.5)
        d = triage_email(packet.subject, packet.account, bool(packet.attachment_paths))
        await bus.publish(Event(EventType.TRIAGE, {
            "decision": d.decision, "reason": d.reason, "model": d.model,
        }))
        await asyncio.sleep(step)
        return {"is_order": d.is_order}

    async def extract(state: LoopState) -> dict:
        packet = state["packet"]
        step = state.get("step", 0.0)
        parsers = registry.get_parsers()
        if hasattr(parsers, "parse_packet"):
            docs = parsers.parse_packet()
        else:
            docs = [parsers.parse_path(p) for p in packet.attachment_paths]
        await bus.publish(Event(EventType.EXTRACT, {
            "message": f"parsed {len(docs)} document(s): " + ", ".join(d.doc_name for d in docs),
        }))
        merged = merge_parsed_docs(docs)
        await bus.publish(Event(EventType.EXTRACT, {
            "message": f"merged into {len(merged.rows)} order line(s) for {merged.shipment_id}",
        }))
        await asyncio.sleep(step)
        return {"merged_doc": merged}

    async def reconcile_node(state: LoopState) -> dict:
        step = state.get("step", 0.0)
        store = registry.get_store()
        recon = reconcile(store.get_state(), state["merged_doc"])
        await bus.publish(Event(EventType.RECON, {
            "shipment_id": recon.shipment_id,
            "summary": recon.summary,
            "source_doc_count": recon.source_doc_count,
            "matched_count": recon.matched_count,
            "change_count": recon.change_count,
        }))
        await asyncio.sleep(step)
        return {"recon": recon}

    async def propose(state: LoopState) -> dict:
        step = state.get("step", 0.0)
        recon = state["recon"]
        if not recon.proposed_mutations:
            await bus.publish(Event(EventType.LOG, {
                "message": f"{recon.shipment_id}: in sync — no proposals",
            }))
            return {}
        for m in recon.proposed_mutations:
            app_state.register_proposal(m)
            await bus.publish(Event(EventType.PROPOSAL, m.model_dump(mode="json")))
            await asyncio.sleep(step)  # paced reveal — the proposals surface one by one
        return {}

    def route_after_triage(state: LoopState) -> str:
        return "extract" if state.get("is_order") else "skip"

    g = StateGraph(LoopState)
    g.add_node("triage", triage)
    g.add_node("extract", extract)
    g.add_node("reconcile", reconcile_node)
    g.add_node("propose", propose)
    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", route_after_triage, {"extract": "extract", "skip": END})
    g.add_edge("extract", "reconcile")
    g.add_edge("reconcile", "propose")
    g.add_edge("propose", END)
    return g.compile()


async def run_replay(app_state, mode: str = "live", step_seconds: float | None = None) -> None:
    """Drive packets from the replay seam through the graph, streaming events.

    `live`  — run the real pipeline now (parser seam + engine).
    `replay`— stream a prior cached run if WS-5 has one; otherwise fall back to
              live (the dev seam has no cache). Pacing gives the real-time feel.
    """
    step = step_seconds if step_seconds is not None else settings.replay_step_seconds
    graph = build_graph(app_state)
    replay = registry.get_replay()
    bus = app_state.bus
    try:
        cached = replay.cached_run() if mode == "replay" else None
        if mode == "replay" and cached is None:
            await bus.publish(Event(EventType.LOG, {
                "message": "no cached run found — running live (WS-5 cache not yet present)",
            }))
        await bus.publish(Event(EventType.LOG, {
            "message": f"replay started ({mode}) · LLM={'on' if settings.use_llm else 'off'} · step={step}s",
        }))
        for packet in replay.packets():
            await graph.ainvoke({"packet": packet, "step": step})
        await bus.publish(Event(EventType.DONE, {"mode": mode}))
    except Exception as e:  # noqa: BLE001 — surface, don't crash the server
        await bus.publish(Event(EventType.ERROR, {"message": f"{type(e).__name__}: {e}"}))
    finally:
        app_state.replay_running = False
