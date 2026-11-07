import logging
import math
import threading
import time
from collections.abc import Callable

import pytest

from pivr180_device.camera import CameraPair, Controls, FrameMetadata
from pivr180_device.camera.fake import FakeCamera, FakeFrame
from pivr180_device.exposure import (
    ExposureNotAppliedError,
    ExposurePreview,
    ExposureSettings,
    ExposureSync,
)

LOCKED_CONTROLS = {
    "AeEnable": False,
    "AwbEnable": False,
    "ExposureTime": 10_000,
    "AnalogueGain": 1.0,
    "ColourGains": (2.0, 1.5),
}


def make_metadata(
    exposure_time_us: int = 10_000,
    analogue_gain: float = 1.0,
    colour_gains: tuple[float, float] = (2.0, 1.5),
) -> FrameMetadata:
    return FrameMetadata(
        sensor_timestamp_ns=0,
        exposure_time_us=exposure_time_us,
        analogue_gain=analogue_gain,
        colour_gains=colour_gains,
    )


def make_frame(
    exposure_time_us: int = 10_000,
    analogue_gain: float = 1.0,
    colour_gains: tuple[float, float] = (2.0, 1.5),
) -> FakeFrame:
    return FakeFrame(make_metadata(exposure_time_us, analogue_gain, colour_gains))


def make_sync(
    left_frames: list[FakeFrame] | None = None,
    right_frames: list[FakeFrame] | None = None,
    max_wait_frames: int = 30,
    settle_frames: int = 0,
    stable_frames: int = 1,
) -> tuple[ExposureSync, FakeCamera, FakeCamera]:
    left = FakeCamera("left", frames=left_frames or [])
    right = FakeCamera("right", frames=right_frames or [])
    pair = CameraPair(left=left, right=right)
    pair.start()
    sync = ExposureSync(
        pair,
        settle_frames=settle_frames,
        stable_frames=stable_frames,
        max_wait_frames=max_wait_frames,
    )
    return sync, left, right


