# Live email listener (autonomous ingest)

The listener polls a mailbox over IMAP and, for each **new** message, pushes it
through the agent loop (`orchestrator.ingest`) so proposals surface in the UI on
their own. **The human gate is unchanged** — the listener only proposes; commits
still require an approve click. Live tenant mail is a deliberate step past the
original v1 scope; the cached/dev-stub replay stays as the rehearsal safety net.

Design notes: **read-only** IMAP select + UID-dedup → it never mutates the
mailbox; blocking IMAP runs in a worker thread; a bad poll logs and retries
(never crashes the server); the first poll baselines existing mail so it only
reacts to messages that arrive *after* you start it.

## Go live

Set credentials via env (or a gitignored `.env`) — **never commit them**:

```bash
export CARRYSTAR_IMAP_HOST=imap.gmail.com         # M365: outlook.office365.com
export CARRYSTAR_IMAP_PORT=993
export CARRYSTAR_IMAP_USER='you@domain.com'
export CARRYSTAR_IMAP_PASSWORD='<app password>'   # Gmail: App Password (2FA required)
export CARRYSTAR_IMAP_FOLDER=INBOX                # or a specific label/folder
export CARRYSTAR_IMAP_SENDER='eduardo@carrystarinc.com'   # optional FROM filter
export CARRYSTAR_LISTENER_POLL=10                 # seconds between polls

uv run uvicorn carrystar.api.main:app --port 8000
```

Then in the UI click **📡 Listen** (or `POST /api/listener/start`). Forward/send
a Carrystar order email to that mailbox and watch the agent triage → parse →
reconcile → propose, live. `GET /api/listener/status` reports state.

## Provider notes
- **Gmail / Google Workspace:** enable IMAP; create an **App Password** (needs
  2-Step Verification). Workspace admins may need to allow IMAP for the org.
- **Microsoft 365:** IMAP host `outlook.office365.com`. Many tenants disable
  basic-auth IMAP — if so, the listener can't log in and you'd need the Microsoft
  **Graph** API with OAuth (a phase-2 adapter; the `ingest`/`email_to_beat` core
  is reused unchanged — only the fetch layer changes).

## Verified without a live mailbox
`tests/test_email_intake.py` synthesizes the real Ross order + revision emails
(actual attachments) and drives the full two-act through `ingest`: order →
missing_row catch (3 sources), revision → the agent retracts its own proposal →
tracker stays 559. So the processing path is proven; only the IMAP socket needs
your creds to exercise live.
