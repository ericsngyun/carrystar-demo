"""Codex-owned seam registration hooks."""

from __future__ import annotations

from carrystar.parsers import parsers
from carrystar.replay import replay
from carrystar.seams.registry import register_parsers, register_replay, register_store
from carrystar.store import store


def register_codex_seams() -> None:
    register_parsers(parsers())
    register_store(store())
    register_replay(replay())


register_codex_seams()