def wait_for(predicate: Callable[[], bool], timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()


class ControlledCamera(FakeCamera):
    def __init__(self, camera_id: str, auto: FrameMetadata) -> None:
        super().__init__(camera_id)
        self.auto = auto

    def capture_metadata(self) -> FrameMetadata:
        if not self.started:
            raise RuntimeError(f"camera {self.camera_id} is not started")
        time.sleep(0.001)
        controls = self.controls
        auto = self.auto
        return FrameMetadata(
            sensor_timestamp_ns=0,
            exposure_time_us=auto.exposure_time_us
            if controls.get("AeEnable", True)
            else controls["ExposureTime"],
            analogue_gain=auto.analogue_gain
            if controls.get("AeEnable", True)
            else controls["AnalogueGain"],
            colour_gains=auto.colour_gains
            if controls.get("AwbEnable", True)
            else controls["ColourGains"],
        )


def test_resume_preview_enables_auto_on_left_and_disables_it_on_right():
    sync, left, right = make_sync()

    sync.resume_preview()

    assert left.controls == {"AeEnable": True, "AwbEnable": True}
    assert right.controls == {"AeEnable": False, "AwbEnable": False}


def test_sync_once_copies_left_values_to_right_without_touching_left():
    sync, left, right = make_sync(
        [
            make_frame(
                exposure_time_us=33_333, analogue_gain=4.5, colour_gains=(1.8, 2.2)
            )
        ]
    )
    sync.resume_preview()

    settings = sync.sync_once()

    assert settings == ExposureSettings(33_333, 4.5, (1.8, 2.2))
    assert right.controls == {
        "AeEnable": False,
        "AwbEnable": False,
        "ExposureTime": 33_333,
        "AnalogueGain": 4.5,
        "ColourGains": (1.8, 2.2),
    }
    assert left.controls == {"AeEnable": True, "AwbEnable": True}


def test_sync_once_follows_changes_in_left_values():
    sync, _, right = make_sync(
        [
            make_frame(exposure_time_us=10_000, analogue_gain=1.0),
            make_frame(exposure_time_us=20_000, analogue_gain=2.0),
        ]
    )

    sync.sync_once()
    sync.sync_once()

    assert right.controls["ExposureTime"] == 20_000
    assert right.controls["AnalogueGain"] == 2.0


def test_sync_once_propagates_capture_errors_without_setting_right():
    sync, _, right = make_sync()

    with pytest.raises(RuntimeError, match="no scripted frames"):
        sync.sync_once()

    assert right.controls_history == []


@pytest.mark.parametrize(
    ("exposure_time_us", "analogue_gain", "colour_gains"),
    [
        (0, 1.0, (2.0, 1.5)),
        (-1, 1.0, (2.0, 1.5)),
        (10_000, 0.0, (2.0, 1.5)),
        (10_000, math.nan, (2.0, 1.5)),
        (10_000, math.inf, (2.0, 1.5)),
        (10_000, 1.0, (0.0, 1.5)),
        (10_000, 1.0, (2.0, -1.0)),
        (10_000, 1.0, (2.0, math.nan)),
    ],
)
def test_sync_once_rejects_invalid_left_values(
    exposure_time_us: int, analogue_gain: float, colour_gains: tuple[float, float]
):
    sync, _, right = make_sync(
        [make_frame(exposure_time_us, analogue_gain, colour_gains)]
    )

    with pytest.raises(ValueError):
        sync.sync_once()

    assert right.controls_history == []


def test_sync_rejects_non_positive_max_wait_frames():
    pair = CameraPair(left=FakeCamera("left"), right=FakeCamera("right"))

    with pytest.raises(ValueError, match="max_wait_frames"):
        ExposureSync(pair, max_wait_frames=0)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"settle_frames": -1}, "settle_frames"),
        ({"stable_frames": 0}, "stable_frames"),
        ({"stable_frames": 3, "max_wait_frames": 2}, "max_wait_frames"),
    ],
)
def test_sync_rejects_invalid_wait_parameters(kwargs: dict[str, int], match: str):
    pair = CameraPair(left=FakeCamera("left"), right=FakeCamera("right"))

    with pytest.raises(ValueError, match=match):
        ExposureSync(pair, **kwargs)


def test_shoot_ignores_matching_frames_queued_before_the_control_change():
    changed = make_frame(exposure_time_us=12_000)
    marker = make_frame(exposure_time_us=10_000)
    sync, left, right = make_sync(
        [make_frame(), make_frame(), changed, make_frame()],
        [make_frame(), changed, make_frame(), marker],
        settle_frames=2,
    )
    left_remaining: list[bool] = []

    def capture(settings: ExposureSettings) -> FakeFrame:
        try:
            left.capture_metadata()
        except RuntimeError:
            left_remaining.append(False)
        return right.capture_frame()

    assert sync.shoot(capture) is marker
    assert left_remaining == [False]


def test_shoot_requires_consecutive_matching_frames():
    changed = make_frame(exposure_time_us=12_000)
    marker = make_frame()
    sync, _, right = make_sync(
        [make_frame(), make_frame(), changed, make_frame(), make_frame()],
        [make_frame(), changed, make_frame(), make_frame(), marker],
        stable_frames=2,
    )

    assert sync.shoot(lambda settings: right.capture_frame()) is marker


def test_shoot_raises_when_auto_exposure_keeps_changing_the_values():
    changed = make_frame(exposure_time_us=12_000)
    sync, left, _ = make_sync(
        [make_frame(), make_frame(), changed, make_frame(), changed],
        stable_frames=2,
        max_wait_frames=4,
    )
    calls: list[ExposureSettings] = []

    with pytest.raises(ExposureNotAppliedError, match="camera left .* 2 consecutive"):
        sync.shoot(calls.append)

    assert calls == []
    assert left.controls["AeEnable"] is True


