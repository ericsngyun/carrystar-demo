"""Replay source for the real staged Ross email thread."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from carrystar.config import CACHE_DIR, DATA_DIR
from carrystar.contracts import Beat
from carrystar.parsers import parse_bol_docx, parsers


ROSS_BOL = "CS02411883"
DATA_DIR_ROSS = DATA_DIR / "ross-cs02411883"
CACHE_PATH = CACHE_DIR / "run.json"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _relative_name(path: Path) -> str:
    return path.name


@dataclass(frozen=True)
class StagedEmailPacket:
    packet_id: str
    account: str
    subject: str
    attachment_paths: list[Path]


class RossReplaySource:
    def __init__(self, data_dir: Path = DATA_DIR_ROSS, cache_path: Path = CACHE_PATH) -> None:
        self.data_dir = data_dir
        self.cache_path = cache_path

    def packets(self) -> list[StagedEmailPacket]:
        return [
            StagedEmailPacket(
                packet_id="ross-cs02411883-order",
                account="ROSS",
                subject="Load CS02411883 - pickup 06/17, adding PO 11667250",
                attachment_paths=self._order_paths(),
            ),
            StagedEmailPacket(
                packet_id="ross-cs02411883-revision",
                account="ROSS",
                subject="RE: Load CS02411883 - revised BOL (PO 11667250 pulled)",
                attachment_paths=self._revision_paths(),
            ),
        ]

    def beats(self) -> list[Beat]:
        order_paths = self._order_paths()
        revision_paths = self._revision_paths()
        return [
            Beat(
                beat_id="ross-1-order",
                kind="order",
                shipment_id=ROSS_BOL,
                account="ROSS",
                sender="Lina Vincelli - Mark Edwards Apparel",
                subject="Load CS02411883 - pickup 06/17, adding PO 11667250",
                email_body=_read_text(self.data_dir / "email1_add_instruction.txt"),
                attachment_names=[_relative_name(p) for p in order_paths],
                attachment_paths=[str(p) for p in order_paths],
                parsed_docs=[],
            ),
            Beat(
                beat_id="ross-2-revision",
                kind="revision",
                shipment_id=ROSS_BOL,
                account="ROSS",
                sender="Lina Vincelli - Mark Edwards Apparel",
                subject="RE: Load CS02411883 - revised BOL (PO 11667250 pulled)",
                email_body=_read_text(self.data_dir / "email2_revision.txt"),
                rescinds=self._derive_rescinds(),
                attachment_names=[_relative_name(p) for p in revision_paths],
                attachment_paths=[str(p) for p in revision_paths],
                parsed_docs=[],
            ),
        ]

    def cached_run(self) -> dict | None:
        self.write_cache()
        if not self.cache_path.exists():
            return None
        return json.loads(self.cache_path.read_text(encoding="utf-8"))

    def write_cache(self) -> Path:
        parser_registry = parsers()
        beats = self.beats()
        parsed_by_beat = {
            beat.beat_id: [parser_registry.parse_path(Path(path)).model_dump(mode="json") for path in beat.attachment_paths]
            for beat in beats
        }
        payload = {
            "version": 1,
            "source": "ross-cs02411883-real-files",
            "beats": [beat.model_dump(mode="json") for beat in beats],
            "parsed_docs": parsed_by_beat,
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return self.cache_path

    def _order_paths(self) -> list[Path]:
        # Pick slip intentionally dropped from the demo packet (b72f0ee): it is
        # corroboration-only, and parsing it live triggers multi-second OCR that
        # blocks the agent loop. The catch stays multi-sourced via the order
        # export + original BOL. The real PDF remains on disk for the parser.
        return [
            self.data_dir / "Book6.xlsx",
            self.data_dir / "BOL_CS02411883_original.docx",
        ]

    def _revision_paths(self) -> list[Path]:
        return [self.data_dir / "BOL_CS02411883_revised.docx"]

    def _derive_rescinds(self) -> list[str]:
        original = parse_bol_docx(self.data_dir / "BOL_CS02411883_original.docx")
        revised = parse_bol_docx(self.data_dir / "BOL_CS02411883_revised.docx")
        original_pos = {str(row.get("customer_po", "")).strip() for row in original.rows if row.get("customer_po")}
        revised_pos = {str(row.get("customer_po", "")).strip() for row in revised.rows if row.get("customer_po")}
        return sorted(original_pos - revised_pos)


_REPLAY: RossReplaySource | None = None


def replay() -> RossReplaySource:
    global _REPLAY
    if _REPLAY is None:
        _REPLAY = RossReplaySource()
    return _REPLAY
