from pathlib import Path

import pytest

from pivr180_device.camera import Camera, CameraPair, Frame, FrameMetadata
from pivr180_device.camera.fake import FakeCamera, FakeFrame


def make_metadata(
    sensor_timestamp_ns: int = 0,
    exposure_time_us: int = 10_000,
    analogue_gain: float = 1.0,
    colour_gains: tuple[float, float] = (2.0, 1.5),
) -> FrameMetadata:
    return FrameMetadata(
        sensor_timestamp_ns=sensor_timestamp_ns,
        exposure_time_us=exposure_time_us,
        analogue_gain=analogue_gain,
        colour_gains=colour_gains,
    )


def test_fake_camera_satisfies_camera_interface():
    camera: Camera = FakeCamera("left")
    frame: Frame = FakeFrame(make_metadata())

    assert camera.camera_id == "left"
    assert camera.model == "imx477"
    assert frame.metadata == make_metadata()


def test_capture_frame_returns_scripted_frames_in_order():
    first = FakeFrame(make_metadata(sensor_timestamp_ns=1_000))
    second = FakeFrame(make_metadata(sensor_timestamp_ns=2_500_000))
    camera = FakeCamera("left", frames=[first, second])
    camera.start()

    assert camera.capture_frame() is first
    assert camera.capture_frame() is second


def test_capture_metadata_returns_scripted_exposure_values():
    metadata = make_metadata(
        sensor_timestamp_ns=123_456_789,
        exposure_time_us=33_333,
        analogue_gain=4.5,
        colour_gains=(1.8, 2.2),
    )
    camera = FakeCamera("left", frames=[FakeFrame(metadata)])
    camera.start()

    assert camera.capture_metadata() == metadata


def test_capture_metadata_consumes_a_frame():
    camera = FakeCamera(
        "left",
        frames=[
            FakeFrame(make_metadata(sensor_timestamp_ns=1)),
            FakeFrame(make_metadata(sensor_timestamp_ns=2)),
        ],
    )
    camera.start()

    camera.capture_metadata()

    assert camera.capture_frame().metadata.sensor_timestamp_ns == 2


def test_push_adds_frames_after_construction():
    camera = FakeCamera("left")
    camera.start()
    frame = FakeFrame(make_metadata(sensor_timestamp_ns=42))

    camera.push(frame)

    assert camera.capture_frame() is frame


def test_capture_raises_when_frames_are_exhausted():
    camera = FakeCamera("left")
    camera.start()

    with pytest.raises(RuntimeError):
        camera.capture_frame()


def test_capture_raises_when_not_started():
    camera = FakeCamera("left", frames=[FakeFrame(make_metadata())])

    with pytest.raises(RuntimeError):
        camera.capture_frame()


def test_capture_raises_after_stop():
    camera = FakeCamera("left", frames=[FakeFrame(make_metadata())])
    camera.start()
    camera.stop()

    with pytest.raises(RuntimeError):
        camera.capture_metadata()


def test_set_controls_records_history_and_merged_controls():
    camera = FakeCamera("right")

    camera.set_controls({"ExposureTime": 20_000, "AnalogueGain": 2.0})
    camera.set_controls(
        {
            "AnalogueGain": 3.0,
            "ColourGains": (1.9, 1.6),
            "AeEnable": False,
            "AwbEnable": False,
        }
    )

    assert camera.controls_history == [
        {"ExposureTime": 20_000, "AnalogueGain": 2.0},
        {
            "AnalogueGain": 3.0,
            "ColourGains": (1.9, 1.6),
            "AeEnable": False,
            "AwbEnable": False,
        },
    ]
    assert camera.controls == {
        "ExposureTime": 20_000,
        "AnalogueGain": 3.0,
        "ColourGains": (1.9, 1.6),
        "AeEnable": False,
        "AwbEnable": False,
    }


def test_set_controls_is_not_affected_by_later_mutation_of_the_argument():
    camera = FakeCamera("right")
    controls = {"ExposureTime": 20_000}

    camera.set_controls(controls)
    controls["ExposureTime"] = 1

    assert camera.controls == {"ExposureTime": 20_000}


def test_fake_frame_save_writes_image_and_records_quality(tmp_path: Path):
    frame = FakeFrame(make_metadata(), image=b"jpeg-bytes")
    path = tmp_path / "left.jpg"

    frame.save(path, quality=100)

    assert path.read_bytes() == b"jpeg-bytes"
    assert frame.saves == [(path, 100)]


def test_camera_pair_starts_and_stops_both_cameras():
    left = FakeCamera("left")
    right = FakeCamera("right")
    pair = CameraPair(left=left, right=right)

    pair.start()
    assert left.started and right.started

    pair.stop()
    assert not left.started and not right.started


class FailingStartCamera(FakeCamera):
    def start(self) -> None:
        raise RuntimeError("start failed")


class FailingStopCamera(FakeCamera):
    def stop(self) -> None:
        raise RuntimeError("stop failed")


def test_camera_pair_stops_left_when_right_fails_to_start():
    left = FakeCamera("left")
    pair = CameraPair(left=left, right=FailingStartCamera("right"))

    with pytest.raises(RuntimeError, match="start failed"):
        pair.start()

    assert not left.started


def test_camera_pair_stops_right_when_left_fails_to_stop():
    right = FakeCamera("right")
    pair = CameraPair(left=FailingStopCamera("left"), right=right)
    right.start()

    with pytest.raises(RuntimeError, match="stop failed"):
        pair.stop()

    assert not right.started
