import io
import itertools
import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import entry_points
from pathlib import Path

import pytest

from pivr180_device.app import (
    EXIT_ERROR,
    EXIT_INTERRUPTED,
    EXIT_OK,
    main,
    run,
    stdin_triggers,
)
from pivr180_device.camera import CameraPair, Controls, FrameMetadata
from pivr180_device.camera.fake import FakeCamera, FakeFrame
from pivr180_device.storage import CaptureStorage

AUTO = FrameMetadata(
    sensor_timestamp_ns=0,
    exposure_time_us=20_000,
    analogue_gain=2.0,
    colour_gains=(1.8, 1.4),
)
LOCKED = {
    "AeEnable": False,
    "AwbEnable": False,
    "ExposureTime": 20_000,
    "AnalogueGain": 2.0,
    "ColourGains": (1.8, 1.4),
}
FRAME_INTERVAL_NS = 1_000
CAPTURE_TIME = datetime(2026, 11, 7, 12, 34, 56, tzinfo=UTC)


class CameraBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clock = itertools.count(1)
        self.overlaps: list[str] = []

    @contextmanager
    def use(self, name: str) -> Iterator[None]:
        if not self._lock.acquire(blocking=False):
            self.overlaps.append(name)
            time.sleep(0.001)
            yield
            return
        try:
            time.sleep(0.001)
            yield
        finally:
            self._lock.release()

    def next_timestamp_ns(self) -> int:
        return next(self._clock) * FRAME_INTERVAL_NS


class AutoCamera(FakeCamera):
    def __init__(self, camera_id: str, bus: CameraBus) -> None:
        super().__init__(camera_id)
        self.bus = bus
        self.auto = AUTO
        self.failing_captures = 0
        self.broken = threading.Event()
        self.metadata_error: Exception | None = None
        self.captured_with: list[Controls] = []
        self.rejected_controls: Controls | None = None

    def set_controls(self, controls: Controls) -> None:
        with self.bus.use(f"{self.camera_id}.set_controls"):
            if controls == self.rejected_controls:
                raise RuntimeError(f"camera {self.camera_id} rejected {controls}")
            super().set_controls(controls)

    def capture_metadata(self) -> FrameMetadata:
        with self.bus.use(f"{self.camera_id}.capture_metadata"):
            if self.metadata_error is not None:
                raise self.metadata_error
            if self.broken.is_set():
                raise RuntimeError(f"camera {self.camera_id} disconnected")
            return self._metadata()

    def capture_frame(self) -> FakeFrame:
        with self.bus.use(f"{self.camera_id}.capture_frame"):
            if self.failing_captures:
                self.failing_captures -= 1
                raise RuntimeError(f"camera {self.camera_id} dropped a frame")
            frame = FakeFrame(self._metadata(), image=f"{self.camera_id}-jpeg".encode())
            self.captured_with.append(self.controls)
            return frame

    def _metadata(self) -> FrameMetadata:
        if not self.started:
            raise RuntimeError(f"camera {self.camera_id} is not started")
        controls = self.controls
        auto_exposure = controls.get("AeEnable", True)
        auto_wb = controls.get("AwbEnable", True)
        return FrameMetadata(
            sensor_timestamp_ns=self.bus.next_timestamp_ns(),
            exposure_time_us=self.auto.exposure_time_us
            if auto_exposure
            else controls["ExposureTime"],
            analogue_gain=self.auto.analogue_gain
            if auto_exposure
            else controls["AnalogueGain"],
            colour_gains=self.auto.colour_gains if auto_wb else controls["ColourGains"],
        )


@pytest.fixture
def bus() -> CameraBus:
    return CameraBus()


@pytest.fixture
def left(bus: CameraBus) -> AutoCamera:
    return AutoCamera("left", bus)


@pytest.fixture
def right(bus: CameraBus) -> AutoCamera:
    right = AutoCamera("right", bus)
    # Not AUTO: right must end up with left's values only by copying them.
    right.auto = replace(
        AUTO, exposure_time_us=5_000, analogue_gain=8.0, colour_gains=(1.0, 3.0)
    )
    return right


