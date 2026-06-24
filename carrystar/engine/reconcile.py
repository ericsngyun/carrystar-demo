"""WS-3 — Reconciliation engine. The semantic heart.

Given the current tracker state and a (possibly merged) ParsedDoc for one
shipment, emit a ReconResult with Mutations classified as:
  matched | new_order | added_po | field_change | missing_row

Deterministic — no model calls here. The agent loop (WS-4) does any LLM-assisted
parsing upstream and merges multi-doc provenance into the ParsedDoc; this engine
turns documents-vs-state into reviewable, provenance-carrying proposals.

Authority boundary (enforced): the engine only ever proposes values for the 10
transcription columns. The 4 internal columns (rush_carton, ds, wms_ticket,
needs_labels) are left blank on added rows and never proposed as field changes —
they appear in no inbound document, so they are flagged for a human, not invented.
"""

from __future__ import annotations

from carrystar.contracts import (
    INTERNAL_COLUMNS,
    TRANSCRIPTION_COLUMNS,
    Classification,
    Mutation,
    MutationType,
    ParsedDoc,
    ReconResult,
    SourceRef,
    StatusColor,
    TrackerRow,
)

# Line key for these shipments: the customer PO uniquely identifies a tracker row.
LINE_KEY = "customer_po"

# Quantity columns compared numerically.
_NUM_COLS = {"ctn_qty", "pc_qty"}


def _norm(value) -> str:
    return "" if value is None else str(value).strip()


def _row_sources(parsed_row: dict) -> list[SourceRef]:
    out: list[SourceRef] = []
    for s in parsed_row.get("_sources", []) or []:
        if isinstance(s, SourceRef):
            out.append(s)
        elif isinstance(s, dict) and "doc_name" in s and "locator" in s:
            out.append(SourceRef(doc_name=s["doc_name"], locator=s["locator"]))
    return out


def _transcription_fields(parsed_row: dict) -> dict[str, object]:
    """Only the transcribable columns the engine is allowed to propose."""
    fields: dict[str, object] = {}
    for col in TRANSCRIPTION_COLUMNS:
        if col in parsed_row and _norm(parsed_row[col]) != "":
            fields[col] = parsed_row[col]
    return fields


def _values_differ(field: str, parsed_value, tracker_value) -> bool:
    if field in _NUM_COLS:
        try:
            return int(parsed_value) != int(tracker_value)
        except (TypeError, ValueError):
            return _norm(parsed_value) != _norm(tracker_value)
    return _norm(parsed_value) != _norm(tracker_value)


def _confidence_from_sources(n_sources: int, doc_confidence: float) -> float:
    """More independent corroborating documents -> higher confidence."""
    base = {0: 0.5, 1: 0.72, 2: 0.9}.get(n_sources, 0.97)
    return round(min(0.99, max(base, doc_confidence)), 2)


def _build_proposed_row(shipment_id: str, po: str, fields: dict, sources: list[SourceRef]) -> TrackerRow:
    row = TrackerRow(
        row_id=f"row-{shipment_id}-{po}",
        shipment_id=shipment_id,
        source_refs=sources,
    )
    for col, val in fields.items():
        if col in INTERNAL_COLUMNS:           # belt-and-suspenders: never fill internal cols
            continue
        setattr(row, col, _coerce(col, val))
    return row


