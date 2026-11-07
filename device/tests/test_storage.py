from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from pivr180_device.camera import FrameMetadata
from pivr180_device.camera.fake import FakeFrame
from pivr180_device.storage import (
    DEFAULT_CAPTURE_ROOT,
    JPEG_QUALITY,
    STILL_SIZE,
    CaptureSaveError,
    CaptureStorage,
)

CAPTURE_TIME = datetime(2026, 11, 7, 12, 34, 56, 789_000, tzinfo=UTC)


def make_frame(
    image: bytes = b"jpeg", size: tuple[int, int] = (4056, 3040)
) -> FakeFrame:
    return FakeFrame(
        FrameMetadata(
            sensor_timestamp_ns=0,
            exposure_time_us=10_000,
            analogue_gain=1.0,
            colour_gains=(2.0, 1.5),
        ),
        image=image,
        size=size,
    )


class FailingFrame:
    def __init__(self, partial: bytes = b"") -> None:
        self._partial = partial

    @property
    def metadata(self) -> FrameMetadata:
        return make_frame().metadata

    @property
    def size(self) -> tuple[int, int]:
        return STILL_SIZE

    def save(self, path: Path, quality: int) -> None:
        if self._partial:
            path.write_bytes(self._partial)
        raise OSError("disk full")


def fixed_clock(moment: datetime = CAPTURE_TIME):
    return lambda: moment


def test_capture_settings_follow_spec():
    assert STILL_SIZE == (4056, 3040)
    assert JPEG_QUALITY == 100
    assert DEFAULT_CAPTURE_ROOT == Path("/data/captures")
    assert CaptureStorage().root == DEFAULT_CAPTURE_ROOT


def test_save_pair_writes_left_and_right_jpeg_into_capture_directory(tmp_path):
    left = make_frame(b"left-image")
    right = make_frame(b"right-image")
    storage = CaptureStorage(root=tmp_path, clock=fixed_clock())

    directory = storage.save_pair(left, right)

    assert directory == tmp_path / "20261107-123456-000"
    assert sorted(p.name for p in directory.iterdir()) == ["left.jpg", "right.jpg"]
    assert (directory / "left.jpg").read_bytes() == b"left-image"
    assert (directory / "right.jpg").read_bytes() == b"right-image"


def test_save_pair_saves_with_quality_100(tmp_path):
    left = make_frame()
    right = make_frame()
    storage = CaptureStorage(root=tmp_path, clock=fixed_clock())

    directory = storage.save_pair(left, right)

    assert left.saves == [(directory / "left.jpg", 100)]
    assert right.saves == [(directory / "right.jpg", 100)]


def test_captures_in_the_same_second_get_distinct_directories(tmp_path):
    storage = CaptureStorage(root=tmp_path, clock=fixed_clock())

    directories = [storage.save_pair(make_frame(), make_frame()) for _ in range(3)]

    assert [d.name for d in directories] == [
        "20261107-123456-000",
        "20261107-123456-001",
        "20261107-123456-002",
    ]


def test_sequence_skips_directories_left_by_previous_runs(tmp_path):
    (tmp_path / "20261107-123456-000").mkdir()
    (tmp_path / "20261107-123456-001").mkdir()
    storage = CaptureStorage(root=tmp_path, clock=fixed_clock())

    directory = storage.save_pair(make_frame(), make_frame())

    assert directory.name == "20261107-123456-002"


def test_sequence_restarts_in_the_next_second(tmp_path):
    moments = iter([CAPTURE_TIME, CAPTURE_TIME + timedelta(seconds=1)])
    storage = CaptureStorage(root=tmp_path, clock=lambda: next(moments))

    first = storage.save_pair(make_frame(), make_frame())
    second = storage.save_pair(make_frame(), make_frame())

    assert first.name == "20261107-123456-000"
    assert second.name == "20261107-123457-000"


def test_raises_when_a_second_already_has_1000_captures(tmp_path):
    for sequence in range(1000):
        (tmp_path / f"20261107-123456-{sequence:03d}").mkdir()
    storage = CaptureStorage(root=tmp_path, clock=fixed_clock())

    with pytest.raises(CaptureSaveError):
        storage.save_pair(make_frame(), make_frame())


