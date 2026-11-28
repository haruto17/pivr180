import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from pivr180_device.button import Status
from pivr180_device.status import UNKNOWN_ERROR, StatusBoard, free_bytes
from pivr180_device.storage import CaptureStorage

AOA_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "aoa.schema.json"
FREE = 52_613_349_376


@pytest.fixture(scope="module")
def status_validator() -> Draft202012Validator:
    schema = json.loads(AOA_SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(
        {"$ref": f"{schema['$id']}#/$defs/status"}, registry=registry
    )


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "captures"


@pytest.fixture
def board(root: Path) -> StatusBoard:
    return StatusBoard(CaptureStorage(root), measure_free_bytes=lambda path: FREE)


def make_capture(root: Path, capture_id: str) -> None:
    (root / capture_id).mkdir(parents=True)


def listen(board: StatusBoard) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    received: list[dict[str, Any]] = []
    board.subscribe(received.append)
    return received.pop(0), received


def test_subscribing_gives_the_status_before_the_first_capture(
    board: StatusBoard, status_validator: Draft202012Validator
):
    first, received = listen(board)

    assert first == {
        "type": "status",
        "state": "idle",
        "capture_count": 0,
        "free_bytes": FREE,
        "last_capture": None,
    }
    status_validator.validate(first)
    assert received == []


def test_a_shot_is_passed_on_as_capturing_then_saved_then_idle(
    root: Path, board: StatusBoard, status_validator: Draft202012Validator
):
    _, received = listen(board)

    board.show(Status.CAPTURING)
    make_capture(root, "20261126-031522-000")
    board.saved("20261126-031522-000", sync_warning=True)
    board.show(Status.IDLE)

    last = {"id": "20261126-031522-000", "sync_warning": True}
    assert [(m["state"], m["capture_count"], m["last_capture"]) for m in received] == [
        ("capturing", 0, None),
        ("capturing", 1, last),
        ("idle", 1, last),
    ]
    for message in received:
        status_validator.validate(message)


def test_an_error_carries_its_message_until_the_next_state(
    board: StatusBoard, status_validator: Draft202012Validator
):
    _, received = listen(board)

    board.show(Status.ERROR, "capture failed: disk full")
    board.show(Status.IDLE)

    assert received[0]["error_message"] == "capture failed: disk full"
    assert "error_message" not in received[1]
    for message in received:
        status_validator.validate(message)


def test_an_error_without_a_message_still_says_something(
    board: StatusBoard, status_validator: Draft202012Validator
):
    _, received = listen(board)

    board.show(Status.ERROR)

    assert received[0]["error_message"] == UNKNOWN_ERROR
    status_validator.validate(received[0])


def test_a_message_is_dropped_for_states_other_than_error(board: StatusBoard):
    _, received = listen(board)

    board.show(Status.CAPTURING, "ignored")

    assert "error_message" not in received[0]


def test_nothing_is_passed_on_when_nothing_changed(board: StatusBoard):
    _, received = listen(board)

    board.show(Status.IDLE)
    board.show(Status.CAPTURING)
    board.show(Status.CAPTURING)

    assert [message["state"] for message in received] == ["capturing"]


def test_deleting_the_last_capture_clears_it(root: Path, board: StatusBoard):
    make_capture(root, "20261126-031522-000")
    make_capture(root, "20261126-031522-001")
    board.saved("20261126-031522-001", sync_warning=False)
    _, received = listen(board)

    (root / "20261126-031522-001").rmdir()
    board.deleted("20261126-031522-001")

    assert received == [
        {
            "type": "status",
            "state": "idle",
            "capture_count": 1,
            "free_bytes": FREE,
            "last_capture": None,
        }
    ]


def test_deleting_another_capture_keeps_the_last_one(root: Path, board: StatusBoard):
    make_capture(root, "20261126-031522-000")
    make_capture(root, "20261126-031522-001")
    board.saved("20261126-031522-001", sync_warning=False)
    _, received = listen(board)

    (root / "20261126-031522-000").rmdir()
    board.deleted("20261126-031522-000")

    assert received[0]["capture_count"] == 1
    assert received[0]["last_capture"] == {
        "id": "20261126-031522-001",
        "sync_warning": False,
    }


def test_unsubscribed_listeners_get_nothing(board: StatusBoard):
    received: list[dict[str, Any]] = []
    unsubscribe = board.subscribe(received.append)

    unsubscribe()
    unsubscribe()
    board.show(Status.CAPTURING)

    assert [message["state"] for message in received] == ["idle"]


def test_a_failing_listener_does_not_stop_the_others(board: StatusBoard):
    def failing(message: dict[str, Any]) -> None:
        raise RuntimeError("phone gone")

    board.subscribe(failing)
    _, received = listen(board)

    board.show(Status.CAPTURING)

    assert [message["state"] for message in received] == ["capturing"]


def test_keeps_the_last_counts_when_they_cannot_be_measured(root: Path):
    sizes = iter([FREE])

    def measure(path: Path) -> int:
        try:
            return next(sizes)
        except StopIteration:
            raise PermissionError("no access") from None

    make_capture(root, "20261126-031522-000")
    board = StatusBoard(CaptureStorage(root), measure_free_bytes=measure)
    first, received = listen(board)

    board.saved("20261126-031522-000", sync_warning=False)

    assert first["capture_count"] == 1
    assert first["free_bytes"] == FREE
    assert received[0]["free_bytes"] == FREE


def test_free_bytes_are_measured_on_the_nearest_existing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    measured: list[Path] = []

    def disk_usage(path: Path) -> SimpleNamespace:
        measured.append(path)
        return SimpleNamespace(total=10, used=4, free=6)

    monkeypatch.setattr(shutil, "disk_usage", disk_usage)

    assert free_bytes(tmp_path / "captures" / "not" / "yet") == 6
    assert measured == [tmp_path]


def test_a_save_reported_after_its_capture_was_deleted_stays_deleted(
    root: Path, board: StatusBoard
):
    make_capture(root, "20261126-031522-000")
    _, received = listen(board)

    (root / "20261126-031522-000").rmdir()
    board.deleted("20261126-031522-000")
    board.saved("20261126-031522-000", sync_warning=False)
    board.show(Status.IDLE)

    assert received[-1]["capture_count"] == 0
    assert received[-1]["last_capture"] is None
