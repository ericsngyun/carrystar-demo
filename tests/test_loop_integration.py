"""WS-4 integration — the agent loop end to end over the dev seam (real Ross
packet). Claude-lane test; uses asyncio.run so no async-pytest plugin needed.
"""

import asyncio
import json

from carrystar.api.events import Event, EventType
from carrystar.api.state import AppState
from carrystar.loop.orchestrator import run_replay
from carrystar.seams import registry


def _run_and_collect():
    async def main():
        registry.get_store().reset()
        app = AppState()
        q = app.bus.subscribe()
        events: list[Event] = []

        async def drain():
            while True:
                events.append(await q.get())

        task = asyncio.create_task(drain())
        await run_replay(app, mode="live", step_seconds=0)
        await asyncio.sleep(0.02)
        task.cancel()
        return app, events

    return asyncio.run(main())


def test_loop_emits_full_beat_sequence():
    _app, events = _run_and_collect()
    seq = [e.type.value for e in events]
    for beat in ("email_received", "triage", "extract", "recon", "proposal", "done"):
        assert beat in seq, f"missing beat {beat} in {seq}"


def test_loop_surfaces_triple_sourced_catch():
    _app, events = _run_and_collect()
    proposals = [e.data for e in events if e.type is EventType.PROPOSAL]
    miss = [p for p in proposals if p["classification"] == "missing_row"]
    assert len(miss) == 1
    m = miss[0]
    assert m["proposed_row"]["customer_po"] == "11667250"
    assert m["proposed_row"]["ctn_qty"] == 103
    assert len({s["doc_name"] for s in m["sources"]}) == 3
    assert m["confidence"] >= 0.95


def test_approve_commits_and_reaches_662():
    app, events = _run_and_collect()
    miss = next(e.data for e in events if e.type is EventType.PROPOSAL
                and e.data["classification"] == "missing_row")

    before = registry.get_store().get_state()
    assert len(before) == 4 and sum(r.ctn_qty for r in before) == 559

    asyncio.run(app.approve(miss["mutation_id"]))

    after = registry.get_store().get_state()
    assert len(after) == 5 and sum(r.ctn_qty for r in after) == 662


def test_sse_wire_serializes_enums_as_strings():
    """The SSE payload must carry plain strings (missing_row / plain), not enum
    reprs, so the browser parses them directly."""
    _app, events = _run_and_collect()
    proposal = next(e for e in events if e.type is EventType.PROPOSAL)
    wire = proposal.sse()
    payload = json.loads(wire.split("data: ", 1)[1].strip())
    assert payload["classification"] == "missing_row"
    assert payload["type"] == "add_row"
    assert payload["proposed_row"]["status_color"] == "plain"
    assert "Classification." not in wire and "StatusColor." not in wire