def test_directory_name_uses_utc_regardless_of_clock_timezone(tmp_path):
    jst = timezone(timedelta(hours=9))
    moment = datetime(2026, 11, 8, 0, 30, 0, tzinfo=jst)
    storage = CaptureStorage(root=tmp_path, clock=fixed_clock(moment))

    directory = storage.save_pair(make_frame(), make_frame())

    assert directory.name == "20261107-153000-000"


def test_rejects_naive_clock(tmp_path):
    storage = CaptureStorage(root=tmp_path, clock=lambda: datetime(2026, 11, 7))

    with pytest.raises(ValueError):
        storage.save_pair(make_frame(), make_frame())

    assert list(tmp_path.iterdir()) == []


def test_creates_missing_root_directory(tmp_path):
    root = tmp_path / "captures"
    storage = CaptureStorage(root=root, clock=fixed_clock())

    directory = storage.save_pair(make_frame(), make_frame())

    assert directory.parent == root


def test_raises_when_root_parent_is_missing(tmp_path):
    storage = CaptureStorage(
        root=tmp_path / "missing" / "captures", clock=fixed_clock()
    )

    with pytest.raises(CaptureSaveError, match="capture root"):
        storage.save_pair(make_frame(), make_frame())


def test_failed_right_save_removes_incomplete_capture(tmp_path):
    storage = CaptureStorage(root=tmp_path, clock=fixed_clock())

    with pytest.raises(CaptureSaveError, match="right.jpg") as excinfo:
        storage.save_pair(make_frame(), FailingFrame(partial=b"half"))

    assert isinstance(excinfo.value.__cause__, OSError)
    assert list(tmp_path.iterdir()) == []


def test_failed_left_save_skips_right_and_removes_capture(tmp_path):
    right = make_frame()
    storage = CaptureStorage(root=tmp_path, clock=fixed_clock())

    with pytest.raises(CaptureSaveError, match="left.jpg"):
        storage.save_pair(FailingFrame(), right)

    assert right.saves == []
    assert list(tmp_path.iterdir()) == []


def test_failed_capture_frees_its_directory_name(tmp_path):
    storage = CaptureStorage(root=tmp_path, clock=fixed_clock())
    with pytest.raises(CaptureSaveError):
        storage.save_pair(make_frame(), FailingFrame())

    directory = storage.save_pair(make_frame(), make_frame())

    assert directory.name == "20261107-123456-000"


def test_new_capture_keeps_extra_files_written_in_the_block(tmp_path):
    storage = CaptureStorage(root=tmp_path, clock=fixed_clock())

    with storage.new_capture() as directory:
        (directory / "meta.json").write_text("{}")

    assert (directory / "meta.json").read_text() == "{}"


def test_new_capture_removes_directory_when_block_raises(tmp_path):
    storage = CaptureStorage(root=tmp_path, clock=fixed_clock())

    with pytest.raises(RuntimeError), storage.new_capture() as directory:
        (directory / "left.jpg").write_bytes(b"left")
        raise RuntimeError("meta failed")

    assert list(tmp_path.iterdir()) == []


def test_new_capture_notes_cleanup_failure_on_original_error(tmp_path, monkeypatch):
    storage = CaptureStorage(root=tmp_path, clock=fixed_clock())

    def fail_rmtree(path):
        raise PermissionError("read-only")

    monkeypatch.setattr("pivr180_device.storage.shutil.rmtree", fail_rmtree)

    with pytest.raises(RuntimeError) as excinfo, storage.new_capture():
        raise RuntimeError("meta failed")

    assert any(
        "failed to remove incomplete capture" in n for n in excinfo.value.__notes__
    )


@pytest.mark.parametrize("side", ["left", "right"])
def test_rejects_frame_with_unexpected_resolution(tmp_path, side):
    frames = {"left": make_frame(), "right": make_frame()}
    frames[side] = make_frame(size=(1920, 1080))
    storage = CaptureStorage(root=tmp_path, clock=fixed_clock())

    with pytest.raises(CaptureSaveError, match=f"{side} frame is 1920x1080"):
        storage.save_pair(frames["left"], frames["right"])

    assert frames["left"].saves == []
    assert frames["right"].saves == []
    assert list(tmp_path.iterdir()) == []