def test_shoot_locks_both_cameras_to_left_values_during_capture():
    sync, left, right = make_sync([make_frame(), make_frame()], [make_frame()])
    seen: list[tuple[ExposureSettings, Controls, Controls]] = []

    def capture(settings: ExposureSettings) -> str:
        seen.append((settings, left.controls, right.controls))
        return "captured"

    result = sync.shoot(capture)

    assert result == "captured"
    assert seen == [
        (ExposureSettings(10_000, 1.0, (2.0, 1.5)), LOCKED_CONTROLS, LOCKED_CONTROLS)
    ]


def test_shoot_resumes_preview_after_capture():
    sync, left, right = make_sync([make_frame(), make_frame()], [make_frame()])

    sync.shoot(lambda settings: None)

    assert sync.locked_settings is None
    assert left.controls["AeEnable"] is True
    assert left.controls["AwbEnable"] is True
    assert right.controls["AeEnable"] is False
    assert right.controls["AwbEnable"] is False


def test_sync_once_does_nothing_during_shoot():
    sync, _, right = make_sync([make_frame(), make_frame()], [make_frame()])
    results: list[ExposureSettings | None] = []
    history_lengths: list[tuple[int, int]] = []

    def capture(settings: ExposureSettings) -> None:
        before = len(right.controls_history)
        results.append(sync.sync_once())
        history_lengths.append((before, len(right.controls_history)))

    sync.shoot(capture)

    assert results == [None]
    assert history_lengths[0][0] == history_lengths[0][1]


def test_shoot_waits_until_delayed_controls_are_reported():
    old = make_frame(
        exposure_time_us=40_000, analogue_gain=8.0, colour_gains=(1.0, 1.0)
    )
    marker = make_frame(exposure_time_us=10_000, analogue_gain=1.0)
    sync, left, right = make_sync(
        [make_frame(), old, old, make_frame()],
        [old, old, old, make_frame(), marker],
    )

    captured = sync.shoot(lambda settings: right.capture_frame())

    assert captured is marker
    with pytest.raises(RuntimeError, match="no scripted frames"):
        left.capture_metadata()


def test_shoot_accepts_values_rounded_by_the_driver():
    sync, _, _ = make_sync(
        [make_frame(), make_frame(exposure_time_us=9_998, analogue_gain=1.003)],
        [make_frame(exposure_time_us=10_004, colour_gains=(2.01, 1.49))],
        max_wait_frames=1,
    )

    assert sync.shoot(lambda settings: "captured") == "captured"


def test_shoot_raises_and_resumes_preview_when_controls_are_never_applied():
    old = make_frame(exposure_time_us=40_000)
    sync, left, _ = make_sync(
        [make_frame(), make_frame()], [old, old, old], max_wait_frames=3
    )
    calls: list[ExposureSettings] = []

    with pytest.raises(ExposureNotAppliedError, match="camera right .* 3 frames"):
        sync.shoot(calls.append)

    assert calls == []
    assert sync.locked_settings is None
    assert left.controls["AeEnable"] is True


def test_shoot_resumes_preview_when_capture_raises():
    sync, left, _ = make_sync([make_frame(), make_frame()], [make_frame()])

    def capture(settings: ExposureSettings) -> None:
        raise RuntimeError("capture failed")

    with pytest.raises(RuntimeError, match="capture failed"):
        sync.shoot(capture)

    assert sync.locked_settings is None
    assert left.controls["AeEnable"] is True


class FailingSetControlsCamera(FakeCamera):
    def set_controls(self, controls: Controls) -> None:
        raise RuntimeError("set_controls failed")


