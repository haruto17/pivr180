import sys
import types
from pathlib import Path
from typing import Any

import pytest

from pivr180_device.camera import Camera, CameraPair, Frame, FrameMetadata
from pivr180_device.camera.picamera2 import (
    Picamera2Camera,
    Picamera2Frame,
    open_camera_pair,
)

SERVER = "server"
CLIENT = "client"


def make_raw_metadata(**overrides: Any) -> dict[str, Any]:
    metadata = {
        "SensorTimestamp": 123_456_789,
        "ExposureTime": 33_333,
        "AnalogueGain": 4.5,
        "ColourGains": (1.8, 2.2),
        "SyncReady": True,
    }
    metadata.update(overrides)
    return metadata


class StubImage:
    def __init__(self) -> None:
        self.saves: list[tuple[Path, str, int]] = []

    def save(self, fp: Path, format: str, quality: int) -> None:
        fp.write_bytes(b"jpeg")
        self.saves.append((fp, format, quality))


class StubRequest:
    def __init__(self, metadata: dict[str, Any]) -> None:
        self._metadata = metadata
        self.image = StubImage()
        self.released = False
        self.made_images: list[str] = []

    def get_metadata(self) -> dict[str, Any]:
        return self._metadata

    def make_image(self, name: str) -> StubImage:
        self.made_images.append(name)
        return self.image

    def release(self) -> None:
        self.released = True


class StubPicamera2:
    def __init__(self, model: str = "imx477") -> None:
        self.camera_properties = {"Model": model}
        self.requests: list[StubRequest] = []
        self.calls: list[tuple[str, Any]] = []
        self.started = False
        self.closed = False
        self.timeout = False

    def push(self, *requests: StubRequest) -> None:
        self.requests.extend(requests)

    def create_still_configuration(self, **kwargs: Any) -> dict[str, Any]:
        return {"still": kwargs}

    def configure(self, config: dict[str, Any]) -> None:
        self.calls.append(("configure", config))

    def start(self) -> None:
        self.started = True
        self.calls.append(("start", None))

    def stop(self) -> None:
        self.started = False
        self.calls.append(("stop", None))

    def close(self) -> None:
        self.closed = True

    def set_controls(self, controls: dict[str, Any]) -> None:
        self.calls.append(("set_controls", controls))

    def capture_request(self, wait: float) -> StubRequest:
        return self._next("capture_request", wait)

    def capture_sync_request(self, wait: float) -> StubRequest:
        return self._next("capture_sync_request", wait)

    def cancel_all_and_flush(self) -> None:
        self.calls.append(("cancel_all_and_flush", None))

    def _next(self, name: str, wait: float) -> StubRequest:
        self.calls.append((name, wait))
        if self.timeout:
            raise TimeoutError()
        return self.requests.pop(0)


def make_camera(
    picam2: StubPicamera2, *, is_sync_server: bool = True
) -> Picamera2Camera:
    return Picamera2Camera(
        picam2,
        "/base/axi/pcie@1000120000/rp1/i2c@88000/imx477@1a",
        SERVER if is_sync_server else CLIENT,
        is_sync_server=is_sync_server,
        sync_timeout_s=30.0,
        capture_timeout_s=5.0,
    )


def started_camera(*requests: StubRequest) -> tuple[Picamera2Camera, StubPicamera2]:
    picam2 = StubPicamera2()
    picam2.push(*requests)
    camera = make_camera(picam2)
    camera.start()
    return camera, picam2


def capture_calls(picam2: StubPicamera2) -> list[tuple[str, Any]]:
    return [
        call
        for call in picam2.calls
        if call[0] in ("capture_request", "capture_sync_request")
    ]


def test_picamera2_camera_satisfies_camera_interface():
    camera: Camera = make_camera(StubPicamera2(model="imx477"))
    frame: Frame = Picamera2Frame(FrameMetadata(1, 2, 1.0, (1.0, 1.0)), StubImage())

    assert camera.camera_id == "/base/axi/pcie@1000120000/rp1/i2c@88000/imx477@1a"
    assert camera.model == "imx477"
    assert frame.metadata == FrameMetadata(1, 2, 1.0, (1.0, 1.0))


def test_start_configures_full_resolution_with_sync_server_controls():
    picam2 = StubPicamera2()
    camera = make_camera(picam2, is_sync_server=True)

    camera.start()

    assert picam2.calls == [
        (
            "configure",
            {
                "still": {
                    "main": {"size": (4056, 3040)},
                    "buffer_count": 2,
                    "controls": {
                        "FrameRate": 10.0,
                        "SyncMode": SERVER,
                        "SyncFrames": 70,
                    },
                }
            },
        ),
        ("start", None),
    ]
    assert picam2.started


