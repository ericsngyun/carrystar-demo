"""Lightweight ground-truth readout — a DEMO affordance, NOT an eval framework.

Surfaces the agent's extraction against the known-correct Ross source values as a
one-line "verified against source" statement (shown in the UI activity feed), so
the room gets an explicit accuracy line. Gated to the Ross demo shipment; the
exact values the regression tests already assert. No model comparison, no harness.
"""

from __future__ import annotations

from carrystar.contracts import ParsedDoc

_SHIPMENT = "CS02411883"
_EXPECTED_POS = {"11722464", "11573709", "11573712", "11626058", "11667250"}
_EXPECTED_CARTONS = 662
_HERO = {"po": "11667250", "ctn": 103, "style": "82355J-IU", "container": "MATU2103718"}


def order_accuracy_line(merged: ParsedDoc) -> str | None:
    """One-line extraction-vs-source readout for the Ross order; None otherwise."""
    if merged.shipment_id != _SHIPMENT:
        return None
    pos = {str(r.get("customer_po")) for r in merged.rows if r.get("customer_po")}
    total = sum(int(r.get("ctn_qty", 0) or 0) for r in merged.rows)
    hero = next((r for r in merged.rows if str(r.get("customer_po")) == _HERO["po"]), {})
    ok = (
        pos == _EXPECTED_POS
        and total == _EXPECTED_CARTONS
        and int(hero.get("ctn_qty", 0) or 0) == _HERO["ctn"]
        and hero.get("style") == _HERO["style"]
        and hero.get("container") == _HERO["container"]
    )
    mark = "✓" if ok else "⚠"
    return (
        f"{mark} extraction verified vs source — {len(pos & _EXPECTED_POS)}/5 POs, "
        f"{total}/{_EXPECTED_CARTONS} cartons; PO {_HERO['po']}: {hero.get('ctn_qty')} ctn · "
        f"{hero.get('style')} · {hero.get('container')}"
    )
