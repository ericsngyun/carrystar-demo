"""Runtime dependency-injection registry for the Codex-lane seams.

The Claude lane (API + agent loop) resolves parsers/store/replay through this
registry and never imports the concrete Codex modules directly. Codex's
bootstrap (or the integration wiring in WS-INT) registers concrete impls here.

Resolution order for each seam:
  1. An explicitly registered implementation (set by Codex modules / WS-INT).
  2. The Claude-owned dev stub, IF env CARRYSTAR_DEV_SEAM=1 (default in dev).
  3. Otherwise raise SeamNotImplemented pointing at docs/HANDOFF_CODEX.md.
"""

from __future__ import annotations

import os

from carrystar.interfaces import ParserRegistry, ReplaySource, Store


class SeamNotImplemented(RuntimeError):
    def __init__(self, seam: str, codex_ws: str) -> None:
        super().__init__(
            f"Seam '{seam}' is not implemented yet (owned by Codex {codex_ws}). "
            f"Either run with CARRYSTAR_DEV_SEAM=1 to use the Claude dev stub, "
            f"or land {codex_ws}. See docs/HANDOFF_CODEX.md."
        )


_parsers: ParserRegistry | None = None
_store: Store | None = None
_replay: ReplaySource | None = None


def _dev_seam_enabled() -> bool:
    return os.environ.get("CARRYSTAR_DEV_SEAM", "1") == "1"


def register_parsers(parsers: ParserRegistry) -> None:
    global _parsers
    _parsers = parsers


def register_store(store: Store) -> None:
    global _store
    _store = store


def register_replay(replay: ReplaySource) -> None:
    global _replay
    _replay = replay


def get_parsers() -> ParserRegistry:
    if _parsers is not None:
        return _parsers
    if _dev_seam_enabled():
        from carrystar.seams import dev_stub

        return dev_stub.parsers()
    raise SeamNotImplemented("parsers", "WS-1")


def get_store() -> Store:
    if _store is not None:
        return _store
    if _dev_seam_enabled():
        from carrystar.seams import dev_stub

        return dev_stub.store()
    raise SeamNotImplemented("store", "WS-2")


def get_replay() -> ReplaySource:
    if _replay is not None:
        return _replay
    if _dev_seam_enabled():
        from carrystar.seams import dev_stub

        return dev_stub.replay()
    raise SeamNotImplemented("replay", "WS-5")


def using_dev_seam() -> bool:
    """True when any seam is currently served by the Claude dev stub."""
    return _dev_seam_enabled() and (_parsers is None or _store is None or _replay is None)
