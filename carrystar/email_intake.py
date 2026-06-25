"""Email -> Beat intake for the autonomous listener.

Turns a raw inbound email (RFC822 bytes, as a mailbox would hand us) into a
Beat the agent loop can ingest: extracts attachments to a working dir, reads the
body, and infers whether it's an order or a revision (and which PO it rescinds).

Source-agnostic: the IMAP/Graph listener supplies the raw bytes; this module
does not talk to any mailbox itself. The human gate downstream is unchanged.
"""

from __future__ import annotations

import email
import email.policy
import re
from pathlib import Path

from carrystar.contracts import Beat

# Body phrases that signal a revision rescinding a PO.
_RESCIND_PATTERNS = (
    "will not be shipping", "will not ship", "won't ship", "not be shipping",
    "not shipping", "disregard", "do not ship", "cancel", "pulled", "remove po",
)
_PO_RE = re.compile(r"\b\d{6,8}\b")
_BOL_RE = re.compile(r"\bCS\d{6,}\b", re.IGNORECASE)
_MIN_ATTACHMENT_BYTES = 3000  # skip tiny inline logos


def parse_email(raw: bytes) -> dict:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body = ""
    b = msg.get_body(preferencelist=("plain",))
    if b is not None:
        body = b.get_content()
    else:
        h = msg.get_body(preferencelist=("html",))
        if h is not None:
            body = re.sub(r"<[^>]+>", " ", h.get_content())
    body = re.sub(r"\s+", " ", body).strip()

    attachments: list[tuple[str, bytes]] = []
    for part in msg.walk():
        fn = part.get_filename()
        data = part.get_payload(decode=True)
        if not fn or not data:
            continue
        if part.get_content_type().startswith("image/") and len(data) < _MIN_ATTACHMENT_BYTES:
            continue
        attachments.append((fn, data))

    return {
        "sender": str(msg.get("From", "")),
        "subject": str(msg.get("Subject", "")),
        "date": str(msg.get("Date", "")),
        "body": body,
        "attachments": attachments,
    }


def classify(body: str) -> tuple[str, list[str]]:
    """Return (kind, rescinds). kind is 'revision' if the body rescinds a PO,
    else 'order'. rescinds lists ONLY the POs named in rescind sentences — so a
    quoted prior email or a signature block can't leak unrelated PO numbers."""
    if not any(p in body.lower() for p in _RESCIND_PATTERNS):
        return "order", []
    rescinds: list[str] = []
    for sentence in re.split(r"[.!?\n]+", body):
        if any(p in sentence.lower() for p in _RESCIND_PATTERNS):
            rescinds.extend(_PO_RE.findall(sentence))
    return "revision", sorted(set(rescinds))


def _shipment_id(subject: str, body: str, attachment_names: list[str]) -> str:
    for text in (subject, body, " ".join(attachment_names)):
        m = _BOL_RE.search(text or "")
        if m:
            return m.group(0).upper()
    return ""


def email_to_beat(raw: bytes, work_dir: Path, beat_id: str, account: str = "") -> Beat:
    """Materialize one inbound email into a Beat (attachments written to disk so
    the WS-1 parser seam can read them; parsed_docs left empty -> real parse)."""
    meta = parse_email(raw)
    dest = work_dir / beat_id
    dest.mkdir(parents=True, exist_ok=True)

    attachment_paths: list[str] = []
    attachment_names: list[str] = []
    for fn, data in meta["attachments"]:
        safe = Path(fn).name
        (dest / safe).write_bytes(data)
        attachment_paths.append(str(dest / safe))
        attachment_names.append(safe)

    kind, rescinds = classify(meta["body"])
    shipment_id = _shipment_id(meta["subject"], meta["body"], attachment_names)

    return Beat(
        beat_id=beat_id,
        kind=kind,
        shipment_id=shipment_id,
        account=account or "",
        sender=meta["sender"],
        subject=meta["subject"],
        date=meta["date"],
        email_body=meta["body"],
        rescinds=rescinds,
        attachment_names=attachment_names,
        attachment_paths=attachment_paths,
        parsed_docs=[],
    )
