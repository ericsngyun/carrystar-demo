# Codex handoff — WS-1 / WS-2 / WS-5 / WS-7

The Claude lane (WS-0/3/4/6) is built and the contracts are **frozen**. Build the
following against `carrystar/contracts.py` and `carrystar/interfaces.py` as
**read-only**. Do not edit Claude-lane files; if a signature is wrong, flag a
contract bump rather than forking.

Concrete impls plug in via `carrystar/seams/registry.py`:
`register_parsers(...)`, `register_store(...)`, `register_replay(...)`. Once
registered, the registry prefers them over the dev stub. Wire registration in a
small `carrystar/bootstrap.py` (Codex-owned) imported at app startup.

---

## WS-1 — Parsers → `carrystar/parsers/`
Implement the `Parser` / `ParserRegistry` Protocols (`interfaces.py`). Each
`parse()` returns a `ParsedDoc` whose `rows` use **TRACKER_COLUMNS** field names
and carry per-field provenance under the reserved row key `"_sources"`
(list of `{doc_name, locator}`). Degrade gracefully — never raise on bad input;
return low `confidence` instead.

- `parse_order_export_xlsx` (openpyxl): Book6 schema → Customer, Customer PO,
  ETA, ETD, Container (`C#: …`, may repeat — dedupe), Import PO, CS BOL, Style,
  Color, Ordered Qty, CARTONS. **Convert Excel date serials** (e.g. 46169) to
  human text matching tracker style (`"07 May, 2026"`).
- `parse_bol_docx` (python-docx): extract the `CUSTOMER ORDER NUMBER / # PKGS /
  WEIGHT` table incl. the TOTAL row, plus ship-to, carrier, BOL number,
  floor-load flag.
- `parse_pickslip_pdf` (pdfplumber): thin text layer — corroboration only;
  never block the pipeline.

**Regression lock (real data, already verified):** the Ross `Book6.xlsx` yields
**5 rows / 662 cartons**; the BOL customer-order table yields the same 5 POs /
662 total. The five POs: `11667250`/103, `11626058`/330, `11573709`/10,
`11573712`/10, `11722464`/209.

## WS-2 — Store + mirror → `carrystar/store.py`
Implement the `Store` Protocol. SQLite single-file (Postgres is a pilot swap,
same schema). `get_state()`, `get_row()`, `apply_mutation()` (must reject
non-approved mutations — there is no auto-commit), `write_mirror_xlsx()`
(14-column layout + `status_color` cell fills), `reset()` (reload initial state
from fixtures). Load initial state from WS-7 fixtures.

## WS-5 — Replay harness + cache → `carrystar/replay.py`
Implement `ReplaySource`. `live` mode runs the real pipeline now; `replay` mode
streams cached agent outputs (`cache/run.json`) on a configurable timer. **Order
the replay so Ross lands as the climax.** Serialize ParsedDocs / ReconResults /
Mutations from a real run into `cache/run.json`.

## WS-7 — Fixtures + tests → `tests/fixtures.py`, `tests/test_*.py`
- Seeded initial tracker = **4 Ross rows / 559 ctn** (POs 11626058, 11573709,
  11573712, 11722464). PO `11667250` (103 ctn) intentionally absent — that gap
  is the hero catch. (See `carrystar/seams/dev_stub.py` `_initial_rows()` for the
  exact field values; promote those into the real fixture.)
- **Regression test:** the Ross `ReconResult` must flag `missing_row` for PO
  `11667250` / 103 ctn with all three sources (BOL line + order-export row +
  email instruction).
- Unit tests per parser (assert the 5 rows / 662 ctn above).

---

### Claude-lane interfaces you build against (frozen)
- `ParsedDoc(doc_id, doc_name, doc_type, shipment_id, rows[dict], confidence, notes)`
  — rows use TRACKER_COLUMNS names + `"_sources"`.
- `Mutation(type, shipment_id, row_id?, field?, old_value?, new_value, sources[],
  confidence, status, agent_note, classification, proposed_row?)`.
- Authority boundary: parsers/engine may fill the **10 transcription columns**;
  the **4 internal columns** (`rush_carton, ds, wms_ticket, needs_labels`) are
  flagged, never invented.
