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
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pivr180_device.app import (
    EXIT_ERROR,
    EXIT_INTERRUPTED,
    EXIT_OK,
    run,
    stdin_triggers,
)
from pivr180_device.app import main as capture_main
from pivr180_device.atoms3.fake import FakeClock, FakeSerialLink
from pivr180_device.atoms3.pyserial import DEFAULT_PORT
from pivr180_device.button import Status
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
        ["--shutter", "stdin", "--captures-dir", str(tmp_path / "captures")],
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


def test_shows_idle_when_ready_and_capturing_while_shooting(
    pair: CameraPair, left: AutoCamera, storage: CaptureStorage
):
    statuses: list[Status] = []
    shown_before_trigger: list[list[Status]] = []
    shown_while_capturing: list[Status] = []
    capture_frame = left.capture_frame

    def recording_capture_frame() -> FakeFrame:
        shown_while_capturing.append(statuses[-1])
        return capture_frame()

    left.capture_frame = recording_capture_frame

    def triggers() -> Iterator[None]:
        shown_before_trigger.append(list(statuses))
        yield
        yield

    run(pair, storage, triggers(), statuses.append)

    assert shown_before_trigger == [[Status.IDLE]]
    assert statuses == [
        Status.IDLE,
        Status.CAPTURING,
        Status.IDLE,
        Status.CAPTURING,
        Status.IDLE,
    ]
    assert set(shown_while_capturing) == {Status.CAPTURING}
    assert len(captures(storage)) == 2


def test_shows_an_error_after_a_failed_capture_until_the_next_shot(
    pair: CameraPair, left: AutoCamera, storage: CaptureStorage
):
    left.failing_captures = 1
    statuses: list[Status] = []

    run(pair, storage, [None, None], statuses.append)

    assert statuses == [
        Status.IDLE,
        Status.CAPTURING,
        Status.ERROR,
        Status.CAPTURING,
        Status.IDLE,
    ]
    assert len(captures(storage)) == 1


def test_shows_nothing_when_the_cameras_fail_to_sync_before_ready(
    pair: CameraPair, right: AutoCamera, storage: CaptureStorage
):
    right.metadata_error = TimeoutError("cameras did not synchronise")
    statuses: list[Status] = []

    with pytest.raises(TimeoutError):
        run(pair, storage, [None], statuses.append)

    assert statuses == []


def test_shows_an_error_as_soon_as_the_preview_sync_dies(
    pair: CameraPair, left: AutoCamera, storage: CaptureStorage
):
    statuses: list[Status] = []
    shown_before_trigger: list[Status] = []

    def triggers() -> Iterator[None]:
        left.broken.set()
        assert wait_for(lambda: not preview_threads())
        shown_before_trigger.append(statuses[-1])
        yield

    with pytest.raises(RuntimeError, match="exposure preview stopped on error"):
        run(pair, storage, triggers(), statuses.append)

    assert shown_before_trigger == [Status.ERROR]
    assert statuses == [Status.IDLE, Status.ERROR]