def test_sync_ready_frame_comes_well_after_a_libcamera_sync_packet():
    libcamera_sync_period_frames = 30
    frames_for_correction_to_reach_sensor = 5
    picam2 = StubPicamera2()
    make_camera(picam2, is_sync_server=True).start()

    sync_frames = picam2.calls[0][1]["still"]["controls"]["SyncFrames"]

    assert sync_frames > libcamera_sync_period_frames
    assert (
        sync_frames % libcamera_sync_period_frames
        >= frames_for_correction_to_reach_sensor
    )


def test_start_as_sync_client_does_not_set_sync_frames():
    picam2 = StubPicamera2()
    camera = make_camera(picam2, is_sync_server=False)

    camera.start()

    config = picam2.calls[0][1]
    assert config["still"]["controls"] == {"FrameRate": 10.0, "SyncMode": CLIENT}


def test_first_capture_waits_for_sync_then_later_captures_do_not():
    camera, picam2 = started_camera(
        StubRequest(make_raw_metadata(SensorTimestamp=1)),
        StubRequest(make_raw_metadata(SensorTimestamp=2)),
        StubRequest(make_raw_metadata(SensorTimestamp=3)),
    )

    camera.capture_frame()
    camera.capture_metadata()
    camera.capture_frame()

    assert capture_calls(picam2) == [
        ("capture_sync_request", 30.0),
        ("capture_request", 5.0),
        ("capture_request", 5.0),
    ]


def test_restart_waits_for_sync_again():
    camera, picam2 = started_camera(
        StubRequest(make_raw_metadata()),
        StubRequest(make_raw_metadata()),
    )
    camera.capture_metadata()

    camera.stop()
    camera.start()
    camera.capture_metadata()

    assert [name for name, _ in capture_calls(picam2)] == [
        "capture_sync_request",
        "capture_sync_request",
    ]


def test_capture_frame_converts_metadata_and_releases_request():
    request = StubRequest(make_raw_metadata())
    camera, _ = started_camera(request)

    frame = camera.capture_frame()

    assert frame.metadata == FrameMetadata(
        sensor_timestamp_ns=123_456_789,
        exposure_time_us=33_333,
        analogue_gain=4.5,
        colour_gains=(1.8, 2.2),
    )
    assert request.made_images == ["main"]
    assert request.released


def test_capture_metadata_converts_metadata_and_releases_request():
    request = StubRequest(make_raw_metadata(ExposureTime=10_000, AnalogueGain=2))
    camera, _ = started_camera(request)

    metadata = camera.capture_metadata()

    assert metadata.exposure_time_us == 10_000
    assert metadata.analogue_gain == 2.0
    assert isinstance(metadata.analogue_gain, float)
    assert request.released


@pytest.mark.parametrize(
    "metadata",
    [
        {k: v for k, v in make_raw_metadata().items() if k != "SensorTimestamp"},
        {k: v for k, v in make_raw_metadata().items() if k != "ColourGains"},
        make_raw_metadata(ColourGains=(1.8,)),
        make_raw_metadata(ExposureTime=None),
    ],
    ids=["no-timestamp", "no-colour-gains", "one-colour-gain", "none-exposure"],
)
def test_capture_raises_and_releases_request_on_unexpected_metadata(
    metadata: dict[str, Any],
):
    request = StubRequest(metadata)
    camera, _ = started_camera(request)

    with pytest.raises(RuntimeError, match="unexpected frame metadata"):
        camera.capture_frame()

    assert request.released


def test_frame_save_writes_jpeg_with_quality(tmp_path: Path):
    request = StubRequest(make_raw_metadata())
    camera, _ = started_camera(request)
    frame = camera.capture_frame()
    path = tmp_path / "left.jpg"

    frame.save(path, quality=100)

    assert path.read_bytes() == b"jpeg"
    assert request.image.saves == [(path, "JPEG", 100)]


def test_capture_raises_when_not_started():
    picam2 = StubPicamera2()
    picam2.push(StubRequest(make_raw_metadata()))
    camera = make_camera(picam2)

    with pytest.raises(RuntimeError, match="not started"):
        camera.capture_frame()


def test_capture_raises_after_stop():
    camera, picam2 = started_camera(StubRequest(make_raw_metadata()))

    camera.stop()

    with pytest.raises(RuntimeError, match="not started"):
        camera.capture_metadata()
    assert not picam2.started


def test_sync_timeout_cancels_pending_jobs_and_raises():
    camera, picam2 = started_camera()
    picam2.timeout = True

    with pytest.raises(TimeoutError, match="did not synchronise within 30.0s"):
        camera.capture_frame()

    assert picam2.calls[-1] == ("cancel_all_and_flush", None)


def test_sync_timeout_is_retried_with_sync_on_next_capture():
    camera, picam2 = started_camera(StubRequest(make_raw_metadata()))
    picam2.timeout = True
    with pytest.raises(TimeoutError):
        camera.capture_frame()

    picam2.timeout = False
    camera.capture_frame()

    assert [name for name, _ in capture_calls(picam2)] == [
        "capture_sync_request",
        "capture_sync_request",
    ]


