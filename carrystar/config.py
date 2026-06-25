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
    # When true (default), register the real Codex seams (parsers/store/replay)
    # at startup. Set CARRYSTAR_REAL_SEAMS=0 to fall back to the dev stub — a
    # safety valve if real parsing ever misbehaves mid-rehearsal.
    real_seams: bool = os.environ.get("CARRYSTAR_REAL_SEAMS", "1") == "1"
    # ENGINEERING-ONLY override: point LiteLLM at a local endpoint (e.g. EVO-X2
    # ollama over Tailscale) to prototype agent behaviors on local models.
    # EMPTY in the product — Carrystar's runtime stays on frontier APIs per the
    # data-class gate. Never ship this set.
    llm_api_base: str = os.environ.get("CARRYSTAR_LLM_API_BASE", "")

    # Live email listener (autonomous ingest). Credentials come from env only —
    # never hardcoded/committed. Empty host => listener stays idle.
    imap_host: str = os.environ.get("CARRYSTAR_IMAP_HOST", "")
    imap_port: int = int(os.environ.get("CARRYSTAR_IMAP_PORT", "993"))
    imap_user: str = os.environ.get("CARRYSTAR_IMAP_USER", "")
    imap_password: str = os.environ.get("CARRYSTAR_IMAP_PASSWORD", "")
    imap_folder: str = os.environ.get("CARRYSTAR_IMAP_FOLDER", "INBOX")
    imap_sender_filter: str = os.environ.get("CARRYSTAR_IMAP_SENDER", "")  # optional FROM filter
    listener_poll_seconds: float = float(os.environ.get("CARRYSTAR_LISTENER_POLL", "10"))


settings = Settings()
