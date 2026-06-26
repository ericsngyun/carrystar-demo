"""Email -> Beat -> ingest, end to end, without a live mailbox.

Synthesizes two real RFC822 messages (order + revision) from the staged Ross
artifacts — exactly what an IMAP listener would hand us — and drives them
through the autonomous ingest path. The human gate stays intact: ingest only
proposes; commits still require approve().
"""

import asyncio
from email.message import EmailMessage
from pathlib import Path

from carrystar.api.events import EventType
from carrystar.api.state import AppState
from carrystar.email_intake import classify, email_to_beat
from carrystar.loop import orchestrator
from carrystar.parsers import parsers as real_parsers
from carrystar.seams import registry

ROSS = Path(__file__).resolve().parents[1] / "data" / "emails" / "ross-cs02411883"

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _msg(subject: str, body: str, attachments: list[Path]) -> bytes:
    m = EmailMessage()
    m["From"] = "Lina Vincelli <lina@markedwards.example>"
    m["To"] = "ops@carrystar.example"
    m["Subject"] = subject
    m.set_content(body)
    for p in attachments:
        sub = {".xlsx": _XLSX, ".docx": _DOCX, ".pdf": "application/pdf"}[p.suffix.lower()]
        maintype, subtype = sub.split("/", 1)
        m.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)
    return m.as_bytes()


def _order_email() -> bytes:
    return _msg(
        "Load CS02411883 - pickup 06/17, adding PO 11667250",
        (ROSS / "email1_add_instruction.txt").read_text(),
        # Matches the synthetic Gmail packet: pick slip dropped (b72f0ee).
        [ROSS / "Book6.xlsx", ROSS / "BOL_CS02411883_original.docx"],
    )


def _revision_email() -> bytes:
    return _msg(
        "RE: Load CS02411883 - revised BOL (PO 11667250 pulled)",
        (ROSS / "email2_revision.txt").read_text(),
        [ROSS / "BOL_CS02411883_revised.docx"],
    )


def test_classify_distinguishes_order_from_revision():
    order_kind, order_rescinds = classify((ROSS / "email1_add_instruction.txt").read_text())
    rev_kind, rev_rescinds = classify((ROSS / "email2_revision.txt").read_text())
    assert order_kind == "order" and order_rescinds == []
    assert rev_kind == "revision" and rev_rescinds == ["11667250"]


def test_order_email_becomes_a_beat_with_real_attachments(tmp_path):
    beat = email_to_beat(_order_email(), tmp_path, "ross-order", account="ROSS")
    assert beat.kind == "order"
    assert beat.shipment_id == "CS02411883"
    assert {Path(p).suffix for p in beat.attachment_paths} == {".xlsx", ".docx"}
    assert beat.parsed_docs == []   # parsed live by the WS-1 seam during ingest


def test_autonomous_ingest_two_emails_full_two_act(tmp_path):
    async def main():
        registry.register_parsers(real_parsers())     # real WS-1 parsing of attachments
        registry.get_store().reset()                   # dev store seed 559/4
        app = AppState()
        events: list = []
        q = app.bus.subscribe()

        async def drain():
            while True:
                events.append(await q.get())

        t = asyncio.create_task(drain())

        # --- email 1 arrives (order) -> the catch, pending ---
        b1 = email_to_beat(_order_email(), tmp_path, "ross-order", account="ROSS")
        await orchestrator.ingest(app, b1, step_seconds=0.0)
        pend = app.pending_list()
        assert len(pend) == 1 and pend[0].classification.value == "missing_row"
        assert pend[0].proposed_row.customer_po == "11667250"
        assert len({s.doc_name for s in pend[0].sources}) >= 2   # export + BOL (pick slip dropped)
        # human gate intact: nothing committed yet
        assert sum(r.ctn_qty for r in registry.get_store().get_state()) == 559

        # --- email 2 arrives (revision) -> agent retracts its own proposal ---
        b2 = email_to_beat(_revision_email(), tmp_path, "ross-revision", account="ROSS")
        await orchestrator.ingest(app, b2, step_seconds=0.0)
        await asyncio.sleep(0.02)
        t.cancel()

        assert b2.kind == "revision" and b2.rescinds == ["11667250"]
        retr = [e for e in events if e.type is EventType.RETRACTION]
        assert len(retr) == 1 and retr[0].data["customer_po"] == "11667250"
        assert app.pending_list() == []
        assert sum(r.ctn_qty for r in registry.get_store().get_state()) == 559

    asyncio.run(main())