def test_capture_timeout_after_sync_cancels_pending_jobs_and_raises():
    camera, picam2 = started_camera(StubRequest(make_raw_metadata()))
    camera.capture_frame()
    picam2.timeout = True

    with pytest.raises(TimeoutError, match="no frame arrived within 5.0s"):
        camera.capture_metadata()

    assert picam2.calls[-1] == ("cancel_all_and_flush", None)


def test_set_controls_passes_a_copy_to_picamera2():
    picam2 = StubPicamera2()
    camera = make_camera(picam2)
    controls = {"ExposureTime": 20_000, "ColourGains": (1.9, 1.6)}

    camera.set_controls(controls)
    controls["ExposureTime"] = 1

    assert picam2.calls == [
        ("set_controls", {"ExposureTime": 20_000, "ColourGains": (1.9, 1.6)})
    ]


def test_close_closes_picamera2():
    picam2 = StubPicamera2()
    camera = make_camera(picam2)

    camera.close()

    assert picam2.closed


class StubPicamera2Factory:
    def __init__(self, fail_on: int | None = None) -> None:
        self.camera_info = [
            {"Id": "/base/imx477@1a-cam0", "Model": "imx477", "Num": 0},
            {"Id": "/base/imx477@1a-cam1", "Model": "imx477", "Num": 1},
        ]
        self.fail_on = fail_on
        self.opened: dict[int, StubPicamera2] = {}

    def global_camera_info(self) -> list[dict[str, Any]]:
        return self.camera_info

    def __call__(self, index: int) -> StubPicamera2:
        if index == self.fail_on:
            raise RuntimeError(f"failed to open camera {index}")
        self.opened[index] = StubPicamera2()
        return self.opened[index]


@pytest.fixture
def picamera2_factory(monkeypatch: pytest.MonkeyPatch) -> StubPicamera2Factory:
    factory = StubPicamera2Factory()
    picamera2_module = types.ModuleType("picamera2")
    picamera2_module.Picamera2 = factory  # type: ignore[attr-defined]
    libcamera_module = types.ModuleType("libcamera")
    libcamera_module.controls = types.SimpleNamespace(  # type: ignore[attr-defined]
        rpi=types.SimpleNamespace(
            SyncModeEnum=types.SimpleNamespace(Server=SERVER, Client=CLIENT)
        )
    )
    monkeypatch.setitem(sys.modules, "picamera2", picamera2_module)
    monkeypatch.setitem(sys.modules, "libcamera", libcamera_module)
    return factory


def test_open_camera_pair_makes_left_the_sync_server_and_right_the_client(
    picamera2_factory: StubPicamera2Factory,
):
    with open_camera_pair(left_index=1, right_index=0) as pair:
        assert isinstance(pair, CameraPair)
        assert pair.left.camera_id == "/base/imx477@1a-cam1"
        assert pair.right.camera_id == "/base/imx477@1a-cam0"
        pair.start()
        left_controls = picamera2_factory.opened[1].calls[0][1]["still"]["controls"]
        right_controls = picamera2_factory.opened[0].calls[0][1]["still"]["controls"]

    assert left_controls["SyncMode"] == SERVER
    assert "SyncFrames" in left_controls
    assert right_controls["SyncMode"] == CLIENT
    assert "SyncFrames" not in right_controls


def test_open_camera_pair_closes_both_cameras_on_exit(
    picamera2_factory: StubPicamera2Factory,
):
    with pytest.raises(RuntimeError, match="boom"), open_camera_pair():
        raise RuntimeError("boom")

    assert picamera2_factory.opened[0].closed
    assert picamera2_factory.opened[1].closed


def test_open_camera_pair_closes_left_when_right_fails_to_open(
    picamera2_factory: StubPicamera2Factory,
):
    picamera2_factory.fail_on = 1

    with (
        pytest.raises(RuntimeError, match="failed to open camera 1"),
        open_camera_pair(),
    ):
        pass

    assert picamera2_factory.opened[0].closed


@pytest.mark.parametrize(("left", "right"), [(0, 2), (-1, 1)])
def test_open_camera_pair_rejects_missing_camera_index(
    picamera2_factory: StubPicamera2Factory, left: int, right: int
):
    with (
        pytest.raises(RuntimeError, match="not found"),
        open_camera_pair(left_index=left, right_index=right),
    ):
        pass

    assert all(camera.closed for camera in picamera2_factory.opened.values())


def test_open_camera_pair_rejects_same_index_for_both_sides(
    picamera2_factory: StubPicamera2Factory,
):
    with (
        pytest.raises(ValueError, match="must differ"),
        open_camera_pair(left_index=0, right_index=0),
    ):
        pass

    assert picamera2_factory.opened == {}
