"""In-process pub/sub event bus for the real-time SSE stream.

The agent loop publishes typed events; every connected SSE client gets its own
async queue and receives the stream. Deliberately tiny — no broker, single
process. That's the whole point of the v1 skeleton.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    HELLO = "hello"                 # initial handshake (carries a state snapshot)
    EMAIL_RECEIVED = "email_received"
    TRIAGE = "triage"               # triage decision for an inbound email
    EXTRACT = "extract"             # parser/extraction progress
    RECON = "recon"                 # a ReconResult summary
    PROPOSAL = "proposal"           # a pending Mutation awaiting the human gate
    MUTATION_STATUS = "mutation_status"  # approved / rejected / edited
    COMMITTED = "committed"         # an approved mutation committed -> row delta
    STATE = "state"                 # full tracker-state snapshot
    LOG = "log"                     # narration line
    DONE = "done"                   # replay finished
    ERROR = "error"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)

    def sse(self) -> str:
        # Server-Sent Events wire format.
        return f"event: {self.type.value}\ndata: {json.dumps(self.data, default=str)}\n\n"


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._history: list[Event] = []  # so late joiners can catch up the narrative

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(q)

    async def publish(self, event: Event) -> None:
        self._history.append(event)
        for q in list(self._subscribers):
            await q.put(event)

    def publish_nowait(self, event: Event) -> None:
        self._history.append(event)
        for q in list(self._subscribers):
            q.put_nowait(event)

    @property
    def history(self) -> list[Event]:
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()
