"""Send the real Ross thread as two test emails (order -> revision) to a mailbox,
so the live IMAP listener can ingest them. Test helper only — not product.

Reuses the actual staged attachments + Lina's real email bodies, so the messages
hit the inbox in the exact format the parsers expect.

Usage (creds via the same env the listener uses):
    export CARRYSTAR_IMAP_USER='you@gmail.com'
    export CARRYSTAR_IMAP_PASSWORD='<app password>'      # Gmail App Password
    # optional: CARRYSTAR_SMTP_HOST (default smtp.gmail.com), CARRYSTAR_SMTP_PORT (587)
    uv run python scripts/send_test_emails.py --to you@gmail.com --part both --gap 20

    --part order      # send only the order email (the catch)
    --part revision   # send only the revision email (the retract)
    --part both       # order, wait --gap seconds, then revision (default)
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys
import time
from email.message import EmailMessage
from pathlib import Path

import carrystar.config  # noqa: F401 — importing loads .env into os.environ

ROSS = Path(__file__).resolve().parents[1] / "data" / "emails" / "ross-cs02411883"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _build(sender: str, to: str, subject: str, body: str, attachments: list[Path]) -> EmailMessage:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = to
    m["Subject"] = subject
    m.set_content(body)
    for p in attachments:
        sub = {".xlsx": _XLSX, ".docx": _DOCX, ".pdf": "application/pdf"}[p.suffix.lower()]
        maintype, subtype = sub.split("/", 1)
        m.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)
    return m


def order_email(sender: str, to: str) -> EmailMessage:
    return _build(sender, to, "Load CS02411883 - pickup 06/17, adding PO 11667250",
                  (ROSS / "email1_add_instruction.txt").read_text(),
                  [ROSS / "Book6.xlsx", ROSS / "BOL_CS02411883_original.docx",
                   ROSS / "Pick Slips - Export - 2026-06-15T111006.232.pdf"])


def revision_email(sender: str, to: str) -> EmailMessage:
    return _build(sender, to, "RE: Load CS02411883 - revised BOL (PO 11667250 pulled)",
                  (ROSS / "email2_revision.txt").read_text(),
                  [ROSS / "BOL_CS02411883_revised.docx"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default=os.environ.get("CARRYSTAR_IMAP_USER", ""))
    ap.add_argument("--part", choices=["order", "revision", "both"], default="both")
    ap.add_argument("--gap", type=float, default=20.0, help="seconds between order and revision")
    args = ap.parse_args()

    user = os.environ.get("CARRYSTAR_IMAP_USER", "")
    pw = os.environ.get("CARRYSTAR_IMAP_PASSWORD", "")
    host = os.environ.get("CARRYSTAR_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("CARRYSTAR_SMTP_PORT", "587"))
    to = args.to or user
    if not (user and pw and to):
        print("ERROR: set CARRYSTAR_IMAP_USER / CARRYSTAR_IMAP_PASSWORD (and --to).", file=sys.stderr)
        return 2

    def send(msg: EmailMessage, label: str) -> None:
        with smtplib.SMTP(host, port) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
        print(f"  sent [{label}] -> {to}: {msg['Subject']}")

    print(f"Sending test thread to {to} via {host}:{port}")
    if args.part in ("order", "both"):
        send(order_email(user, to), "order / the catch")
    if args.part == "both":
        print(f"  waiting {args.gap}s before the revision...")
        time.sleep(args.gap)
    if args.part in ("revision", "both"):
        send(revision_email(user, to), "revision / the retract")
    print("Done. Watch the listener ingest these (start the listener BEFORE sending).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
