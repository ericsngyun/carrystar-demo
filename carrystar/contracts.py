"""Frozen shared contracts for the Carrystar real-time agent demo.

OWNERSHIP: authored and owned by Claude Code (WS-0). READ-ONLY for Codex.
Everything in the system binds to these schemas. Do not edit without a contract
bump coordinated across both agent sessions.

Models are pydantic v2 so they serialize cleanly over SSE and validate at the
parser/store seams. Field names mirror the customer's tracker columns exactly.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Column taxonomy + authority boundary
# ---------------------------------------------------------------------------

# The 14 visible tracker columns, in display order. The UI table and the xlsx
# mirror render these left-to-right exactly as the customer's sheet does.
TRACKER_COLUMNS: tuple[str, ...] = (
    "account",
    "bol_number",
    "container",
    "date_of_etd",
    "import_po",
    "style",
    "customer_po",
    "ctn_qty",
    "pallet",
    "pc_qty",
    "rush_carton",
    "ds",
    "wms_ticket",
    "needs_labels",
)

# Authority boundary (enforced in the reconciliation engine, WS-3).
# The agent may propose/fill these 10 columns — they are transcribable from
# inbound documents (order export, BOL, pick slip).
TRANSCRIPTION_COLUMNS: frozenset[str] = frozenset(
    {
        "account",
        "bol_number",
        "container",
        "date_of_etd",
        "import_po",
        "style",
        "customer_po",
        "ctn_qty",
        "pallet",
        "pc_qty",
    }
)

# The agent must FLAG — never invent — these 4 columns. They appear in no
# inbound document; they are assigned inside the customer's own WMS / ops flow.
INTERNAL_COLUMNS: frozenset[str] = frozenset(
    {
        "rush_carton",
        "ds",
        "wms_ticket",
        "needs_labels",
    }
)

assert TRANSCRIPTION_COLUMNS | INTERNAL_COLUMNS == set(TRACKER_COLUMNS)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class StatusColor(str, Enum):
    """Status encoding mirrored from the customer's cell fills."""

    GREEN = "green"
    BLUE = "blue"
    RED = "red"
    PLAIN = "plain"


class DocType(str, Enum):
    ORDER_EXPORT_XLSX = "order_export_xlsx"
    BOL_DOCX = "bol_docx"
    PICKSLIP_PDF = "pickslip_pdf"
    EMAIL_BODY = "email_body"
    UNKNOWN = "unknown"


class MutationType(str, Enum):
    ADD_ROW = "add_row"
    UPDATE_FIELD = "update_field"
    REMOVE_ROW = "remove_row"   # compensating removal (e.g. a rescinded PO already committed)


class MutationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    SUPERSEDED = "superseded"   # a pending proposal withdrawn by a later inbound email


class Classification(str, Enum):
    """How the engine classified a reconciled row. Carried on each Mutation's
    metadata so the UI can color/group proposals."""

    MATCHED = "matched"          # already in tracker, no change
    NEW_ORDER = "new_order"      # whole shipment not in tracker
    ADDED_PO = "added_po"        # shipment present, this PO/line missing
    FIELD_CHANGE = "field_change"  # row present, a transcription field differs
    MISSING_ROW = "missing_row"  # row exists in source docs, absent in tracker
    INTERNAL_FLAG = "internal_flag"  # an internal column needs a human (never auto-filled)
    RESCINDED = "rescinded"      # a prior proposal/row invalidated by a later email (e.g. PO pulled)


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------


class SourceRef(BaseModel):
    """Provenance pointer: which document and where inside it a value came from."""

    doc_name: str = Field(..., description='e.g. "BOL CS02411883.docx" / "Book6.xlsx" / "email body (Lina, 6/15)"')
    locator: str = Field(..., description='e.g. "Customer Order Number table, row 5" / "Sheet1 row 2" / "para 3"')


