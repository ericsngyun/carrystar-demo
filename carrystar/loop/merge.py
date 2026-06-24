"""Merge the multiple ParsedDocs of one email packet into a single consolidated
ParsedDoc per shipment, accumulating provenance.

This is the 'extract' step's join: the order export, the BOL, and the email
instruction each contribute a view of the same PO lines. Merging by customer_po
and accumulating `_sources` is what makes the Ross catch *triple-sourced* — the
engine then sees PO 11667250 corroborated by three documents.
"""

from __future__ import annotations

from carrystar.contracts import TRANSCRIPTION_COLUMNS, DocType, ParsedDoc

LINE_KEY = "customer_po"


def merge_parsed_docs(docs: list[ParsedDoc]) -> ParsedDoc:
    if not docs:
        return ParsedDoc(doc_id="merged-empty")

    # Process in completeness order so the richest doc fills fields first; later
    # docs only fill gaps but always contribute provenance.
    order = {DocType.ORDER_EXPORT_XLSX: 0, DocType.BOL_DOCX: 1, DocType.PICKSLIP_PDF: 2, DocType.EMAIL_BODY: 3}
    docs_sorted = sorted(docs, key=lambda d: order.get(d.doc_type, 9))

    shipment_id = next((d.shipment_id for d in docs_sorted if d.shipment_id), "")
    merged: dict[str, dict] = {}  # po -> row

    for doc in docs_sorted:
        for row in doc.rows:
            po = str(row.get(LINE_KEY, "")).strip()
            if not po:
                continue
            slot = merged.setdefault(po, {LINE_KEY: po, "_sources": []})
            # fill transcription fields, first non-empty wins
            for col in TRANSCRIPTION_COLUMNS:
                val = row.get(col)
                if val not in (None, "") and slot.get(col) in (None, ""):
                    slot[col] = val
            # accumulate provenance (dedup by doc_name+locator)
            for s in row.get("_sources", []) or []:
                if s not in slot["_sources"]:
                    slot["_sources"].append(s)

    confidence = max((d.confidence for d in docs_sorted), default=0.0)
    return ParsedDoc(
        doc_id=f"merged-{shipment_id or 'unknown'}",
        doc_name="merged packet",
        doc_type=DocType.UNKNOWN,
        shipment_id=shipment_id,
        rows=list(merged.values()),
        confidence=confidence,
        notes=f"merged {len(docs_sorted)} docs: " + ", ".join(d.doc_name for d in docs_sorted),
    )