def test_shoot_stays_unlocked_when_left_set_controls_fails():
    left = FailingSetControlsCamera("left", frames=[make_frame()])
    pair = CameraPair(left=left, right=FakeCamera("right"))
    pair.start()
    sync = ExposureSync(pair, settle_frames=0, stable_frames=1)
    calls: list[ExposureSettings] = []

    with pytest.raises(RuntimeError, match="set_controls failed"):
        sync.shoot(calls.append)

    assert calls == []
    assert sync.locked_settings is None


def test_shoot_rejects_invalid_left_values_without_changing_controls():
    sync, left, right = make_sync([make_frame(exposure_time_us=0)])

    with pytest.raises(ValueError, match="exposure_time_us"):
        sync.shoot(lambda settings: None)

    assert sync.locked_settings is None
    assert left.controls_history == []
    assert right.controls_history == []


def test_overlapping_shoots_do_not_resume_preview_mid_capture():
    sync, left, _ = make_sync(
        [make_frame(), make_frame(), make_frame(), make_frame()],
        [make_frame(), make_frame()],
    )
    first_entered = threading.Event()
    release_first = threading.Event()
    events: list[str] = []

    def first_capture(settings: ExposureSettings) -> None:
        events.append("first start")
        first_entered.set()
        release_first.wait(timeout=5)
        events.append("first end")

    def second_capture(settings: ExposureSettings) -> None:
        events.append(f"second start, AeEnable={left.controls['AeEnable']}")

    first = threading.Thread(target=sync.shoot, args=(first_capture,))
    first.start()
    assert first_entered.wait(timeout=5)
    second = threading.Thread(target=sync.shoot, args=(second_capture,))
    second.start()
    second.join(timeout=0.2)
    events_while_first_runs = list(events)
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert events_while_first_runs == ["first start"]
    assert events == ["first start", "first end", "second start, AeEnable=False"]
    assert left.controls["AeEnable"] is True


class BlockingFirstCaptureCamera(FakeCamera):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.entered = threading.Event()
        self.release = threading.Event()
        self._calls = 0

    def capture_metadata(self) -> FrameMetadata:
        self._calls += 1
        if self._calls == 1:
            self.entered.set()
            self.release.wait(timeout=5)
        return super().capture_metadata()


def test_shoot_during_sync_once_is_not_overwritten_by_the_in_flight_sync():
    left = BlockingFirstCaptureCamera(
        "left",
        frames=[
            make_frame(exposure_time_us=10_000),
            make_frame(exposure_time_us=20_000),
            make_frame(exposure_time_us=20_000),
        ],
    )
    right = FakeCamera("right", frames=[make_frame(exposure_time_us=20_000)])
    pair = CameraPair(left=left, right=right)
    pair.start()
    sync = ExposureSync(pair, settle_frames=0, stable_frames=1)
    right_during_capture: list[Controls] = []

    syncing = threading.Thread(target=sync.sync_once)
    syncing.start()
    assert left.entered.wait(timeout=5)
    shooting = threading.Thread(
        target=sync.shoot,
        args=(lambda settings: right_during_capture.append(right.controls),),
    )
    shooting.start()
    shooting.join(timeout=0.2)
    left.release.set()
    syncing.join(timeout=5)
    shooting.join(timeout=5)

    assert right_during_capture == [{**LOCKED_CONTROLS, "ExposureTime": 20_000}]


def make_preview_pair(
    auto: FrameMetadata,
) -> tuple[ExposureSync, ControlledCamera, ControlledCamera]:
    left = ControlledCamera("left", auto)
    right = ControlledCamera("right", make_metadata(exposure_time_us=1))
    pair = CameraPair(left=left, right=right)
    pair.start()
    return ExposureSync(pair), left, right


