# Codex handoff — WS-1 / WS-2 / WS-5 / WS-7

The Claude lane (WS-0/3/4/6) is built and the contracts are **frozen**. Build the
following against `carrystar/contracts.py` and `carrystar/interfaces.py` as
**read-only**. Do not edit Claude-lane files; if a signature is wrong, flag a
contract bump rather than forking.

Concrete impls plug in via `carrystar/seams/registry.py`:
`register_parsers(...)`, `register_store(...)`, `register_replay(...)`. Once
registered, the registry prefers them over the dev stub. Wire registration in a
small `carrystar/bootstrap.py` (Codex-owned) imported at app startup.

**Contract surface (frozen, v2).** Beyond the core models, note:
`MutationType.REMOVE_ROW` (compensating removal), `MutationStatus.SUPERSEDED`
(a pending proposal withdrawn by a later email), `Classification.RESCINDED`,
`Beat` (one inbound email in a packet timeline), and `ReplaySource.beats()`.
The loop processes one Beat per inbound email so threads unfold as they did.

**Two-act revision flow (the hero).** The Ross thread is two beats: an `order`
beat (original docs, 662/5) then a `revision` beat (revised BOL 559/4, `rescinds`
= `["11667250"]`). The loop handles rescission itself (supersede pending / propose
removal); your parsers + replay just need to surface the two beats and the
rescind intent. Real source data for ALL accounts is already staged under
`data/emails/<account>/` (+ `MANIFEST.json`).

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
**5 rows / 662 cartons**; the **original** BOL (`BOL_CS02411883_original.docx`)
yields the same 5 POs / 662; the **revised** BOL (`BOL_CS02411883_revised.docx`)
yields **4 POs / 559** (PO `11667250` removed). The five POs: `11667250`/103,
`11626058`/330, `11573709`/10, `11573712`/10, `11722464`/209.

## WS-2 — Store + mirror → `carrystar/store.py`
Implement the `Store` Protocol. SQLite single-file (Postgres is a pilot swap,
same schema). `get_state()`, `get_row()`, `apply_mutation()` (must reject
non-approved mutations — there is no auto-commit), `write_mirror_xlsx()`
(14-column layout + `status_color` cell fills), `reset()` (reload initial state
from fixtures). Load initial state from WS-7 fixtures.

## WS-5 — Replay harness + cache → `carrystar/replay.py`
Implement `ReplaySource.beats()` returning ordered `Beat`s. **Order so Ross lands
as the climax**, and its `revision` beat (rescinds `11667250`) follows its `order`
beat. `live` mode parses real attachments now; `replay` mode streams cached
outputs (`cache/run.json`) on a timer. (See `dev_stub.py` `_DevReplay.beats()`
for the exact two-beat shape to mirror.)

## WS-7 — Fixtures + tests → `tests/fixtures.py`, `tests/test_*.py`
- Seeded initial tracker = **4 Ross rows / 559 ctn** (POs 11626058, 11573709,
  11573712, 11722464) — including the real internal columns (WMS tickets
  151385-151388, D-S `06/19@8AM`). PO `11667250` (103 ctn) intentionally absent.
  (See `dev_stub.py` `_initial_rows()`; promote those exact values into the fixture.)
- **Regression tests:** (a) Act 1 — the Ross `ReconResult` flags `missing_row`
  for PO `11667250` / 103 ctn with ≥3 sources. (b) Revised BOL → 4 POs / 559.
  (c) Act 2 — a pending catch is `superseded` by the revision; an already-approved
  catch yields a `rescinded` `remove_row` proposal. (Claude-lane engine + loop
  tests already cover the logic in `tests/test_reconcile_engine.py` and
  `tests/test_loop_integration.py` — mirror their assertions against real parses.)
- Unit tests per parser (assert the carton totals above).

---

### Claude-lane interfaces you build against (frozen)
- `ParsedDoc(doc_id, doc_name, doc_type, shipment_id, rows[dict], confidence, notes)`
  — rows use TRACKER_COLUMNS names + `"_sources"`.
- `Mutation(type, shipment_id, row_id?, field?, old_value?, new_value, sources[],
  confidence, status, agent_note, classification, proposed_row?)`.
- Authority boundary: parsers/engine may fill the **10 transcription columns**;
  the **4 internal columns** (`rush_carton, ds, wms_ticket, needs_labels`) are
  flagged, never invented.