@pytest.fixture
def pair(left: AutoCamera, right: AutoCamera) -> CameraPair:
    return CameraPair(left=left, right=right)


@pytest.fixture
def storage(tmp_path: Path) -> CaptureStorage:
    return CaptureStorage(tmp_path / "captures", clock=lambda: CAPTURE_TIME)


def wait_for(predicate: Callable[[], bool], timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()


def preview_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "exposure-preview" and thread.is_alive()
    ]


def captures(storage: CaptureStorage) -> list[Path]:
    if not storage.root.exists():
        return []
    return sorted(storage.root.iterdir())


def right_has_copied(right: AutoCamera, metadata: FrameMetadata) -> bool:
    controls = right.controls
    return (
        controls.get("ExposureTime") == metadata.exposure_time_us
        and controls.get("AnalogueGain") == metadata.analogue_gain
        and controls.get("ColourGains") == metadata.colour_gains
    )


def test_preview_keeps_copying_left_exposure_and_wb_to_right(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, storage: CaptureStorage
):
    copied: list[bool] = []

    def triggers() -> Iterator[None]:
        copied.append(wait_for(lambda: right_has_copied(right, AUTO)))
        left.auto = replace(
            AUTO, exposure_time_us=40_000, analogue_gain=4.0, colour_gains=(2.2, 1.1)
        )
        copied.append(wait_for(lambda: right_has_copied(right, left.auto)))
        yield from ()

    run(pair, storage, triggers())

    assert copied == [True, True]
    assert right.controls["AeEnable"] is False
    assert right.controls["AwbEnable"] is False
    assert left.controls["AeEnable"] is True
    assert captures(storage) == []


def test_trigger_saves_a_pair_shot_with_exposure_locked_on_both_cameras(
    pair: CameraPair,
    left: AutoCamera,
    right: AutoCamera,
    storage: CaptureStorage,
    meta_validator,
):
    run(pair, storage, [None])

    [directory] = captures(storage)
    assert directory.name == "20261107-123456-000"
    assert (directory / "left.jpg").read_bytes() == b"left-jpeg"
    assert (directory / "right.jpg").read_bytes() == b"right-jpeg"
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    meta_validator.validate(meta)
    assert meta["exposure"] == {
        "exposure_time_us": 20_000,
        "analogue_gain": 2.0,
        "colour_gains": [1.8, 1.4],
    }
    assert meta["sync"]["warning"] is False
    assert left.captured_with and right.captured_with
    for controls in left.captured_with + right.captured_with:
        assert {key: controls[key] for key in LOCKED} == LOCKED


def test_returns_to_auto_exposure_preview_after_each_shot(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, storage: CaptureStorage
):
    after_shot: list[bool] = []

    def triggers() -> Iterator[None]:
        yield
        left.auto = replace(AUTO, exposure_time_us=30_000)
        after_shot.append(left.controls["AeEnable"])
        after_shot.append(wait_for(lambda: right_has_copied(right, left.auto)))

    run(pair, storage, triggers())

    assert after_shot == [True, True]


def test_multiple_triggers_save_separate_captures_without_concurrent_camera_access(
    pair: CameraPair, bus: CameraBus, storage: CaptureStorage, meta_validator
):
    run(pair, storage, [None, None, None])

    directories = captures(storage)
    assert [directory.name for directory in directories] == [
        "20261107-123456-000",
        "20261107-123456-001",
        "20261107-123456-002",
    ]
    for directory in directories:
        meta_validator.validate(
            json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        )
    assert bus.overlaps == []


def test_failed_capture_is_reported_and_the_next_trigger_still_shoots(
    pair: CameraPair,
    left: AutoCamera,
    storage: CaptureStorage,
    caplog: pytest.LogCaptureFixture,
):
    left.failing_captures = 1

    with caplog.at_level(logging.INFO, logger="pivr180_device.app"):
        run(pair, storage, [None, None])

    assert len(captures(storage)) == 1
    [failure] = [record for record in caplog.records if record.levelname == "ERROR"]
    assert "capture failed" in failure.getMessage()
    assert failure.exc_info is not None
    assert "dropped a frame" in str(failure.exc_info[1])


