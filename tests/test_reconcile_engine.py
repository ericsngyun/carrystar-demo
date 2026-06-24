"""WS-3 engine tests — self-contained (inline ParsedDoc / state).

These exercise the reconciliation engine in isolation. The shared WS-7 fixtures
+ the cross-cutting regression lock are Codex-owned; this file only proves the
engine logic the Claude lane owns.
"""

from carrystar.contracts import (
    INTERNAL_COLUMNS,
    Classification,
    DocType,
    MutationType,
    ParsedDoc,
    StatusColor,
    TrackerRow,
)
from carrystar.engine.reconcile import reconcile

SHIP = "CS02411883"


def _tracker_4rows() -> list[TrackerRow]:
    """The seeded tracker: 4 Ross rows / 559 ctn (PO 11667250 absent)."""
    spec = [
        ("11626058", "CAAU4749341", "76284J-AK", 9900, 330),
        ("11573709", "CAAU9809171", "85739J-AD", 600, 10),
        ("11573712", "CAAU9809171", "85739J-AG", 600, 10),
        ("11722464", "XYLU8223291", "85404J-AA", 10002, 209),
    ]
    return [
        TrackerRow(
            row_id=f"row-{SHIP}-{po}", shipment_id=SHIP, account="ROSS", bol_number=SHIP,
            container=cont, style=style, customer_po=po, pc_qty=pc, ctn_qty=ctn,
            pallet="FL/LOAD" if po == "11722464" else "",
            status_color=StatusColor.PLAIN,
        )
        for (po, cont, style, pc, ctn) in spec
    ]


def _merged_doc() -> ParsedDoc:
    """ParsedDoc as WS-4 would hand it to the engine: one row per PO, with
    accumulated provenance. PO 11667250 is triple-sourced."""
    oe = {"doc_name": "Book6.xlsx", "locator": "Sheet1"}
    bol = {"doc_name": "BOL_CS02411883.docx", "locator": "Customer Order Number table"}
    email = {"doc_name": "email body (Carrystar)", "locator": "order instruction"}
    rows = [
        {"customer_po": "11626058", "ctn_qty": 330, "_sources": [oe, bol]},
        {"customer_po": "11573709", "ctn_qty": 10, "_sources": [oe, bol]},
        {"customer_po": "11573712", "ctn_qty": 10, "_sources": [oe, bol]},
        {"customer_po": "11722464", "ctn_qty": 209, "pallet": "FL/LOAD", "_sources": [oe, bol]},
        {"customer_po": "11667250", "ctn_qty": 103, "import_po": "221777",
         "container": "MATU2103718", "style": "82355J-IU",
         "_sources": [oe, bol, email]},
    ]
    return ParsedDoc(doc_id="ross-merged", doc_name="Ross packet", doc_type=DocType.UNKNOWN,
                     shipment_id=SHIP, rows=rows, confidence=0.95)


def test_ross_catch_missing_po_11667250():
    result = reconcile(_tracker_4rows(), _merged_doc())

    assert result.shipment_id == SHIP
    # exactly one missing_row, and it is the hero PO
    missing = [m for m in result.proposed_mutations if m.classification == Classification.MISSING_ROW]
    assert len(missing) == 1, [m.classification for m in result.proposed_mutations]
    m = missing[0]
    assert m.type == MutationType.ADD_ROW
    assert m.proposed_row is not None
    assert m.proposed_row.customer_po == "11667250"
    assert m.proposed_row.ctn_qty == 103
    # triple-sourced
    assert len({s.doc_name for s in m.sources}) == 3
    # corroboration -> high confidence
    assert m.confidence >= 0.95


def test_summary_states_the_gap():
    s = reconcile(_tracker_4rows(), _merged_doc()).summary
    assert "662" in s and "559" in s and "11667250" in s
    assert "5 POs" in s and "4 POs" in s


def test_matched_rows_produce_no_mutation():
    result = reconcile(_tracker_4rows(), _merged_doc())
    # 4 POs already in the tracker with identical ctn -> matched, no change
    assert result.matched_count == 4
    # only the missing PO produces a mutation
    assert result.change_count == 1


def test_authority_boundary_never_touches_internal_columns():
    result = reconcile(_tracker_4rows(), _merged_doc())
    for mut in result.proposed_mutations:
        assert mut.field not in INTERNAL_COLUMNS
        if mut.proposed_row is not None:
            for col in INTERNAL_COLUMNS:
                assert getattr(mut.proposed_row, col) == "", f"internal col {col} was filled"


def test_field_change_detected_for_drifted_value():
    state = _tracker_4rows()
    # tracker has stale carton count on one PO
    state[0].ctn_qty = 300  # real docs say 330
    result = reconcile(state, _merged_doc())
    changes = [m for m in result.proposed_mutations if m.classification == Classification.FIELD_CHANGE]
    assert any(m.field == "ctn_qty" and m.old_value == "300" and m.new_value == "330" for m in changes)


def test_new_order_when_shipment_unknown():
    # empty tracker -> every PO is a new_order add
    result = reconcile([], _merged_doc())
    assert all(
        m.classification == Classification.NEW_ORDER
        for m in result.proposed_mutations
    )
    assert len(result.proposed_mutations) == 5
