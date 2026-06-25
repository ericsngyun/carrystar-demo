"""WS-7 tracker fixtures — re-exported from the canonical package seed so tests
and production (the store seam) share one source of truth (carrystar/seed.py)."""

from __future__ import annotations

from carrystar.seed import ROSS_BOL, initial_tracker_rows

__all__ = ["ROSS_BOL", "initial_tracker_rows"]
