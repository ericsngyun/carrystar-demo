import asyncio
from pathlib import Path

import pytest

from carrystar.contracts import Classification, MutationStatus, MutationType
from carrystar.engine.reconcile import reconcile
from carrystar.loop import orchestrator
from carrystar.loop.merge import merge_parsed_docs
from carrystar.parsers import parsers
from carrystar.replay import RossReplaySource
from carrystar.seams import dev_stub, registry
from carrystar.store import store
from tests.fixtures import initial_tracker_rows


ROSS_DIR = Path(__file__).resolve().parents[1] / "data" / "emails" / "ross-cs02411883"


@pytest.fixture()
def real_seams(tmp_path: Path):
    real_store = store(tmp_path / "tracker.sqlite3")
    real_replay = RossReplaySource(cache_path=tmp_path / "run.json")
    registry.register_parsers(parsers())
    registry.register_store(real_store)
    registry.register_replay(real_replay)
    try:
        yield real_store, real_replay
    finally:
        registry.register_parsers(dev_stub.parsers())
        registry.register_store(dev_stub.store())
        registry.register_replay(dev_stub.replay())


def _order_docs():
    p = parsers()
    return [
        p.parse_path(ROSS_DIR / "Book6.xlsx"),
        p.parse_path(ROSS_DIR / "BOL_CS02411883_original.docx"),
        p.parse_path(ROSS_DIR / "Pick Slips - Export - 2026-06-15T111006.232.pdf"),
    ]


def test_real_parser_doc_totals():
    p = parsers()
    export = p.parse_path(ROSS_DIR / "Book6.xlsx")
    original = p.parse_path(ROSS_DIR / "BOL_CS02411883_original.docx")
    revised = p.parse_path(ROSS_DIR / "BOL_CS02411883_revised.docx")

    assert len(export.rows) == 5 and sum(row["ctn_qty"] for row in export.rows) == 662
    assert len(original.rows) == 5 and sum(row["ctn_qty"] for row in original.rows) == 662
    assert len(revised.rows) == 4 and sum(row["ctn_qty"] for row in revised.rows) == 559


def test_real_act1_reconcile_flags_one_triple_sourced_missing_row():
    merged = merge_parsed_docs(_order_docs())
    result = reconcile(initial_tracker_rows(), merged)

    missing = [m for m in result.proposed_mutations if m.classification == Classification.MISSING_ROW]
    assert len(missing) == 1
    mutation = missing[0]
    assert mutation.proposed_row is not None
    assert mutation.proposed_row.customer_po == "11667250"
    assert mutation.proposed_row.ctn_qty == 103
    source_names = {source.doc_name for source in mutation.sources}
    assert "Book6.xlsx" in source_names
    assert "BOL_CS02411883_original.docx" in source_names
    assert "Pick Slips - Export - 2026-06-15T111006.232.pdf" in source_names
    assert len(source_names) >= 3


def test_real_act2_revised_bol_reconcile_is_in_sync():
    revised = parsers().parse_path(ROSS_DIR / "BOL_CS02411883_revised.docx")
    merged = merge_parsed_docs([revised])
    result = reconcile(initial_tracker_rows(), merged)

    assert result.proposed_mutations == []
    assert result.matched_count == 4
    assert "in sync" in result.summary
    assert "11667250 missing" not in result.summary


def test_real_replay_beats_have_paths_and_derived_rescind(real_seams):
    _, replay = real_seams
    beats = replay.beats()

    assert [beat.beat_id for beat in beats] == ["ross-1-order", "ross-2-revision"]
    assert beats[0].parsed_docs == [] and beats[1].parsed_docs == []
    assert [Path(path).name for path in beats[0].attachment_paths] == [
        "Book6.xlsx",
        "BOL_CS02411883_original.docx",
        "Pick Slips - Export - 2026-06-15T111006.232.pdf",
    ]
    assert [Path(path).name for path in beats[1].attachment_paths] == ["BOL_CS02411883_revised.docx"]
    assert beats[1].rescinds == ["11667250"]

    cached = replay.cached_run()
    assert cached is not None
    assert cached["beats"][1]["rescinds"] == ["11667250"]
    assert (Path(replay.cache_path)).exists()


def test_real_loop_supersedes_pending_catch(real_seams):
    async def main():
        from carrystar.api.state import AppState

        app = AppState()
        await app.begin_replay()
        await orchestrator.deliver_next(app, 0.0)
        pending = app.pending_list()
        assert len(pending) == 1
        assert pending[0].proposed_row.customer_po == "11667250"

        await orchestrator.deliver_next(app, 0.0)
        assert app.pending_list() == []
        superseded = app.get_pending(pending[0].mutation_id)
        assert superseded.status == MutationStatus.SUPERSEDED
        assert sum(row.ctn_qty for row in registry.get_store().get_state()) == 559

    asyncio.run(main())


def test_real_loop_approved_catch_gets_rescinded_remove(real_seams):
    async def main():
        from carrystar.api.state import AppState

        app = AppState()
        await app.begin_replay()
        await orchestrator.deliver_next(app, 0.0)
        add = app.pending_list()[0]
        await app.approve(add.mutation_id)
        assert sum(row.ctn_qty for row in registry.get_store().get_state()) == 662

        await orchestrator.deliver_next(app, 0.0)
        removals = [m for m in app.pending_list() if m.type == MutationType.REMOVE_ROW]
        assert len(removals) == 1
        assert removals[0].classification == Classification.RESCINDED
        await app.approve(removals[0].mutation_id)
        rows = registry.get_store().get_state()
        assert len(rows) == 4
        assert sum(row.ctn_qty for row in rows) == 559

    asyncio.run(main())