def _coerce(col: str, value):
    if col in _NUM_COLS:
        try:
            return int(str(value).replace(",", "").strip() or 0)
        except (TypeError, ValueError):
            return 0
    return _norm(value)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def reconcile(state: list[TrackerRow], doc: ParsedDoc) -> ReconResult:
    shipment_id = doc.shipment_id or (doc.rows[0].get("shipment_id", "") if doc.rows else "")

    # Index the tracker rows for THIS shipment by PO.
    shipment_rows = [r for r in state if r.shipment_id == shipment_id]
    by_po: dict[str, TrackerRow] = {r.customer_po: r for r in shipment_rows if r.customer_po}
    shipment_known = len(shipment_rows) > 0

    mutations: list[Mutation] = []
    matched = 0
    doc_pos: list[str] = []
    doc_ctn_total = 0
    all_doc_names: set[str] = set()

    for parsed_row in doc.rows:
        po = _norm(parsed_row.get(LINE_KEY))
        if not po:
            continue
        doc_pos.append(po)
        fields = _transcription_fields(parsed_row)
        sources = _row_sources(parsed_row)
        for s in sources:
            all_doc_names.add(s.doc_name)
        doc_ctn_total += _coerce("ctn_qty", fields.get("ctn_qty", 0))

        existing = by_po.get(po)
        if existing is None:
            # PO not in tracker.
            if not shipment_known:
                classification = Classification.NEW_ORDER
                note = f"New shipment {shipment_id}: add PO {po}"
            elif len({s.doc_name for s in sources}) >= 2:
                # Corroborated across multiple inbound docs but absent from the
                # tracker — this should already be there. The catch.
                classification = Classification.MISSING_ROW
                note = (
                    f"PO {po} ({_coerce('ctn_qty', fields.get('ctn_qty', 0))} ctn) is on the "
                    f"{shipment_id} paperwork but missing from the tracker"
                )
            else:
                classification = Classification.ADDED_PO
                note = f"Add PO {po} to existing shipment {shipment_id}"

            proposed_row = _build_proposed_row(shipment_id, po, fields, sources)
            proposed_row.status_color = StatusColor.BLUE   # visually mark a newly added row
            mutations.append(
                Mutation(
                    mutation_id=f"mut-{shipment_id}-{po}-add",
                    type=MutationType.ADD_ROW,
                    shipment_id=shipment_id,
                    row_id=proposed_row.row_id,
                    new_value=f"add row · PO {po} · {proposed_row.ctn_qty} ctn",
                    sources=sources,
                    confidence=_confidence_from_sources(len({s.doc_name for s in sources}), doc.confidence),
                    agent_note=note,
                    classification=classification,
                    proposed_row=proposed_row,
                )
            )
            continue

        # PO present — diff transcription fields only.
        row_changed = False
        for field, parsed_value in fields.items():
            if field in INTERNAL_COLUMNS:
                continue
            tracker_value = getattr(existing, field)
            if _values_differ(field, parsed_value, tracker_value):
                row_changed = True
                mutations.append(
                    Mutation(
                        mutation_id=f"mut-{shipment_id}-{po}-{field}",
                        type=MutationType.UPDATE_FIELD,
                        shipment_id=shipment_id,
                        row_id=existing.row_id,
                        field=field,
                        old_value=_norm(tracker_value),
                        new_value=_norm(parsed_value),
                        sources=sources,
                        confidence=_confidence_from_sources(len({s.doc_name for s in sources}), doc.confidence),
                        agent_note=(
                            f"PO {po}: {field} '{_norm(tracker_value)}' → '{_norm(parsed_value)}'"
                        ),
                        classification=Classification.FIELD_CHANGE,
                    )
                )
        if not row_changed:
            matched += 1

    # ---- summary + rollups ----
    tracker_ctn = sum(r.ctn_qty for r in shipment_rows)
    tracker_pos = sorted({r.customer_po for r in shipment_rows if r.customer_po})
    missing = [po for po in doc_pos if po not in by_po and shipment_known]
    summary = _summary(shipment_id, doc_ctn_total, doc_pos, tracker_ctn, tracker_pos, missing, doc)

    change_count = len(mutations)
    return ReconResult(
        shipment_id=shipment_id,
        summary=summary,
        proposed_mutations=mutations,
        source_doc_count=len(all_doc_names),
        matched_count=matched,
        change_count=change_count,
    )


def _summary(shipment_id, doc_ctn, doc_pos, trk_ctn, trk_pos, missing, doc: ParsedDoc) -> str:
    n_doc_pos = len(set(doc_pos))
    base = (
        f"{shipment_id}: documents show {doc_ctn} ctn across {n_doc_pos} POs "
        f"vs tracker {trk_ctn} ctn / {len(trk_pos)} POs"
    )
    if missing:
        miss = ", ".join(sorted(set(missing)))
        return f"{base}; PO {miss} missing"
    if not doc_pos:
        return f"{shipment_id}: no order lines found in document"
    return f"{base}; in sync"
