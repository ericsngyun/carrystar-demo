"""FastAPI app factory. Serves the API and (in prod build) the static SPA."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from carrystar.api.routes import router

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app() -> FastAPI:
    # Register the real Codex seams (WS-1 parsers / WS-2 store / WS-5 replay).
    # Behind a flag so a rehearsal can fall back to the dev stub if needed.
    from carrystar.config import settings

    if settings.real_seams:
        import carrystar.bootstrap  # noqa: F401 — import registers the seams

    app = FastAPI(title="Carrystar Real-Time Agent Demo", version="0.1.0")

    # Vite dev server runs on :5173; allow it during development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    # If a production SPA build exists, serve it at root.
    if FRONTEND_DIST.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="spa")

    return app


app = create_app()
