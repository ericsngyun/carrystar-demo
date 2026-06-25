"""Canonical initial tracker seed (the customer's real Ross sheet state).

Lives in the package (not tests/) so production code — the store seam — can
load it without depending on the test suite. Mirrors the customer's actual
tracker screenshot: 4 Ross rows / 559 ctn, with their internal WMS tickets and
D-S, and PO 11667250 absent (the hero gap).
"""

from __future__ import annotations

from carrystar.contracts import StatusColor, TrackerRow

ROSS_BOL = "CS02411883"


def initial_tracker_rows() -> list[TrackerRow]:
    spec = [
        ("11626058", "CAAU4749341", "07 May, 2026", "221415", "76284J-AK", 330, 9900, "151385", StatusColor.PLAIN),
        ("11573709", "CAAU9809171", "12 Mar, 2026", "219094SS", "85739J-AD", 10, 600, "151386", StatusColor.PLAIN),
        ("11573712", "CAAU9809171", "12 Mar, 2026", "219094SS", "85739J-AG", 10, 600, "151387", StatusColor.PLAIN),
        ("11722464", "XYLU8223291", "21 May, 2026", "221915", "85404J-AA", 209, 10002, "151388", StatusColor.RED),
    ]
    return [
        TrackerRow(
            row_id=f"row-ross-{po}",
            shipment_id=ROSS_BOL,
            account="ROSS",
            bol_number=ROSS_BOL,
            container=container,
            date_of_etd=etd,
            import_po=import_po,
            style=style,
            customer_po=po,
            ctn_qty=ctn_qty,
            pallet="FL/LOAD",
            pc_qty=pc_qty,
            ds="06/19@8AM",
            wms_ticket=wms_ticket,
            status_color=status,
        )
        for po, container, etd, import_po, style, ctn_qty, pc_qty, wms_ticket, status in spec
    ]
