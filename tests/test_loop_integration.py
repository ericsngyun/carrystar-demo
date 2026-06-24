"""WS-4 integration — the two-act Ross thread end to end over the dev seam.

Act 1 (order email): agent flags PO 11667250 as missing (the catch).
Act 2 (revision email): agent retracts it (pending) or proposes a compensating
removal (already committed). The tracker ends correct at 559/4 either way.

Claude-lane tests; asyncio.run so no async-pytest plugin needed.
"""

import asyncio
import json

from carrystar.api.events import Event, EventType
from carrystar.api.state import AppState
from carrystar.loop import orchestrator


async def _new_app() -> tuple[AppState, list[Event], asyncio.Task]:
    app = AppState()
    events: list[Event] = []
    q = app.bus.subscribe()

    async def drain():
        while True:
            events.append(await q.get())

    task = asyncio.create_task(drain())
    await app.begin_replay()
    return app, events, task


def test_act1_surfaces_the_missing_po_catch():
    async def main():
        app, events, task = await _new_app()
        await orchestrator.deliver_next(app, 0.0)
        await asyncio.sleep(0.02)
        task.cancel()
        pend = app.pending_list()
        assert len(pend) == 1
        m = pend[0]
        assert m.classification.value == "missing_row"
        assert m.proposed_row.customer_po == "11667250"
        assert m.proposed_row.ctn_qty == 103
        # corroborated by order export + original BOL + pick slip + email
        assert len({s.doc_name for s in m.sources}) >= 3
        # tracker untouched until a human approves
        from carrystar.seams import registry
        assert sum(r.ctn_qty for r in registry.get_store().get_state()) == 559

    asyncio.run(main())


def test_act2_auto_retracts_a_pending_catch():
    async def main():
        app, events, task = await _new_app()
        await orchestrator.deliver_next(app, 0.0)   # act 1: catch
        await orchestrator.deliver_next(app, 0.0)   # act 2: revision
        await asyncio.sleep(0.02)
        task.cancel()
        retr = [e for e in events if e.type is EventType.RETRACTION]
        assert len(retr) == 1
        assert retr[0].data["customer_po"] == "11667250"
        assert len(retr[0].data["sources"]) == 2   # revised BOL + revision email
        # nothing pending, tracker stays correct
        assert app.pending_list() == []
        from carrystar.seams import registry
        rows = registry.get_store().get_state()
        assert len(rows) == 4 and sum(r.ctn_qty for r in rows) == 559

    asyncio.run(main())


def test_act2_proposes_removal_when_catch_already_approved():
    async def main():
        from carrystar.seams import registry
        app, events, task = await _new_app()
        await orchestrator.deliver_next(app, 0.0)   # act 1
        add = app.pending_list()[0]
        await app.approve(add.mutation_id)          # human approves the add -> 662
        assert sum(r.ctn_qty for r in registry.get_store().get_state()) == 662
        await orchestrator.deliver_next(app, 0.0)   # act 2: revision
        await asyncio.sleep(0.02)
        rem = [m for m in app.pending_list() if m.type.value == "remove_row"]
        assert len(rem) == 1 and rem[0].classification.value == "rescinded"
        await app.approve(rem[0].mutation_id)       # human approves the removal -> 559
        task.cancel()
        rows = registry.get_store().get_state()
        assert len(rows) == 4 and sum(r.ctn_qty for r in rows) == 559

    asyncio.run(main())


def test_revision_reconcile_reads_in_sync_not_missing():
    """The revised reconcile must NOT re-flag 11667250 as missing — the rescind
    is a control signal, not an order line."""
    async def main():
        app, events, task = await _new_app()
        await orchestrator.deliver_next(app, 0.0)
        events.clear()
        await orchestrator.deliver_next(app, 0.0)   # revision beat
        await asyncio.sleep(0.02)
        task.cancel()
        recon = [e for e in events if e.type is EventType.RECON]
        # the revision's reconcile summary must not claim a missing PO
        assert recon and "missing" not in recon[0].data["summary"].lower()

    asyncio.run(main())


def test_sse_wire_serializes_new_enums_as_strings():
    async def main():
        app, events, task = await _new_app()
        await orchestrator.deliver_next(app, 0.0)
        await orchestrator.deliver_next(app, 0.0)
        await asyncio.sleep(0.02)
        task.cancel()
        retr = next(e for e in events if e.type is EventType.RETRACTION)
        wire = retr.sse()
        payload = json.loads(wire.split("data: ", 1)[1].strip())
        assert payload["customer_po"] == "11667250"
        status = next(e for e in events if e.type is EventType.MUTATION_STATUS and e.data["status"] == "superseded")
        assert "MutationStatus." not in status.sse()

    asyncio.run(main())