def test_keeps_the_error_when_the_preview_sync_dies_before_ready_shows_idle(
    pair: CameraPair,
    left: AutoCamera,
    storage: CaptureStorage,
    caplog: pytest.LogCaptureFixture,
):
    statuses: list[Status] = []
    shown_before_trigger: list[Status] = []

    class BreakPreviewOnReady(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.getMessage() == "ready to shoot":
                left.broken.set()
                assert wait_for(lambda: not preview_threads())

    def triggers() -> Iterator[None]:
        shown_before_trigger.append(statuses[-1])
        yield

    app_logger = logging.getLogger("pivr180_device.app")
    handler = BreakPreviewOnReady()
    app_logger.addHandler(handler)
    try:
        with (
            caplog.at_level(logging.INFO, logger="pivr180_device.app"),
            pytest.raises(RuntimeError, match="exposure preview stopped on error"),
        ):
            run(pair, storage, triggers(), statuses.append)
    finally:
        app_logger.removeHandler(handler)

    assert shown_before_trigger == [Status.ERROR]
    assert statuses == [Status.ERROR, Status.IDLE, Status.ERROR]


def test_keeps_the_error_when_the_preview_sync_dies_after_a_shot(
    pair: CameraPair, left: AutoCamera, storage: CaptureStorage
):
    statuses: list[Status] = []
    capture_frame = left.capture_frame
    shown_after_shot: list[Status] = []

    def breaking_capture_frame() -> FakeFrame:
        frame = capture_frame()
        left.broken.set()
        return frame

    left.capture_frame = breaking_capture_frame

    def triggers() -> Iterator[None]:
        yield
        assert wait_for(lambda: not preview_threads())
        shown_after_shot.append(statuses[-1])
        yield

    with pytest.raises(RuntimeError, match="exposure preview stopped on error"):
        run(pair, storage, triggers(), statuses.append)

    assert shown_after_shot == [Status.ERROR]
    assert len(captures(storage)) == 1


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


class ServeWebRecorder:
    def __init__(self, *observed: Callable[[], object]) -> None:
        self._observed = observed
        self.served: list[tuple[FastAPI, str, int]] = []
        self.stopped_while: list[tuple[object, ...]] = []
        self.error: Exception | None = None

    @contextmanager
    def __call__(self, app: FastAPI, host: str, port: int) -> Iterator[None]:
        self.served.append((app, host, port))
        if self.error is not None:
            raise self.error
        try:
            yield
        finally:
            self.stopped_while.append(tuple(observe() for observe in self._observed))


def main(argv: list[str] | None = None, **kwargs: Any) -> int:
    # Not the real server: binding port 80 needs privileges the tests lack.
    kwargs.setdefault("serve_web", ServeWebRecorder())
    return capture_main(argv, **kwargs)


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
        [
            "--shutter",
            "stdin",
            "--left",
            "1",
            "--right",
            "0",
            "--captures-dir",
            str(root),
        ],
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

    rig = ButtonRig()

    assert main([], open_pair=open_pair, open_link=rig.open_link) == EXIT_ERROR
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
            ["--shutter", "stdin", "--captures-dir", str(tmp_path)],
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
        ["--shutter", "stdin", "--captures-dir", str(root)],
        open_pair=open_pair,
        stdin=InterruptingStdin(),
    )

    assert code == EXIT_INTERRUPTED
    assert len(list(root.iterdir())) == 1
    assert open_pair.closed
    assert not left.started
    assert not right.started
    assert preview_threads() == []


class ButtonRig:
    def __init__(self, *script: tuple[float, str | OSError]) -> None:
        self.clock = FakeClock()
        self.link = FakeSerialLink(self.clock, script)
        self.opened_ports: list[str] = []

    def open_link(self, port: str) -> FakeSerialLink:
        self.opened_ports.append(port)
        return self.link


class ShutdownRecorder:
    def __init__(self, *observed: Callable[[], object]) -> None:
        self._observed = observed
        self.calls: list[tuple[object, ...]] = []
        self.error: Exception | None = None

    def __call__(self) -> None:
        self.calls.append(tuple(observe() for observe in self._observed))
        if self.error is not None:
            raise self.error


def button_main(
    argv: list[str],
    open_pair: OpenPairRecorder,
    rig: ButtonRig,
    shutdown: ShutdownRecorder,
) -> int:
    return main(
        argv,
        open_pair=open_pair,
        open_link=rig.open_link,
        shutdown=shutdown,
        clock=rig.clock,
        sleep=rig.clock.sleep,
    )


def test_main_shoots_on_each_button_press_and_powers_off_on_a_3_s_hold(
    pair: CameraPair,
    left: AutoCamera,
    right: AutoCamera,
    tmp_path: Path,
    meta_validator,
):
    open_pair = OpenPairRecorder(pair)
    root = tmp_path / "captures"
    rig = ButtonRig(
        (0.0, "press"),
        (0.5, "release"),
        (1.0, "press\r"),
        (1.5, "release\r"),
        (2.0, "press"),
        (60.0, "release"),
    )
    shutdown = ShutdownRecorder(
        lambda: open_pair.closed,
        lambda: rig.link.closed,
        lambda: left.started or right.started,
        lambda: preview_threads(),
        lambda: len(list(root.iterdir())),
    )

    code = button_main(["--captures-dir", str(root)], open_pair, rig, shutdown)

    assert code == EXIT_OK
    assert rig.opened_ports == [DEFAULT_PORT]
    assert shutdown.calls == [(True, True, False, [], 2)]
    assert rig.clock.now == 5.0
    assert rig.link.written[0] == (0.0, "idle")
    assert all(at < 5.0 for at, _ in rig.link.written)
    for directory in sorted(root.iterdir()):
        meta_validator.validate(
            json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        )