def test_preview_keeps_copying_left_values_to_right_until_stopped():
    sync, left, right = make_preview_pair(make_metadata(exposure_time_us=10_000))
    preview = ExposurePreview(sync)

    preview.start()
    try:
        assert left.controls["AeEnable"] is True
        assert wait_for(lambda: right.controls.get("ExposureTime") == 10_000)
        left.auto = make_metadata(exposure_time_us=20_000, colour_gains=(1.7, 1.9))
        assert wait_for(lambda: right.controls.get("ExposureTime") == 20_000)
        assert right.controls["ColourGains"] == (1.7, 1.9)
    finally:
        preview.stop()

    assert not preview.running
    history_length = len(right.controls_history)
    left.auto = make_metadata(exposure_time_us=30_000)
    time.sleep(0.02)
    assert len(right.controls_history) == history_length


def test_shoot_while_preview_runs_locks_and_then_resumes_copying():
    sync, left, right = make_preview_pair(make_metadata(exposure_time_us=15_000))

    with ExposurePreview(sync) as preview:
        assert wait_for(lambda: right.controls.get("ExposureTime") == 15_000)
        settings = sync.shoot(lambda settings: settings)
        left.auto = make_metadata(exposure_time_us=25_000)
        assert wait_for(lambda: right.controls.get("ExposureTime") == 25_000)
        assert preview.running

    assert settings == ExposureSettings(15_000, 1.0, (2.0, 1.5))
    assert left.controls["AeEnable"] is True


def test_preview_stops_and_reports_sync_errors(caplog: pytest.LogCaptureFixture):
    sync, _, _ = make_sync()
    preview = ExposurePreview(sync)

    with caplog.at_level(logging.ERROR, logger="pivr180_device.exposure"):
        preview.start()
        assert wait_for(lambda: not preview.running)

    assert isinstance(preview.error, RuntimeError)
    assert "exposure preview sync failed" in caplog.text
    with pytest.raises(RuntimeError, match="stopped on error") as excinfo:
        preview.stop()
    assert isinstance(excinfo.value.__cause__, RuntimeError)
    assert preview.error is None


def test_preview_cannot_be_started_twice():
    sync, _, _ = make_preview_pair(make_metadata())
    preview = ExposurePreview(sync)

    preview.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            preview.start()
    finally:
        preview.stop()


def test_preview_can_be_restarted_after_stop():
    sync, _, right = make_preview_pair(make_metadata(exposure_time_us=12_000))
    preview = ExposurePreview(sync)

    preview.start()
    preview.stop()
    preview.start()
    try:
        assert preview.running
        assert wait_for(lambda: right.controls.get("ExposureTime") == 12_000)
    finally:
        preview.stop()


def test_stop_without_start_is_a_no_op():
    sync, _, _ = make_sync()

    ExposurePreview(sync).stop()


class GatedCamera(ControlledCamera):
    def __init__(self, camera_id: str, auto: FrameMetadata) -> None:
        super().__init__(camera_id, auto)
        self.gate = threading.Event()
        self.gate.set()
        self.blocked = threading.Event()

    def capture_metadata(self) -> FrameMetadata:
        if not self.gate.is_set():
            self.blocked.set()
            self.gate.wait(timeout=5)
        return super().capture_metadata()


def test_start_is_rejected_until_a_stopping_preview_thread_has_exited():
    left = GatedCamera("left", make_metadata())
    right = ControlledCamera("right", make_metadata(exposure_time_us=1))
    pair = CameraPair(left=left, right=right)
    pair.start()
    preview = ExposurePreview(ExposureSync(pair))
    preview.start()
    assert wait_for(lambda: right.controls.get("ExposureTime") == 10_000)
    left.gate.clear()
    assert left.blocked.wait(timeout=5)

    stopping = threading.Thread(target=preview.stop)
    stopping.start()
    stopping.join(timeout=0.1)
    try:
        assert stopping.is_alive()
        with pytest.raises(RuntimeError, match="still stopping"):
            preview.start()
    finally:
        left.gate.set()
        stopping.join(timeout=5)

    assert not stopping.is_alive()
    assert not preview.running
    assert [t.name for t in threading.enumerate()].count("exposure-preview") == 0
    preview.start()
    try:
        assert preview.running
    finally:
        preview.stop()
