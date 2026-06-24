"""WS-4 — Agent loop.

LangGraph state machine, one run per inbound email (beat):

    triage ─(is_order?)─▶ extract ─▶ reconcile ─▶ propose/revise ─▶ END
       │                                                            ▲
       └─(not order)───────────────────────────────────────────────┘
                                                       human gate ⇢ commit
                                                       (external, via the API —
                                                        there is NO auto-commit)

Beats are delivered one at a time (cursor), so the demo unfolds as the thread
did: an ORDER email proposes adding PO 11667250 (the catch); a later REVISION
email rescinds it, and the agent retracts its own pending proposal (or, if the
add was already approved, proposes a compensating removal). The tracker stays
correct either way.

Model calls (triage) route through LiteLLM; the spine is deterministic, so with
CARRYSTAR_USE_LLM off the loop runs fully offline. The graph stops at propose;
approved mutations commit out-of-band through AppState.approve -> the store seam.
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from carrystar.api.events import Event, EventType
from carrystar.config import settings
from carrystar.contracts import (
    Classification,
    DocType,
    Mutation,
    MutationType,
    ParsedDoc,
    ReconResult,
    SourceRef,
)
from carrystar.engine.reconcile import reconcile
from carrystar.llm.router import triage_email
from carrystar.loop.merge import merge_parsed_docs
from carrystar.seams import registry


class LoopState(TypedDict, total=False):
    beat: Any
    step: float
    is_order: bool
    docs: list[ParsedDoc]
    merged_doc: ParsedDoc
    recon: ReconResult


def _docs_for_beat(beat) -> list[ParsedDoc]:
    if beat.parsed_docs:
        return list(beat.parsed_docs)
    from pathlib import Path

    parsers = registry.get_parsers()
    return [parsers.parse_path(Path(p)) for p in beat.attachment_paths]


def _rescind_provenance(docs: list[ParsedDoc], po: str) -> tuple[list[SourceRef], int | None]:
    """Sources that justify retracting PO `po`: the revision email + the revised
    BOL (where the PO is now absent and the total has dropped)."""
    srcs: list[SourceRef] = []
    revised_total: int | None = None
    for d in docs:
        if d.doc_type == DocType.EMAIL_BODY:
            srcs.append(SourceRef(doc_name=d.doc_name, locator=f"revision — PO {po} not shipping (ships July)"))
        elif d.doc_type == DocType.BOL_DOCX:
            revised_total = sum(int(r.get("ctn_qty", 0) or 0) for r in d.rows)
            srcs.append(SourceRef(doc_name=d.doc_name, locator=f"revised — PO {po} removed, TOTAL {revised_total} ctn"))
    if not srcs:
        srcs.append(SourceRef(doc_name="revision email", locator="PO rescinded"))
    return srcs, revised_total


def build_graph(app_state):
    bus = app_state.bus

    async def triage(state: LoopState) -> dict:
        beat = state["beat"]
        step = state.get("step", 0.0)
        await bus.publish(Event(EventType.EMAIL_RECEIVED, {
            "beat_id": beat.beat_id, "kind": beat.kind, "account": beat.account,
            "sender": beat.sender, "subject": beat.subject,
            "attachments": beat.attachment_names, "body": beat.email_body,
        }))
        await asyncio.sleep(step * 0.5)
        d = triage_email(beat.subject, beat.account, bool(beat.parsed_docs or beat.attachment_paths))
        await bus.publish(Event(EventType.TRIAGE, {"decision": d.decision, "reason": d.reason, "model": d.model}))
        await asyncio.sleep(step)
        return {"is_order": d.is_order}

    async def extract(state: LoopState) -> dict:
        beat = state["beat"]
        step = state.get("step", 0.0)
        docs = _docs_for_beat(beat)
        await bus.publish(Event(EventType.EXTRACT, {
            "message": f"parsed {len(docs)} document(s): " + ", ".join(d.doc_name for d in docs)}))
        merged = merge_parsed_docs(docs)
        await bus.publish(Event(EventType.EXTRACT, {
            "message": f"merged into {len(merged.rows)} order line(s) for {merged.shipment_id}"}))
        await asyncio.sleep(step)
        return {"docs": docs, "merged_doc": merged}

    async def reconcile_node(state: LoopState) -> dict:
        step = state.get("step", 0.0)
        store = registry.get_store()
        recon = reconcile(store.get_state(), state["merged_doc"])
        await bus.publish(Event(EventType.RECON, {
            "shipment_id": recon.shipment_id, "summary": recon.summary,
            "source_doc_count": recon.source_doc_count, "matched_count": recon.matched_count,
            "change_count": recon.change_count,
        }))
        await asyncio.sleep(step)
        return {"recon": recon}

    async def propose(state: LoopState) -> dict:
        beat = state["beat"]
        step = state.get("step", 0.0)
        recon = state["recon"]
        if beat.kind == "revision" and beat.rescinds:
            await _handle_revision(beat, state.get("docs", []), recon, step)
            return {}
        if not recon.proposed_mutations:
            await bus.publish(Event(EventType.LOG, {"message": f"{recon.shipment_id}: in sync — no proposals"}))
            return {}
        for m in recon.proposed_mutations:
            app_state.register_proposal(m)
            await bus.publish(Event(EventType.PROPOSAL, m.model_dump(mode="json")))
            await asyncio.sleep(step)
        return {}

    async def _handle_revision(beat, docs, recon, step) -> None:
        store = registry.get_store()
        for po in beat.rescinds:
            srcs, revised_total = _rescind_provenance(docs, po)
            pending = app_state.find_pending_add(beat.shipment_id, po)
            committed = store.get_row_by_po(beat.shipment_id, po)
            if pending:
                reason = (f"{beat.sender} now says PO {po} will NOT ship on this load (ships in July); "
                          f"the revised BOL confirms {revised_total} ctn. Withdrawing the proposed add — "
                          f"the tracker is already correct.")
                await app_state.supersede(pending.mutation_id, reason, srcs, po)
                await asyncio.sleep(step)
            elif committed:
                m = Mutation(
                    mutation_id=f"mut-{beat.shipment_id}-{po}-remove",
                    type=MutationType.REMOVE_ROW, shipment_id=beat.shipment_id, row_id=committed.row_id,
                    new_value=f"remove PO {po} — rescinded (ships July)", sources=srcs, confidence=0.96,
                    classification=Classification.RESCINDED,
                    agent_note=(f"PO {po} was approved earlier, but {beat.sender}'s follow-up rescinds it "
                                f"(ships in July) and the revised BOL drops the load to {revised_total} ctn. "
                                f"Propose removing the row to keep the tracker correct."),
                )
                app_state.register_proposal(m)
                await bus.publish(Event(EventType.PROPOSAL, m.model_dump(mode="json")))
                await asyncio.sleep(step)
            else:
                await bus.publish(Event(EventType.RECON, {
                    "shipment_id": beat.shipment_id,
                    "summary": f"PO {po} rescinded by {beat.sender} — tracker already excludes it; no action needed.",
                    "source_doc_count": len(docs), "matched_count": 0, "change_count": 0,
                }))
        for m in recon.proposed_mutations:
            po = m.proposed_row.customer_po if m.proposed_row else None
            if po in beat.rescinds:
                continue
            app_state.register_proposal(m)
            await bus.publish(Event(EventType.PROPOSAL, m.model_dump(mode="json")))
            await asyncio.sleep(step)

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


async def deliver_next(app_state, step_seconds: float | None = None) -> bool:
    """Deliver the next queued beat through the graph. Returns False if none left
    or one is already in flight."""
    if app_state.beat_in_flight or app_state.beat_cursor >= len(app_state.beats):
        return False
    step = step_seconds if step_seconds is not None else settings.replay_step_seconds
    beat = app_state.beats[app_state.beat_cursor]
    app_state.beat_in_flight = True
    app_state.replay_running = True
    graph = build_graph(app_state)
    try:
        await graph.ainvoke({"beat": beat, "step": step})
    except Exception as e:  # noqa: BLE001 — surface, don't crash the server
        await app_state.bus.publish(Event(EventType.ERROR, {"message": f"{type(e).__name__}: {e}"}))
    finally:
        app_state.beat_cursor += 1
        app_state.beat_in_flight = False
        app_state.replay_running = False
        has_next = app_state.beat_cursor < len(app_state.beats)
        await app_state.bus.publish(Event(EventType.DONE, {
            "beat": beat.beat_id, "cursor": app_state.beat_cursor, "has_next": has_next,
        }))
    return True


async def run_all_beats(app_state, step_seconds: float = 0.0) -> None:
    """Headless convenience: begin a replay and deliver every beat in order."""
    await app_state.begin_replay()
    while app_state.beat_cursor < len(app_state.beats):
        await deliver_next(app_state, step_seconds)
