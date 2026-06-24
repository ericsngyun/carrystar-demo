"""Runtime configuration. Env-driven, sensible local-demo defaults.

Build-time models (Opus 4.8 / GPT-5.5) wrote this code. The demo's OWN loop
calls frontier APIs via LiteLLM — Haiku-class for triage, Claude-class for messy
parse/repair. Carrystar is the non-regulated track, so no local OSS / EVO-X2.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "emails"
CACHE_DIR = REPO_ROOT / "cache"
MIRROR_XLSX = REPO_ROOT / "out" / "tracker_mirror.xlsx"


@dataclass(frozen=True)
class Settings:
    # Model routing (LiteLLM model strings). Overridable via env.
    triage_model: str = os.environ.get("CARRYSTAR_TRIAGE_MODEL", "anthropic/claude-haiku-4-5-20251001")
    parse_model: str = os.environ.get("CARRYSTAR_PARSE_MODEL", "anthropic/claude-opus-4-8")
    # When false, the loop never calls a live model — it uses deterministic
    # heuristics + the parser seam. Keeps rehearsals offline & fast.
    use_llm: bool = os.environ.get("CARRYSTAR_USE_LLM", "0") == "1"
    # Replay pacing (seconds between streamed beats) for the "real-time" feel.
    replay_step_seconds: float = float(os.environ.get("CARRYSTAR_REPLAY_STEP", "1.2"))
    dev_seam: bool = os.environ.get("CARRYSTAR_DEV_SEAM", "1") == "1"


settings = Settings()