def test_failed_capture_resumes_the_preview_before_the_next_trigger(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, storage: CaptureStorage
):
    left.failing_captures = 1
    resumed: list[bool] = []

    def triggers() -> Iterator[None]:
        yield
        left.auto = replace(AUTO, exposure_time_us=30_000)
        resumed.append(left.controls["AeEnable"])
        resumed.append(wait_for(lambda: right_has_copied(right, left.auto)))
        yield

    run(pair, storage, triggers())

    assert resumed == [True, True]
    assert len(captures(storage)) == 1


def test_stops_with_an_error_when_the_preview_cannot_be_resumed_after_a_shot(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, storage: CaptureStorage
):
    shots_after_failure: list[None] = []

    def triggers() -> Iterator[None]:
        right.rejected_controls = Controls(AeEnable=False, AwbEnable=False)
        yield
        shots_after_failure.append(None)
        yield

    with pytest.raises(RuntimeError, match="camera right rejected"):
        run(pair, storage, triggers())

    assert shots_after_failure == []
    assert len(captures(storage)) == 1
    assert not left.started
    assert not right.started
    assert preview_threads() == []


def test_main_exits_with_failure_when_the_preview_cannot_be_resumed(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, tmp_path: Path
):
    open_pair = OpenPairRecorder(pair)

    class RejectingResumeStdin(io.StringIO):
        def __iter__(self) -> Iterator[str]:
            # Not set before main(): ExposurePreview.start() resumes the preview too.
            right.rejected_controls = Controls(AeEnable=False, AwbEnable=False)
            yield "\n"
            yield "\n"

    code = main(
        ["--captures-dir", str(tmp_path / "captures")],
        open_pair=open_pair,
        stdin=RejectingResumeStdin(),
    )

    assert code == EXIT_ERROR
    assert len(list((tmp_path / "captures").iterdir())) == 1
    assert open_pair.closed
    assert not left.started
    assert not right.started
    assert preview_threads() == []


def test_failed_save_is_reported_and_cameras_are_still_released(
    pair: CameraPair,
    left: AutoCamera,
    right: AutoCamera,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    storage = CaptureStorage(tmp_path / "missing" / "captures")

    with caplog.at_level(logging.ERROR, logger="pivr180_device.app"):
        run(pair, storage, [None])

    assert not (tmp_path / "missing").exists()
    assert any("capture failed" in record.getMessage() for record in caplog.records)
    assert not left.started
    assert not right.started


def test_logs_a_warning_when_the_saved_pair_exceeds_the_sync_threshold(
    pair: CameraPair,
    right: AutoCamera,
    storage: CaptureStorage,
    caplog: pytest.LogCaptureFixture,
):
    original = right._metadata

    def late_metadata() -> FrameMetadata:
        metadata = original()
        return replace(
            metadata, sensor_timestamp_ns=metadata.sensor_timestamp_ns + 5_000_000
        )

    right._metadata = late_metadata

    with caplog.at_level(logging.WARNING, logger="pivr180_device.app"):
        run(pair, storage, [None])

    [directory] = captures(storage)
    assert any(
        record.levelname == "WARNING" and "sync warning" in record.getMessage()
        for record in caplog.records
    )
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    assert meta["sync"]["warning"] is True


def test_stops_with_an_error_when_the_preview_sync_dies(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, storage: CaptureStorage
):
    def triggers() -> Iterator[None]:
        left.broken.set()
        assert wait_for(lambda: not preview_threads())
        yield
        yield

    with pytest.raises(RuntimeError, match="exposure preview stopped on error"):
        run(pair, storage, triggers())

    assert captures(storage) == []
    assert not left.started
    assert not right.started


def test_releases_cameras_and_stops_preview_when_triggers_end(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, storage: CaptureStorage
):
    run(pair, storage, [None])

    assert not left.started
    assert not right.started
    assert preview_threads() == []


def test_releases_cameras_and_stops_preview_on_keyboard_interrupt(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, storage: CaptureStorage
):
    def triggers() -> Iterator[None]:
        yield
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(pair, storage, triggers())

    assert len(captures(storage)) == 1
    assert not left.started
    assert not right.started
    assert preview_threads() == []


def test_waits_for_both_cameras_to_sync_before_preview(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, storage: CaptureStorage
):
    right.metadata_error = TimeoutError("cameras did not synchronise")
    triggered: list[None] = []

    def triggers() -> Iterator[None]:
        triggered.append(None)
        yield

    with pytest.raises(TimeoutError, match="did not synchronise"):
        run(pair, storage, triggers())

    assert triggered == []
    assert left.controls_history == []
    assert not left.started
    assert not right.started


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("", 0),
        ("\n", 1),
        ("\n\n\n", 3),
        ("\nq\n\n", 1),
        ("\n QUIT \n\n", 1),
        ("\nshoot\n", 2),
    ],
)
def test_stdin_triggers_shoot_per_line_until_quit_or_eof(text: str, count: int):
    assert len(list(stdin_triggers(io.StringIO(text)))) == count


