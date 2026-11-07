import math
import threading

import pytest

from pivr180_device.camera import CameraPair, Controls, FrameMetadata
from pivr180_device.camera.fake import FakeCamera, FakeFrame
from pivr180_device.exposure import ExposureSettings, ExposureSync


def make_frame(
    exposure_time_us: int = 10_000,
    analogue_gain: float = 1.0,
    colour_gains: tuple[float, float] = (2.0, 1.5),
) -> FakeFrame:
    return FakeFrame(
        FrameMetadata(
            sensor_timestamp_ns=0,
            exposure_time_us=exposure_time_us,
            analogue_gain=analogue_gain,
            colour_gains=colour_gains,
        )
    )


def make_sync(*left_frames: FakeFrame) -> tuple[ExposureSync, FakeCamera, FakeCamera]:
    left = FakeCamera("left", frames=left_frames)
    right = FakeCamera("right")
    pair = CameraPair(left=left, right=right)
    pair.start()
    return ExposureSync(pair), left, right


class FailingSetControlsCamera(FakeCamera):
    def set_controls(self, controls: Controls) -> None:
        raise RuntimeError("set_controls failed")


def test_resume_preview_enables_auto_on_left_and_disables_it_on_right():
    sync, left, right = make_sync()

    sync.resume_preview()

    assert left.controls == {"AeEnable": True, "AwbEnable": True}
    assert right.controls == {"AeEnable": False, "AwbEnable": False}


def test_sync_once_copies_left_values_to_right_without_touching_left():
    sync, left, right = make_sync(
        make_frame(exposure_time_us=33_333, analogue_gain=4.5, colour_gains=(1.8, 2.2))
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
        make_frame(exposure_time_us=10_000, analogue_gain=1.0),
        make_frame(exposure_time_us=20_000, analogue_gain=2.0),
    )

    sync.sync_once()
    sync.sync_once()

    assert right.controls["ExposureTime"] == 20_000
    assert right.controls["AnalogueGain"] == 2.0


def test_lock_sets_identical_manual_values_on_both_cameras():
    sync, left, right = make_sync(
        make_frame(exposure_time_us=25_000, analogue_gain=3.0, colour_gains=(1.9, 1.6))
    )
    sync.resume_preview()

    settings = sync.lock()

    expected = {
        "AeEnable": False,
        "AwbEnable": False,
        "ExposureTime": 25_000,
        "AnalogueGain": 3.0,
        "ColourGains": (1.9, 1.6),
    }
    assert settings == ExposureSettings(25_000, 3.0, (1.9, 1.6))
    assert left.controls == expected
    assert right.controls == expected
    assert sync.locked_settings == settings


def test_sync_once_does_nothing_while_locked():
    sync, left, right = make_sync(make_frame(), make_frame(exposure_time_us=99_999))
    sync.lock()
    right_history = list(right.controls_history)

    assert sync.sync_once() is None
    assert right.controls_history == right_history
    assert left.capture_metadata().exposure_time_us == 99_999


def test_lock_while_locked_keeps_the_first_values():
    sync, left, _ = make_sync(
        make_frame(exposure_time_us=10_000), make_frame(exposure_time_us=99_999)
    )

    first = sync.lock()
    second = sync.lock()

    assert second == first
    assert left.capture_metadata().exposure_time_us == 99_999


def test_resume_preview_after_lock_restarts_copying():
    sync, left, right = make_sync(
        make_frame(exposure_time_us=10_000), make_frame(exposure_time_us=20_000)
    )
    sync.lock()

    sync.resume_preview()
    settings = sync.sync_once()

    assert sync.locked_settings is None
    assert left.controls["AeEnable"] is True
    assert left.controls["AwbEnable"] is True
    assert settings is not None
    assert right.controls["ExposureTime"] == 20_000


def test_locked_context_resumes_preview_on_exit():
    sync, left, _ = make_sync(make_frame())

    with sync.locked() as settings:
        assert sync.locked_settings == settings
        assert left.controls["AeEnable"] is False

    assert sync.locked_settings is None
    assert left.controls["AeEnable"] is True


def test_locked_context_resumes_preview_when_body_raises():
    sync, left, _ = make_sync(make_frame())

    with pytest.raises(RuntimeError, match="capture failed"), sync.locked():
        raise RuntimeError("capture failed")

    assert sync.locked_settings is None
    assert left.controls["AeEnable"] is True


def test_locked_context_keeps_an_outer_lock():
    sync, _, _ = make_sync(make_frame())
    outer = sync.lock()

    with sync.locked() as settings:
        assert settings == outer

    assert sync.locked_settings == outer


def test_lock_stays_unlocked_when_left_set_controls_fails():
    left = FailingSetControlsCamera("left", frames=[make_frame()])
    right = FakeCamera("right")
    pair = CameraPair(left=left, right=right)
    pair.start()
    sync = ExposureSync(pair)

    with pytest.raises(RuntimeError, match="set_controls failed"):
        sync.lock()

    assert sync.locked_settings is None


def test_resume_preview_stays_locked_when_left_set_controls_fails():
    sync, left, _ = make_sync(make_frame())
    settings = sync.lock()

    def fail(controls: Controls) -> None:
        raise RuntimeError("set_controls failed")

    left.set_controls = fail

    with pytest.raises(RuntimeError, match="set_controls failed"):
        sync.resume_preview()

    assert sync.locked_settings == settings


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
        make_frame(exposure_time_us, analogue_gain, colour_gains)
    )

    with pytest.raises(ValueError):
        sync.sync_once()

    assert right.controls_history == []


def test_lock_rejects_invalid_left_values_and_stays_unlocked():
    sync, left, right = make_sync(make_frame(exposure_time_us=0))

    with pytest.raises(ValueError, match="exposure_time_us"):
        sync.lock()

    assert sync.locked_settings is None
    assert left.controls_history == []
    assert right.controls_history == []


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


def test_lock_during_sync_once_is_not_overwritten_by_the_in_flight_sync():
    left = BlockingFirstCaptureCamera(
        "left",
        frames=[
            make_frame(exposure_time_us=10_000),
            make_frame(exposure_time_us=20_000),
        ],
    )
    right = FakeCamera("right")
    pair = CameraPair(left=left, right=right)
    pair.start()
    sync = ExposureSync(pair)
    results: list[ExposureSettings] = []

    syncing = threading.Thread(target=sync.sync_once)
    syncing.start()
    assert left.entered.wait(timeout=5)
    locking = threading.Thread(target=lambda: results.append(sync.lock()))
    locking.start()
    locking.join(timeout=0.2)
    left.release.set()
    syncing.join(timeout=5)
    locking.join(timeout=5)

    assert results == [ExposureSettings(20_000, 1.0, (2.0, 1.5))]
    assert right.controls["ExposureTime"] == 20_000
    assert left.controls == right.controls
