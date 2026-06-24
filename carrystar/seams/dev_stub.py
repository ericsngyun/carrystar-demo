"""Claude-owned DEV STUB for the Codex-lane seams (WS-1/2/5).

PURPOSE: let the API + agent loop + UI run end-to-end on the *verified-real*
Ross packet (CS02411883) BEFORE Codex's parsers/store/replay land, so the
skeleton streams and the pending->approve->commit motion is demonstrable.

This is an integration affordance (WS-INT, Claude lane). It is NOT WS-1/2/5 —
those are real modules Codex will write in carrystar/parsers/, carrystar/store.py,
carrystar/replay.py. When they land, the registry prefers them and this stub is
bypassed. Do not grow product logic here.

Data provenance:
  - Order-export rows + carton totals: REAL, parsed from data/.../Book6.xlsx.
  - BOL customer-order table: REAL, parsed from data/.../BOL_CS02411883.docx.
  - Email-body instruction line: ILLUSTRATIVE placeholder for the third source
    (the actual email text was not available); replace with the real body.
"""

from __future__ import annotations

from pathlib import Path

from carrystar.contracts import (
    DocType,
    Mutation,
    MutationStatus,
    MutationType,
    ParsedDoc,
    StatusColor,
    TrackerRow,
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "emails" / "ross-cs02411883"
ROSS_BOL = "CS02411883"

# --- The 5 real order-export lines (Book6.xlsx). Cartons sum to 662. ---------
# (customer_po, import_po, container, etd_text, style, color, pc_qty, ctn_qty)
_ROSS_LINES = [
    ("11667250", "221777", "MATU2103718", "27 May, 2026", "82355J-IU", "HEATHER GREY", 3605, 103),
    ("11626058", "221415", "CAAU4749341", "07 May, 2026", "76284J-AK", "BLACK FLORAL", 9900, 330),
    ("11573709", "219094SS", "CAAU9809171", "12 Mar, 2026", "85739J-AD", "YELLOW", 600, 10),
    ("11573712", "219094SS", "CAAU9809171", "12 Mar, 2026", "85739J-AG", "NAVY", 600, 10),
    ("11722464", "221915", "XYLU8223291", "21 May, 2026", "85404J-AA", "BLUE", 10002, 209),
]
# PO present in source docs but intentionally absent from the seeded tracker:
_MISSING_PO = "11667250"


def _initial_rows() -> list[TrackerRow]:
    """Seeded tracker: 4 Ross rows / 559 ctn. PO 11667250 (103) is missing —
    that gap is the demo's hero catch."""
    rows: list[TrackerRow] = []
    for po, imp, cont, etd, style, _color, pc, ctn in _ROSS_LINES:
        if po == _MISSING_PO:
            continue
        rows.append(
            TrackerRow(
                row_id=f"row-ross-{po}",
                shipment_id=ROSS_BOL,
                account="ROSS",
                bol_number=ROSS_BOL,
                container=cont,
                date_of_etd=etd,
                import_po=imp,
                style=style,
                customer_po=po,
                ctn_qty=ctn,
                pallet="FL/LOAD" if po == "11722464" else "",
                pc_qty=pc,
                status_color=StatusColor.PLAIN,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Dev ParserRegistry — returns ParsedDocs for the Ross packet's documents.
# ---------------------------------------------------------------------------


class _DevParsers:
    def _order_export(self) -> ParsedDoc:
        rows = []
        for i, (po, imp, cont, etd, style, _c, pc, ctn) in enumerate(_ROSS_LINES, start=2):
            rows.append(
                {
                    "account": "ROSS",
                    "bol_number": ROSS_BOL,
                    "container": cont,
                    "date_of_etd": etd,
                    "import_po": imp,
                    "style": style,
                    "customer_po": po,
                    "ctn_qty": ctn,
                    "pc_qty": pc,
                    "_sources": [{"doc_name": "Book6.xlsx", "locator": f"Sheet1 row {i}"}],
                }
            )
        return ParsedDoc(
            doc_id="ross-order-export",
            doc_name="Book6.xlsx",
            doc_type=DocType.ORDER_EXPORT_XLSX,
            shipment_id=ROSS_BOL,
            rows=rows,
            confidence=0.98,
        )

    def _bol(self) -> ParsedDoc:
        # BOL "CUSTOMER ORDER NUMBER" table: PO / #PKGS(cartons) / weight.
        bol_lines = [
            ("11722464", 209, "FLOOR LOAD"),
            ("11573709", 10, ""),
            ("11573712", 10, ""),
            ("11626058", 330, ""),
            ("11667250", 103, ""),
        ]
        rows = []
        for i, (po, ctn, pallet) in enumerate(bol_lines, start=1):
            rows.append(
                {
                    "account": "ROSS",
                    "bol_number": ROSS_BOL,
                    "customer_po": po,
                    "ctn_qty": ctn,
                    "pallet": "FL/LOAD" if pallet else "",
                    "_sources": [
                        {"doc_name": "BOL_CS02411883.docx", "locator": f"Customer Order Number table, row {i}"}
                    ],
                }
            )
        return ParsedDoc(
            doc_id="ross-bol",
            doc_name="BOL_CS02411883.docx",
            doc_type=DocType.BOL_DOCX,
            shipment_id=ROSS_BOL,
            rows=rows,
            confidence=0.95,
        )

    def _email_instruction(self) -> ParsedDoc:
        # ILLUSTRATIVE third source — replace with the real email body text.
        return ParsedDoc(
            doc_id="ross-email",
            doc_name="email body (Carrystar)",
            doc_type=DocType.EMAIL_BODY,
            shipment_id=ROSS_BOL,
            rows=[
                {
                    "customer_po": "11667250",
                    "ctn_qty": 103,
                    "_sources": [{"doc_name": "email body (Carrystar)", "locator": "order instruction"}],
                }
            ],
            confidence=0.6,
            notes="Illustrative placeholder for the email instruction (third source).",
        )

    def parse_path(self, path: Path) -> ParsedDoc:
        name = path.name.lower()
        if name.endswith(".xlsx"):
            return self._order_export()
        if name.endswith(".docx"):
            return self._bol()
        return self._email_instruction()

    def parse_packet(self) -> list[ParsedDoc]:
        """Convenience for the dev replay: all docs of the Ross packet."""
        return [self._order_export(), self._bol(), self._email_instruction()]


# ---------------------------------------------------------------------------
# Dev Store — in-memory tracker + minimal xlsx mirror.
# ---------------------------------------------------------------------------


class _DevStore:
    def __init__(self) -> None:
        self._rows: list[TrackerRow] = _initial_rows()

    def get_state(self) -> list[TrackerRow]:
        return [r.model_copy(deep=True) for r in self._rows]

    def get_row(self, row_id: str) -> TrackerRow | None:
        for r in self._rows:
            if r.row_id == row_id:
                return r.model_copy(deep=True)
        return None

    def apply_mutation(self, mutation: Mutation) -> TrackerRow:
        if mutation.status not in (MutationStatus.APPROVED, MutationStatus.EDITED):
            raise ValueError(
                f"refusing to apply mutation {mutation.mutation_id} with status "
                f"{mutation.status} — only approved/edited mutations commit"
            )
        if mutation.type == MutationType.ADD_ROW:
            row = (mutation.proposed_row or TrackerRow(row_id=mutation.row_id or mutation.mutation_id,
                                                       shipment_id=mutation.shipment_id))
            self._rows.append(row.model_copy(deep=True))
            return row
        # update_field
        for r in self._rows:
            if r.row_id == mutation.row_id:
                setattr(r, mutation.field, _coerce(mutation.field, mutation.new_value))
                return r.model_copy(deep=True)
        raise KeyError(f"row {mutation.row_id} not found for update_field")

    def write_mirror_xlsx(self, path: Path) -> Path:
        import openpyxl
        from openpyxl.styles import Font, PatternFill

        from carrystar.contracts import TRACKER_COLUMNS

        fills = {
            "green": PatternFill("solid", fgColor="C6EFCE"),
            "blue": PatternFill("solid", fgColor="BDD7EE"),
            "red": PatternFill("solid", fgColor="FFC7CE"),
            "plain": PatternFill(fill_type=None),
        }
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Tracker"
        ws.append(list(TRACKER_COLUMNS))
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in self._rows:
            ws.append([getattr(r, col) for col in TRACKER_COLUMNS])
            fill = fills.get(r.status_color.value, fills["plain"])
            for c in ws[ws.max_row]:
                c.fill = fill
        path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(path)
        return path

    def reset(self) -> None:
        self._rows = _initial_rows()


def _coerce(field: str, value: str):
    if field in ("ctn_qty", "pc_qty"):
        try:
            return int(str(value).replace(",", "").strip() or 0)
        except ValueError:
            return 0
    return value


# ---------------------------------------------------------------------------
# Dev ReplaySource — just the Ross packet.
# ---------------------------------------------------------------------------


class _DevPacket:
    packet_id = "ross-cs02411883"
    account = "ROSS"
    subject = "CS02411883 — Ross / Mark Edwards Apparel (5 POs, 662 ctn)"

    @property
    def attachment_paths(self) -> list[Path]:
        return [DATA_DIR / "Book6.xlsx", DATA_DIR / "BOL_CS02411883.docx"]


class _DevReplay:
    def packets(self):
        return [_DevPacket()]

    def cached_run(self):
        return None


# --- module-level singletons (dev stub is stateful for the store) ------------
_PARSERS = _DevParsers()
_STORE = _DevStore()
_REPLAY = _DevReplay()


def parsers() -> _DevParsers:
    return _PARSERS


def store() -> _DevStore:
    return _STORE


def replay() -> _DevReplay:
    return _REPLAY
