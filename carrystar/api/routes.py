"""FastAPI routes: state, the SSE stream, replay control, and the human gate."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from carrystar.api.events import Event, EventType
from carrystar.api.state import MutationNotFound, app_state
from carrystar.config import settings

router = APIRouter(prefix="/api")


class ReplayRequest(BaseModel):
    mode: str = "live"            # "live" | "replay"
    step_seconds: float | None = None


class ApproveRequest(BaseModel):
    edits: dict | None = None     # optional field overrides -> marks mutation EDITED


@router.get("/health")
async def health() -> dict:
    from carrystar.seams import registry

    return {"ok": True, "dev_seam": registry.using_dev_seam()}


@router.get("/state")
async def get_state() -> dict:
    return app_state.state_snapshot()


@router.get("/stream")
async def stream() -> StreamingResponse:
    queue = app_state.bus.subscribe()

    async def gen():
        # Handshake: current snapshot so a late joiner is immediately consistent.
        hello = Event(EventType.HELLO, app_state.state_snapshot())
        yield hello.sse()
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield ev.sse()
                except asyncio.TimeoutError:
                    # SSE comment keep-alive so proxies don't drop the connection.
                    yield ": keep-alive\n\n"
        finally:
            app_state.bus.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/replay/start")
async def replay_start(req: ReplayRequest) -> dict:
    if req.mode not in ("live", "replay"):
        raise HTTPException(status_code=400, detail="mode must be 'live' or 'replay'")
    if app_state.beat_in_flight:
        raise HTTPException(status_code=409, detail="a beat is still being delivered")

    from carrystar.loop import orchestrator

    step = req.step_seconds if req.step_seconds is not None else settings.replay_step_seconds
    await app_state.begin_replay()                 # reset store/proposals, load the beat timeline
    asyncio.create_task(orchestrator.deliver_next(app_state, step))   # deliver beat 1 (the order email)
    return {"started": True, "mode": req.mode, "step_seconds": step, "total_beats": len(app_state.beats)}


@router.post("/replay/next")
async def replay_next(req: ReplayRequest | None = None) -> dict:
    """Deliver the next inbound email (e.g. the revision that rescinds the PO)."""
    if app_state.beat_in_flight:
        raise HTTPException(status_code=409, detail="a beat is still being delivered")
    if app_state.beat_cursor >= len(app_state.beats):
        return {"delivered": False, "has_next": False}

    from carrystar.loop import orchestrator

    step = req.step_seconds if (req and req.step_seconds is not None) else settings.replay_step_seconds
    asyncio.create_task(orchestrator.deliver_next(app_state, step))
    return {"delivered": True}


@router.post("/replay/stop")
async def replay_stop() -> dict:
    app_state.replay_running = False
    return {"stopped": True}


@router.post("/mutations/{mutation_id}/approve")
async def approve(mutation_id: str, req: ApproveRequest | None = None) -> dict:
    try:
        m = await app_state.approve(mutation_id, edits=(req.edits if req else None))
    except MutationNotFound:
        raise HTTPException(status_code=404, detail=f"no pending mutation {mutation_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"mutation_id": m.mutation_id, "status": m.status.value}


@router.post("/mutations/{mutation_id}/reject")
async def reject(mutation_id: str) -> dict:
    try:
        m = await app_state.reject(mutation_id)
    except MutationNotFound:
        raise HTTPException(status_code=404, detail=f"no pending mutation {mutation_id}")
    return {"mutation_id": m.mutation_id, "status": m.status.value}


@router.post("/reset")
async def reset() -> dict:
    await app_state.reset()
    return {"ok": True}
