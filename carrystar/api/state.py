"""Application session state: the human gate + commit glue.

Holds the event bus and the registry of pending Mutations. The agent loop adds
proposals here; the UI approves/rejects/edits through here. Approval is the ONLY
path to commit — there is no auto-commit anywhere.
"""

from __future__ import annotations

import asyncio

from carrystar.api.events import Event, EventBus, EventType
from carrystar.contracts import Mutation, MutationStatus
from carrystar.seams import registry


class MutationNotFound(KeyError):
    pass


class AppState:
    def __init__(self) -> None:
        self.bus = EventBus()
        self._pending: dict[str, Mutation] = {}
        self._lock = asyncio.Lock()
        self.replay_running = False

    # --- proposals -------------------------------------------------------
    def register_proposal(self, mutation: Mutation) -> None:
        self._pending[mutation.mutation_id] = mutation

    def get_pending(self, mutation_id: str) -> Mutation:
        m = self._pending.get(mutation_id)
        if m is None:
            raise MutationNotFound(mutation_id)
        return m

    def pending_list(self) -> list[Mutation]:
        return [m for m in self._pending.values() if m.status == MutationStatus.PENDING]

    # --- human gate ------------------------------------------------------
    async def approve(self, mutation_id: str, edits: dict | None = None) -> Mutation:
        async with self._lock:
            m = self.get_pending(mutation_id)
            if edits:
                m = m.model_copy(update=edits)
                m.status = MutationStatus.EDITED
            else:
                m.status = MutationStatus.APPROVED
            self._pending[mutation_id] = m

            # Commit through the store seam (WS-2 / dev stub).
            store = registry.get_store()
            row = store.apply_mutation(m)

            await self.bus.publish(Event(EventType.MUTATION_STATUS, {
                "mutation_id": m.mutation_id,
                "status": m.status.value,
            }))
            await self.bus.publish(Event(EventType.COMMITTED, {
                "mutation_id": m.mutation_id,
                "row": row.model_dump(mode="json"),
                "type": m.type.value,
                "classification": m.classification.value,
            }))
            await self._publish_state(store)
            self._refresh_mirror(store)
            return m

    async def reject(self, mutation_id: str) -> Mutation:
        async with self._lock:
            m = self.get_pending(mutation_id)
            m.status = MutationStatus.REJECTED
            self._pending[mutation_id] = m
            await self.bus.publish(Event(EventType.MUTATION_STATUS, {
                "mutation_id": m.mutation_id,
                "status": m.status.value,
            }))
            return m

    # --- state snapshot --------------------------------------------------
    async def _publish_state(self, store=None) -> None:
        store = store or registry.get_store()
        await self.bus.publish(Event(EventType.STATE, {
            "rows": [r.model_dump(mode="json") for r in store.get_state()],
        }))

    def state_snapshot(self) -> dict:
        store = registry.get_store()
        return {
            "rows": [r.model_dump(mode="json") for r in store.get_state()],
            "pending": [m.model_dump(mode="json") for m in self.pending_list()],
            "replay_running": self.replay_running,
        }

    def _refresh_mirror(self, store) -> None:
        """Regenerate the visible .xlsx mirror after a commit (demo beat)."""
        from carrystar.config import MIRROR_XLSX

        try:
            store.write_mirror_xlsx(MIRROR_XLSX)
            self.bus.publish_nowait(Event(EventType.LOG, {
                "message": f"mirror .xlsx updated → {MIRROR_XLSX.relative_to(MIRROR_XLSX.parents[1])}",
            }))
        except Exception as e:  # noqa: BLE001 — mirror is cosmetic; never block a commit
            self.bus.publish_nowait(Event(EventType.LOG, {
                "message": f"mirror write skipped: {type(e).__name__}",
            }))

    async def reset(self) -> None:
        async with self._lock:
            self._pending.clear()
            self.bus.clear_history()
            registry.get_store().reset()
            self.replay_running = False
        await self._publish_state()


# Single app-scoped instance (the demo is single-process, single-room).
app_state = AppState()
