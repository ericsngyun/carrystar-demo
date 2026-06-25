"""Autonomous live email listener (IMAP).

Polls a mailbox over IMAP, and for each NEW message pushes it through the agent
loop via orchestrator.ingest — so proposals surface in the UI on their own. The
human gate is unchanged: the listener never commits, it only feeds the loop.

Credentials are env-only (carrystar.config). Read-only IMAP select + UID-based
dedup, so it never mutates the mailbox. Blocking IMAP calls run in a thread to
keep the event loop responsive. Defensive throughout — a bad poll logs and
retries; it never crashes the server.

Live tenant mail is a deliberate step past the original v1 scope; keep the
cached/dev-stub replay as the rehearsal safety net.
"""

from __future__ import annotations

import asyncio
import imaplib

from carrystar.api.events import Event, EventType
from carrystar.config import CACHE_DIR, settings
from carrystar.email_intake import email_to_beat
from carrystar.loop import orchestrator

INBOX_DIR = CACHE_DIR / "inbox"


class MailListener:
    def __init__(self, app_state) -> None:
        self.app_state = app_state
        self._task: asyncio.Task | None = None
        self._running = False
        self._status = "stopped"
        self._seen: set[bytes] = set()

    # --- public API ------------------------------------------------------
    def configured(self) -> bool:
        return bool(settings.imap_host and settings.imap_user and settings.imap_password)

    def status(self) -> dict:
        return {
            "running": self._running,
            "configured": self.configured(),
            "status": self._status,
            "host": settings.imap_host or None,
            "folder": settings.imap_folder,
            "sender_filter": settings.imap_sender_filter or None,
            "seen": len(self._seen),
        }

    async def start(self, poll_seconds: float | None = None) -> dict:
        if self._running:
            return self.status()
        if not self.configured():
            self._status = "not configured — set CARRYSTAR_IMAP_HOST/USER/PASSWORD"
            return self.status()
        self._running = True
        self._status = "connecting"
        self._task = asyncio.create_task(self._loop(poll_seconds or settings.listener_poll_seconds))
        return self.status()

    async def stop(self) -> dict:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        self._status = "stopped"
        await self.app_state.bus.publish(Event(EventType.LOG, {"message": "📭 listener stopped"}))
        return self.status()

    # --- internals -------------------------------------------------------
    def _search_criteria(self) -> list[str]:
        if settings.imap_sender_filter:
            return ["FROM", settings.imap_sender_filter]
        return ["ALL"]

    def _poll_once(self) -> list[tuple[bytes, bytes]]:
        """Blocking IMAP poll. Returns [(uid, raw_rfc822)] for messages we
        haven't seen. Runs inside a thread."""
        out: list[tuple[bytes, bytes]] = []
        M = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
        try:
            M.login(settings.imap_user, settings.imap_password)
            M.select(settings.imap_folder, readonly=True)
            typ, data = M.uid("search", None, *self._search_criteria())
            if typ != "OK":
                return out
            uids = data[0].split()
            if not self._seen and uids:
                # First poll: baseline existing mail so we only react to NEW arrivals.
                self._seen.update(uids)
                return out
            for uid in uids:
                if uid in self._seen:
                    continue
                typ, msg_data = M.uid("fetch", uid, "(RFC822)")
                self._seen.add(uid)
                if typ == "OK" and msg_data and msg_data[0]:
                    out.append((uid, msg_data[0][1]))
            return out
        finally:
            try:
                M.logout()
            except Exception:  # noqa: BLE001
                pass

    async def _loop(self, poll_seconds: float) -> None:
        bus = self.app_state.bus
        try:
            await asyncio.to_thread(self._poll_once)  # baseline pass
            self._status = "listening"
            await bus.publish(Event(EventType.LOG, {
                "message": f"📡 listening on {settings.imap_host}/{settings.imap_folder}"
                           + (f" from {settings.imap_sender_filter}" if settings.imap_sender_filter else "")
            }))
        except Exception as e:  # noqa: BLE001
            detail = str(e).strip() or type(e).__name__
            self._status = f"connect error: {detail[:160]}"
            self._running = False
            await bus.publish(Event(EventType.ERROR, {"message": f"listener connect failed: {detail}"}))
            return

        while self._running:
            try:
                new = await asyncio.to_thread(self._poll_once)
                for uid, raw in new:
                    beat = email_to_beat(raw, INBOX_DIR, f"mail-{uid.decode(errors='ignore')}")
                    await orchestrator.ingest(self.app_state, beat)
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001 — keep listening despite a bad poll
                await bus.publish(Event(EventType.ERROR, {"message": f"listener poll error: {type(e).__name__}: {e}"}))
            await asyncio.sleep(poll_seconds)


_LISTENER: MailListener | None = None


def get_listener(app_state) -> MailListener:
    global _LISTENER
    if _LISTENER is None:
        _LISTENER = MailListener(app_state)
    return _LISTENER