class OpenPairRecorder:
    def __init__(self, pair: CameraPair) -> None:
        self.pair = pair
        self.opened_with: list[tuple[int, int]] = []
        self.closed = False

    @contextmanager
    def __call__(self, left_index: int, right_index: int) -> Iterator[CameraPair]:
        self.opened_with.append((left_index, right_index))
        try:
            yield self.pair
        finally:
            self.closed = True


def test_main_shoots_on_each_enter_and_quits_on_q(
    pair: CameraPair, tmp_path: Path, meta_validator
):
    open_pair = OpenPairRecorder(pair)
    root = tmp_path / "captures"

    code = main(
        ["--left", "1", "--right", "0", "--captures-dir", str(root)],
        open_pair=open_pair,
        stdin=io.StringIO("\n\nq\n\n"),
    )

    assert code == EXIT_OK
    assert open_pair.opened_with == [(1, 0)]
    assert open_pair.closed
    directories = sorted(root.iterdir())
    assert len(directories) == 2
    for directory in directories:
        assert {path.name for path in directory.iterdir()} == {
            "left.jpg",
            "right.jpg",
            "meta.json",
        }
        meta_validator.validate(
            json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        )


def test_main_defaults_to_cameras_0_and_1():
    opened: list[tuple[int, int]] = []

    @contextmanager
    def open_pair(left_index: int, right_index: int) -> Iterator[CameraPair]:
        opened.append((left_index, right_index))
        raise RuntimeError("camera index 1 not found; 1 camera(s) attached")
        yield

    assert main([], open_pair=open_pair, stdin=io.StringIO("")) == EXIT_ERROR
    assert opened == [(0, 1)]


def test_main_reports_errors_and_exits_with_failure(
    pair: CameraPair,
    left: AutoCamera,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    open_pair = OpenPairRecorder(pair)
    left.metadata_error = TimeoutError("cameras did not synchronise")

    with caplog.at_level(logging.ERROR, logger="pivr180_device.app"):
        code = main(
            ["--captures-dir", str(tmp_path)],
            open_pair=open_pair,
            stdin=io.StringIO("\n"),
        )

    assert code == EXIT_ERROR
    assert open_pair.closed
    [failure] = caplog.records
    assert "stopped on error" in failure.getMessage()
    assert failure.exc_info is not None
    assert "did not synchronise" in str(failure.exc_info[1])


class InterruptingStdin(io.StringIO):
    def __iter__(self) -> Iterator[str]:
        yield "\n"
        raise KeyboardInterrupt


def test_main_releases_cameras_on_ctrl_c(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, tmp_path: Path
):
    open_pair = OpenPairRecorder(pair)
    root = tmp_path / "captures"

    code = main(
        ["--captures-dir", str(root)], open_pair=open_pair, stdin=InterruptingStdin()
    )

    assert code == EXIT_INTERRUPTED
    assert len(list(root.iterdir())) == 1
    assert open_pair.closed
    assert not left.started
    assert not right.started
    assert preview_threads() == []


def test_capture_command_is_installed_as_a_console_script():
    [script] = entry_points(group="console_scripts", name="pivr180-capture")

    assert script.value == "pivr180_device.app:main"
