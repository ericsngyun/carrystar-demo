from pathlib import Path

import pytest

from carrystar.contracts import Mutation, MutationStatus, MutationType
from carrystar.seams import dev_stub
from carrystar.store import store
from tests.fixtures import initial_tracker_rows


def test_initial_tracker_fixture_matches_dev_stub():
    assert [r.model_dump(mode="json") for r in initial_tracker_rows()] == [
        r.model_dump(mode="json") for r in dev_stub._initial_rows()
    ]


def test_sqlite_store_seed_and_reset(tmp_path: Path):
    s = store(tmp_path / "tracker.sqlite3")
    rows = s.get_state()

    assert len(rows) == 4
    assert sum(row.ctn_qty for row in rows) == 559
    assert [row.customer_po for row in rows] == ["11626058", "11573709", "11573712", "11722464"]
    assert [row.wms_ticket for row in rows] == ["151385", "151386", "151387", "151388"]
    assert all(row.ds == "06/19@8AM" for row in rows)
    assert rows[-1].status_color.value == "red"

    rows[0].ctn_qty = 1
    s.reset()
    assert sum(row.ctn_qty for row in s.get_state()) == 559


def test_sqlite_store_rejects_non_approved_mutations(tmp_path: Path):
    s = store(tmp_path / "tracker.sqlite3")
    mutation = Mutation(
        mutation_id="mut-test",
        type=MutationType.UPDATE_FIELD,
        shipment_id="CS02411883",
        row_id="row-ross-11626058",
        field="ctn_qty",
        old_value="330",
        new_value="331",
    )

    with pytest.raises(ValueError):
        s.apply_mutation(mutation)


def test_sqlite_store_update_add_remove_and_mirror(tmp_path: Path):
    s = store(tmp_path / "tracker.sqlite3")

    update = Mutation(
        mutation_id="mut-update",
        type=MutationType.UPDATE_FIELD,
        shipment_id="CS02411883",
        row_id="row-ross-11626058",
        field="ctn_qty",
        old_value="330",
        new_value="331",
        status=MutationStatus.APPROVED,
    )
    assert s.apply_mutation(update).ctn_qty == 331

    add_row = initial_tracker_rows()[0].model_copy(update={"row_id": "row-test-add", "customer_po": "99999999"})
    add = Mutation(
        mutation_id="mut-add",
        type=MutationType.ADD_ROW,
        shipment_id="CS02411883",
        row_id=add_row.row_id,
        new_value="add row",
        proposed_row=add_row,
        status=MutationStatus.APPROVED,
    )
    assert s.apply_mutation(add).customer_po == "99999999"
    assert s.get_row_by_po("CS02411883", "99999999") is not None

    remove = Mutation(
        mutation_id="mut-remove",
        type=MutationType.REMOVE_ROW,
        shipment_id="CS02411883",
        row_id="row-test-add",
        new_value="remove row",
        status=MutationStatus.EDITED,
    )
    assert s.apply_mutation(remove).customer_po == "99999999"
    assert s.get_row("row-test-add") is None

    mirror = s.write_mirror_xlsx(tmp_path / "mirror.xlsx")
    assert mirror.exists()