def test_main_powers_off_on_a_hold_made_while_a_capture_blocks(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, tmp_path: Path
):
    open_pair = OpenPairRecorder(pair)
    root = tmp_path / "captures"
    rig = ButtonRig(
        (0.0, "press"),
        (0.5, "release"),
        (1.0, "press"),
        (4.5, "release"),
    )
    capture_frame = left.capture_frame
    hold_seen: list[bool] = []

    def slow_capture_frame() -> FakeFrame:
        if not hold_seen:
            hold_seen.append(wait_for(lambda: rig.clock.now >= 4.0))
        return capture_frame()

    left.capture_frame = slow_capture_frame
    shutdown = ShutdownRecorder(
        lambda: open_pair.closed,
        lambda: rig.link.closed,
        lambda: left.started or right.started,
        lambda: len(list(root.iterdir())),
    )

    code = button_main(["--captures-dir", str(root)], open_pair, rig, shutdown)

    assert code == EXIT_OK
    assert hold_seen == [True]
    assert shutdown.calls == [(True, True, False, 1)]


def test_main_powers_off_when_a_capture_fails_after_a_hold_made_during_it(
    pair: CameraPair,
    left: AutoCamera,
    right: AutoCamera,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    open_pair = OpenPairRecorder(pair)
    root = tmp_path / "captures"
    rig = ButtonRig(
        (0.0, "press"),
        (0.5, "release"),
        (1.0, "press"),
        (4.5, "release"),
    )
    capture_frame = left.capture_frame

    def capture_frame_then_reject_resume() -> FakeFrame:
        if right.rejected_controls is None:
            assert wait_for(lambda: rig.clock.now >= 4.0)
            right.rejected_controls = Controls(AeEnable=False, AwbEnable=False)
        return capture_frame()

    left.capture_frame = capture_frame_then_reject_resume
    shutdown = ShutdownRecorder(
        lambda: open_pair.closed,
        lambda: rig.link.closed,
        lambda: left.started or right.started,
        lambda: preview_threads(),
    )

    with caplog.at_level(logging.ERROR, logger="pivr180_device.app"):
        code = button_main(["--captures-dir", str(root)], open_pair, rig, shutdown)

    assert code == EXIT_ERROR
    assert shutdown.calls == [(True, True, False, [])]
    [failure] = caplog.records
    assert "stopped on error" in failure.getMessage()
    assert "camera right rejected" in str(failure.exc_info[1])


def test_main_opens_the_given_button_port(pair: CameraPair, tmp_path: Path):
    rig = ButtonRig((0.0, "press"), (9.0, "release"))
    shutdown = ShutdownRecorder()

    code = button_main(
        [
            "--captures-dir",
            str(tmp_path / "captures"),
            "--button-port",
            "/dev/serial/by-id/usb-Espressif_x-if00",
        ],
        OpenPairRecorder(pair),
        rig,
        shutdown,
    )

    assert code == EXIT_OK
    assert rig.opened_ports == ["/dev/serial/by-id/usb-Espressif_x-if00"]
    assert len(shutdown.calls) == 1


def test_main_reports_a_failed_power_off(
    pair: CameraPair, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    rig = ButtonRig((0.0, "press"), (9.0, "release"))
    shutdown = ShutdownRecorder()
    shutdown.error = RuntimeError("Interactive authentication required.")

    with caplog.at_level(logging.ERROR, logger="pivr180_device.app"):
        code = button_main(
            ["--captures-dir", str(tmp_path / "captures")],
            OpenPairRecorder(pair),
            rig,
            shutdown,
        )

    assert code == EXIT_ERROR
    assert len(shutdown.calls) == 1
    [failure] = caplog.records
    assert "failed to power off" in failure.getMessage()
    assert failure.exc_info is not None


def test_main_still_powers_off_when_releasing_the_cameras_fails(
    pair: CameraPair, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    class FailingClosePair(OpenPairRecorder):
        @contextmanager
        def __call__(self, left_index: int, right_index: int) -> Iterator[CameraPair]:
            yield self.pair
            raise RuntimeError("camera close failed")

    rig = ButtonRig((0.0, "press"), (9.0, "release"))
    shutdown = ShutdownRecorder(lambda: rig.link.closed)

    with caplog.at_level(logging.ERROR, logger="pivr180_device.app"):
        code = button_main(
            ["--captures-dir", str(tmp_path / "captures")],
            FailingClosePair(pair),
            rig,
            shutdown,
        )

    assert code == EXIT_ERROR
    assert shutdown.calls == [(True,)]
    assert any("stopped on error" in r.getMessage() for r in caplog.records)


def test_main_does_not_power_off_when_the_cameras_fail_to_start(
    pair: CameraPair, left: AutoCamera, tmp_path: Path
):
    rig = ButtonRig((0.0, "press"), (9.0, "release"))
    shutdown = ShutdownRecorder()
    left.metadata_error = TimeoutError("cameras did not synchronise")

    code = button_main(
        ["--captures-dir", str(tmp_path / "captures")],
        OpenPairRecorder(pair),
        rig,
        shutdown,
    )

    assert code == EXIT_ERROR
    assert shutdown.calls == []
    assert rig.link.written == [(0.0, "error")]
    assert rig.link.closed


def test_main_shows_an_error_when_the_cameras_cannot_be_opened(tmp_path: Path):
    @contextmanager
    def open_pair(left_index: int, right_index: int) -> Iterator[CameraPair]:
        raise RuntimeError("camera index 1 not found; 1 camera(s) attached")
        yield

    rig = ButtonRig((0.0, "press"), (9.0, "release"))
    shutdown = ShutdownRecorder()

    code = main(
        ["--captures-dir", str(tmp_path / "captures")],
        open_pair=open_pair,
        open_link=rig.open_link,
        shutdown=shutdown,
        clock=rig.clock,
        sleep=rig.clock.sleep,
    )

    assert code == EXIT_ERROR
    assert rig.opened_ports == [DEFAULT_PORT]
    assert rig.link.written == [(0.0, "error")]
    assert rig.link.closed
    assert shutdown.calls == []


def test_main_shows_nothing_when_interrupted_before_ready(tmp_path: Path):
    @contextmanager
    def open_pair(left_index: int, right_index: int) -> Iterator[CameraPair]:
        raise KeyboardInterrupt
        yield

    rig = ButtonRig()

    code = main(
        ["--captures-dir", str(tmp_path / "captures")],
        open_pair=open_pair,
        open_link=rig.open_link,
        shutdown=ShutdownRecorder(),
    )

    assert code == EXIT_INTERRUPTED
    assert rig.opened_ports == []


def test_main_shows_an_error_before_releasing_the_button_link_on_a_fatal_error(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, tmp_path: Path
):
    rig = ButtonRig(
        (0.0, "press"),
        (0.5, "release"),
        (1.0, lambda: wait_for(lambda: not left.started)),
        (1e12, "hello"),
    )
    capture_frame = left.capture_frame

    def capture_frame_then_reject_resume() -> FakeFrame:
        right.rejected_controls = Controls(AeEnable=False, AwbEnable=False)
        return capture_frame()

    left.capture_frame = capture_frame_then_reject_resume
    shutdown = ShutdownRecorder()

    code = button_main(
        ["--captures-dir", str(tmp_path / "captures")],
        OpenPairRecorder(pair),
        rig,
        shutdown,
    )

    assert code == EXIT_ERROR
    statuses = [status for _, status in rig.link.written]
    changes = [s for i, s in enumerate(statuses) if i == 0 or s != statuses[i - 1]]
    assert changes[0] == "idle"
    assert changes[-1] == "error"
    assert changes in (["idle", "error"], ["idle", "capturing", "error"])
    assert rig.link.closed
    assert shutdown.calls == []


def test_main_with_stdin_shutter_never_opens_the_button_or_powers_off(
    pair: CameraPair, tmp_path: Path
):
    rig = ButtonRig()
    shutdown = ShutdownRecorder()

    code = main(
        ["--shutter", "stdin", "--captures-dir", str(tmp_path / "captures")],
        open_pair=OpenPairRecorder(pair),
        stdin=io.StringIO("\nq\n"),
        open_link=rig.open_link,
        shutdown=shutdown,
    )

    assert code == EXIT_OK
    assert rig.opened_ports == []
    assert shutdown.calls == []


def test_main_serves_the_web_ui_on_port_80_of_every_interface(
    pair: CameraPair, tmp_path: Path
):
    serve_web = ServeWebRecorder()

    code = main(
        ["--shutter", "stdin", "--captures-dir", str(tmp_path / "captures")],
        open_pair=OpenPairRecorder(pair),
        stdin=io.StringIO("q\n"),
        serve_web=serve_web,
    )

    assert code == EXIT_OK
    [(app, host, port)] = serve_web.served
    assert (host, port) == ("0.0.0.0", 80)
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert '<main id="app">' in response.text


def test_main_serves_the_web_ui_on_the_given_port(pair: CameraPair, tmp_path: Path):
    serve_web = ServeWebRecorder()

    main(
        [
            "--shutter",
            "stdin",
            "--captures-dir",
            str(tmp_path / "captures"),
            "--web-port",
            "8080",
        ],
        open_pair=OpenPairRecorder(pair),
        stdin=io.StringIO("q\n"),
        serve_web=serve_web,
    )

    [(_, _, port)] = serve_web.served
    assert port == 8080


def test_main_stops_the_web_ui_after_the_cameras_and_button_before_power_off(
    pair: CameraPair, tmp_path: Path
):
    open_pair = OpenPairRecorder(pair)
    rig = ButtonRig((0.0, "press"), (60.0, "release"))
    shutdown = ShutdownRecorder(lambda: list(serve_web.stopped_while))
    serve_web = ServeWebRecorder(lambda: open_pair.closed, lambda: rig.link.closed)

    code = main(
        ["--captures-dir", str(tmp_path / "captures")],
        open_pair=open_pair,
        open_link=rig.open_link,
        shutdown=shutdown,
        clock=rig.clock,
        sleep=rig.clock.sleep,
        serve_web=serve_web,
    )

    assert code == EXIT_OK
    assert serve_web.stopped_while == [(True, True)]
    assert shutdown.calls == [([(True, True)],)]


def test_main_stops_the_web_ui_on_ctrl_c(pair: CameraPair, tmp_path: Path):
    serve_web = ServeWebRecorder()

    code = main(
        ["--shutter", "stdin", "--captures-dir", str(tmp_path / "captures")],
        open_pair=OpenPairRecorder(pair),
        stdin=InterruptingStdin(),
        serve_web=serve_web,
    )

    assert code == EXIT_INTERRUPTED
    assert len(serve_web.stopped_while) == 1


def test_main_keeps_shooting_when_the_web_ui_cannot_start(
    pair: CameraPair, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    serve_web = ServeWebRecorder()
    serve_web.error = RuntimeError("web server failed to listen on 0.0.0.0:80")
    root = tmp_path / "captures"

    with caplog.at_level(logging.ERROR, logger="pivr180_device.app"):
        code = main(
            ["--shutter", "stdin", "--captures-dir", str(root)],
            open_pair=OpenPairRecorder(pair),
            stdin=io.StringIO("\nq\n"),
            serve_web=serve_web,
        )

    assert code == EXIT_OK
    assert len(list(root.iterdir())) == 1
    [failure] = caplog.records
    assert "web UI is unavailable" in failure.getMessage()
    assert "0.0.0.0:80" in str(failure.exc_info[1])


def test_capture_command_is_installed_as_a_console_script():
    [script] = entry_points(group="console_scripts", name="pivr180-capture")

    assert script.value == "pivr180_device.app:main"


def saved(root: Path) -> list[Path]:
    return sorted(root.iterdir()) if root.exists() else []


class WebShutdown:
    def __init__(self, serve_web: ServeWebRecorder) -> None:
        self._serve_web = serve_web
        self.responses: list[int] = []

    def __call__(self) -> None:
        [(app, _, _)] = self._serve_web.served
        self.responses.append(TestClient(app).post("/api/shutdown").status_code)


class WaitingStdin(io.StringIO):
    def __init__(self, on_wait: Callable[[], None]) -> None:
        super().__init__()
        self._on_wait = on_wait
        self.release = threading.Event()

    def __iter__(self) -> Iterator[str]:
        yield "\n"
        self._on_wait()
        # Not waiting forever: without a way out, a broken request would hang the
        # test instead of failing it.
        self.release.wait(timeout=5.0)


def test_main_powers_off_on_a_web_request_after_releasing_cameras_and_button(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, tmp_path: Path
):
    open_pair = OpenPairRecorder(pair)
    root = tmp_path / "captures"
    serve_web = ServeWebRecorder()
    web_shutdown = WebShutdown(serve_web)
    rig = ButtonRig(
        (0.0, "press"),
        (0.5, "release"),
        (1.0, lambda: wait_for(lambda: len(saved(root)) == 1)),
        (1.5, web_shutdown),
        (60.0, "hello"),
    )
    shutdown = ShutdownRecorder(
        lambda: open_pair.closed,
        lambda: rig.link.closed,
        lambda: left.started or right.started,
        lambda: preview_threads(),
        lambda: len(saved(root)),
    )

    code = main(
        ["--captures-dir", str(root)],
        open_pair=open_pair,
        open_link=rig.open_link,
        shutdown=shutdown,
        clock=rig.clock,
        sleep=rig.clock.sleep,
        serve_web=serve_web,
    )

    assert code == EXIT_OK
    assert web_shutdown.responses == [202]
    assert shutdown.calls == [(True, True, False, [], 1)]


def test_main_saves_the_capture_under_way_then_powers_off_on_a_web_request(
    pair: CameraPair, left: AutoCamera, tmp_path: Path
):
    open_pair = OpenPairRecorder(pair)
    root = tmp_path / "captures"
    serve_web = ServeWebRecorder()
    web_shutdown = WebShutdown(serve_web)
    rig = ButtonRig(
        (0.0, "press"),
        (0.5, "release"),
        (1.0, "press"),
        (1.5, "release"),
        (60.0, "hello"),
    )
    capture_frame = left.capture_frame

    def capture_frame_requesting_shutdown() -> FakeFrame:
        if not web_shutdown.responses:
            assert wait_for(lambda: rig.clock.now >= 1.5)
            web_shutdown()
        return capture_frame()

    left.capture_frame = capture_frame_requesting_shutdown
    shutdown = ShutdownRecorder(
        lambda: open_pair.closed,
        lambda: rig.link.closed,
        lambda: len(saved(root)),
    )

    code = main(
        ["--captures-dir", str(root)],
        open_pair=open_pair,
        open_link=rig.open_link,
        shutdown=shutdown,
        clock=rig.clock,
        sleep=rig.clock.sleep,
        serve_web=serve_web,
    )

    assert code == EXIT_OK
    assert web_shutdown.responses == [202]
    assert shutdown.calls == [(True, True, 1)]


def test_main_with_stdin_shutter_powers_off_on_a_web_request_while_stdin_waits(
    pair: CameraPair, tmp_path: Path
):
    open_pair = OpenPairRecorder(pair)
    root = tmp_path / "captures"
    serve_web = ServeWebRecorder()
    web_shutdown = WebShutdown(serve_web)
    stdin = WaitingStdin(web_shutdown)
    shutdown = ShutdownRecorder(lambda: open_pair.closed, lambda: len(saved(root)))

    try:
        code = main(
            ["--shutter", "stdin", "--captures-dir", str(root)],
            open_pair=open_pair,
            stdin=stdin,
            shutdown=shutdown,
            serve_web=serve_web,
        )
    finally:
        stdin.release.set()

    assert code == EXIT_OK
    assert web_shutdown.responses == [202]
    assert shutdown.calls == [(True, 1)]


def test_main_powers_off_on_a_web_request_even_when_the_capture_fails(
    pair: CameraPair, left: AutoCamera, right: AutoCamera, tmp_path: Path
):
    serve_web = ServeWebRecorder()
    web_shutdown = WebShutdown(serve_web)
    capture_frame = left.capture_frame

    def capture_frame_then_reject_resume() -> FakeFrame:
        web_shutdown()
        right.rejected_controls = Controls(AeEnable=False, AwbEnable=False)
        return capture_frame()

    left.capture_frame = capture_frame_then_reject_resume
    open_pair = OpenPairRecorder(pair)
    stdin = WaitingStdin(lambda: None)
    shutdown = ShutdownRecorder(lambda: open_pair.closed)

    try:
        code = main(
            ["--shutter", "stdin", "--captures-dir", str(tmp_path / "captures")],
            open_pair=open_pair,
            stdin=stdin,
            shutdown=shutdown,
            serve_web=serve_web,
        )
    finally:
        stdin.release.set()

    assert code == EXIT_ERROR
    assert shutdown.calls == [(True,)]
