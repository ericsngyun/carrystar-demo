from pathlib import Path

from carrystar.contracts import DocType
from carrystar.parsers import DocumentParserRegistry, parse_bol_docx, parse_order_export_xlsx, parse_pickslip_pdf


ROSS_DIR = Path(__file__).resolve().parents[1] / "data" / "emails" / "ross-cs02411883"


def test_parse_order_export_xlsx_regression_lock():
    doc = parse_order_export_xlsx(ROSS_DIR / "Book6.xlsx")

    assert doc.doc_type == DocType.ORDER_EXPORT_XLSX
    assert doc.confidence >= 0.9
    assert len(doc.rows) == 5
    cartons = [row["ctn_qty"] for row in doc.rows]
    assert cartons == [103, 330, 10, 10, 209]
    assert sum(cartons) == 662

    row = next(row for row in doc.rows if row["customer_po"] == "11667250")
    assert row["ctn_qty"] == 103
    assert row["pc_qty"] == 3605
    assert row["style"] == "82355J-IU"
    assert row["container"] == "MATU2103718"
    assert row["import_po"] == "221777"
    assert row["date_of_etd"] == "27 May, 2026"
    assert "11667250=HEATHER GREY" in doc.notes


def test_parse_original_bol_docx_regression_lock():
    doc = parse_bol_docx(ROSS_DIR / "BOL_CS02411883_original.docx")

    assert doc.doc_type == DocType.BOL_DOCX
    assert doc.shipment_id == "CS02411883"
    assert doc.confidence >= 0.9
    assert [row["customer_po"] for row in doc.rows] == [
        "11722464",
        "11573709",
        "11573712",
        "11626058",
        "11667250",
    ]
    assert [row["ctn_qty"] for row in doc.rows] == [209, 10, 10, 330, 103]
    assert "total_pkgs=662; total_weight=21434" in doc.notes
    assert "carrier=SWIFT TRANSPORTATION" in doc.notes
    assert "ROSS STORES" in doc.notes and "PERRIS, CA 92571" in doc.notes
    assert next(row for row in doc.rows if row["customer_po"] == "11667250")["ctn_qty"] == 103


def test_parse_revised_bol_docx_regression_lock():
    doc = parse_bol_docx(ROSS_DIR / "BOL_CS02411883_revised.docx")

    assert [row["customer_po"] for row in doc.rows] == ["11722464", "11573709", "11573712", "11626058"]
    assert [row["ctn_qty"] for row in doc.rows] == [209, 10, 10, 330]
    assert sum(row["ctn_qty"] for row in doc.rows) == 559
    assert "total_pkgs=559; total_weight=17470" in doc.notes


def test_parse_pickslip_pdf_corroboration_row():
    doc = parse_pickslip_pdf(ROSS_DIR / "Pick Slips - Export - 2026-06-15T111006.232.pdf")

    assert doc.doc_type == DocType.PICKSLIP_PDF
    assert doc.shipment_id == "CS02411883"
    assert doc.confidence > 0
    assert [row["customer_po"] for row in doc.rows] == ["11667250"]
    row = doc.rows[0]
    assert row["import_po"] == "221777"
    assert row["pc_qty"] == 3605
    assert row["_sources"][0]["doc_name"] == "Pick Slips - Export - 2026-06-15T111006.232.pdf"


def test_parser_registry_dispatches_by_extension():
    registry = DocumentParserRegistry()

    assert registry.parse_path(ROSS_DIR / "Book6.xlsx").doc_type == DocType.ORDER_EXPORT_XLSX
    assert registry.parse_path(ROSS_DIR / "BOL_CS02411883_original.docx").doc_type == DocType.BOL_DOCX
    assert registry.parse_path(ROSS_DIR / "Pick Slips - Export - 2026-06-15T111006.232.pdf").doc_type == DocType.PICKSLIP_PDF
    assert registry.parse_path(ROSS_DIR / "email1_add_instruction.txt").doc_type == DocType.UNKNOWN