class TrackerRow(BaseModel):
    """One shipment line in the tracker. 14 visible columns mirror the sheet."""

    row_id: str
    shipment_id: str

    # --- 10 transcription columns (agent may propose) ---
    account: str = ""            # ROSS, BURLINGTON, FRED MEYER, FASHION NOVA, KOHL'S RETAIL/ECOM
    bol_number: str = ""         # CS02411883, DC 810, LEAV5E5T, TBD ...
    container: str = ""          # CAAU4749341 ; may be multi: "XYLU8250804 & CAAU4743127"
    date_of_etd: str = ""        # human text: "07 May, 2026" / "ETA TO WH 6/22"
    import_po: str = ""          # 221415
    style: str = ""              # 76284J-AK
    customer_po: str = ""        # 11626058
    ctn_qty: int = 0             # 330
    pallet: str = ""             # "FL/LOAD" / "23" / ""
    pc_qty: int = 0              # 9900

    # --- 4 internal columns (agent flags, never invents) ---
    rush_carton: str = ""        # operational flag (internal)
    ds: str = ""                 # delivery schedule "06/19@8AM" (internal, email-seeded)
    wms_ticket: str = ""         # 151385 (internal — assigned in their WMS, NOT in any inbound doc)
    needs_labels: str = ""       # "YES"/"" (internal)

    status_color: StatusColor = StatusColor.PLAIN
    source_refs: list[SourceRef] = Field(default_factory=list)


class Mutation(BaseModel):
    """A proposed, human-gated change to the tracker. Never auto-committed."""

    mutation_id: str
    type: MutationType
    shipment_id: str
    row_id: str | None = None      # target row for update_field
    field: str | None = None       # for update_field (one of TRACKER_COLUMNS)
    old_value: str | None = None
    new_value: str
    sources: list[SourceRef] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    status: MutationStatus = MutationStatus.PENDING
    agent_note: str = ""           # human-readable rationale
    classification: Classification = Classification.MATCHED  # set by WS-3

    # For add_row mutations: the full proposed row (so commit can insert it).
    proposed_row: TrackerRow | None = None


class ParsedDoc(BaseModel):
    """Normalized output of a WS-1 parser. rows use TRACKER_COLUMNS field names."""

    doc_id: str
    doc_name: str = ""             # original filename, for provenance
    doc_type: DocType = DocType.UNKNOWN
    shipment_id: str = ""          # parser's best guess at the shipment this belongs to
    rows: list[dict] = Field(default_factory=list)  # normalized fields per contract column names
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    # Optional per-row/per-field provenance, keyed however the parser chooses;
    # the engine reads sources off rows when present (key: "_sources").
    notes: str = ""


class ReconResult(BaseModel):
    """Output of the reconciliation engine (WS-3) for one ParsedDoc vs state."""

    shipment_id: str
    summary: str                   # "BOL 662 ctn / 5 POs vs tracker 559 / 4 POs; PO 11667250 missing"
    proposed_mutations: list[Mutation] = Field(default_factory=list)
    # Convenience rollups for the UI / narration:
    source_doc_count: int = 0
    matched_count: int = 0
    change_count: int = 0          # mutations that are not `matched`


class Beat(BaseModel):
    """One inbound email in a packet's timeline. A shipment can have several —
    e.g. an order email followed by a revision email that rescinds a PO. The
    replay seam (WS-5) emits beats in order; the loop (WS-4) processes one per
    'inbound email' so the demo unfolds as the thread actually did.
    """

    beat_id: str
    kind: str = "order"            # "order" | "revision"
    shipment_id: str = ""
    account: str = ""
    subject: str = ""
    sender: str = ""
    date: str = ""
    email_body: str = ""
    rescinds: list[str] = Field(default_factory=list)   # customer POs this email pulls
    attachment_names: list[str] = Field(default_factory=list)  # for narration
    attachment_paths: list[str] = Field(default_factory=list)  # real path -> parser seam
    # Dev-stub convenience: pre-parsed docs. Real path leaves empty and the loop
    # parses attachment_paths through the WS-1 parser seam instead.
    parsed_docs: list[ParsedDoc] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers shared across workstreams
# ---------------------------------------------------------------------------


def is_transcription_column(field: str) -> bool:
    return field in TRANSCRIPTION_COLUMNS


def is_internal_column(field: str) -> bool:
    return field in INTERNAL_COLUMNS
