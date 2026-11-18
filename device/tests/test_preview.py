import io
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import httpx2
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pivr180_device.atoms3.fake import FakeClock
from pivr180_device.camera import CameraPair
from pivr180_device.camera.fake import FakeCamera
from pivr180_device.exposure import ExposureSync
from pivr180_device.preview import (
    PREVIEW_PATH,
    PreviewFrames,
    preview_router,
    side_by_side_jpeg,
)
from pivr180_device.slot import CameraSlot, LiveCameras
from pivr180_device.web import create_app, serve

LEFT_COLOR = (220, 30, 30)
RIGHT_COLOR = (30, 30, 220)
EYE_SIZE = (64, 48)
FAST_FPS = 1000.0
WAIT_S = 5.0


class PreviewCamera(FakeCamera):
    def __init__(
        self,
        camera_id: str,
        color: tuple[int, int, int],
        limit: int | None = None,
    ) -> None:
        super().__init__(camera_id, preview_size=EYE_SIZE, preview_color=color)
        self.limit = limit
        self.captured = threading.Event()

    def capture_preview(self) -> Image.Image:
        if self.limit is not None and self.previews >= self.limit:
            raise RuntimeError(f"camera {self.camera_id} lost the preview")
        image = super().capture_preview()
        self.captured.set()
        return image


def live_cameras(limit: int | None = None) -> LiveCameras:
    pair = CameraPair(
        left=PreviewCamera("left", LEFT_COLOR, limit),
        right=PreviewCamera("right", RIGHT_COLOR, limit),
    )
    pair.start()
    return LiveCameras(pair=pair, exposure=ExposureSync(pair))


def assert_close(actual: tuple[int, ...], expected: tuple[int, ...]) -> None:
    assert all(abs(a - e) <= 16 for a, e in zip(actual, expected, strict=True))


def assert_side_by_side(jpeg: bytes) -> None:
    image = Image.open(io.BytesIO(jpeg))
    assert image.format == "JPEG"
    assert image.size == (EYE_SIZE[0] * 2, EYE_SIZE[1])
    assert_close(image.getpixel((EYE_SIZE[0] // 2, EYE_SIZE[1] // 2)), LEFT_COLOR)
    assert_close(image.getpixel((EYE_SIZE[0] * 3 // 2, EYE_SIZE[1] // 2)), RIGHT_COLOR)


def split_parts(body: bytes) -> list[tuple[dict[str, str], bytes]]:
    parts = []
    for chunk in body.split(b"--frame\r\n")[1:]:
        head, _, rest = chunk.partition(b"\r\n\r\n")
        headers = dict(
            line.split(": ", 1) for line in head.decode("ascii").split("\r\n")
        )
        length = int(headers["Content-Length"])
        assert rest[length:] == b"\r\n"
        parts.append((headers, rest[:length]))
    return parts


class TickingClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def client_for(slot: CameraSlot, max_fps: float = FAST_FPS) -> TestClient:
    # Not the real clock: frames within the interval share a cached JPEG, so
    # the number of frames sent would depend on how fast the test runs.
    router = preview_router(slot, max_fps=max_fps, clock=TickingClock())
    return TestClient(create_app([router]))


@contextmanager
def attached_in_background(
    slot: CameraSlot, cameras: LiveCameras
) -> Iterator[threading.Event]:
    detach = threading.Event()
    attached = threading.Event()

    def owner() -> None:
        with slot.attach(cameras):
            attached.set()
            detach.wait(WAIT_S)

    thread = threading.Thread(target=owner)
    thread.start()
    attached.wait(WAIT_S)
    try:
        yield detach
    finally:
        detach.set()
        thread.join(WAIT_S)


def test_side_by_side_jpeg_puts_left_on_the_left_and_right_on_the_right():
    left = Image.new("RGB", EYE_SIZE, LEFT_COLOR)
    right = Image.new("RGB", EYE_SIZE, RIGHT_COLOR)

    assert_side_by_side(side_by_side_jpeg(left, right))


def test_preview_is_unavailable_until_the_cameras_are_ready():
    response = client_for(CameraSlot()).get(PREVIEW_PATH)

    assert response.status_code == 503


def test_preview_is_unavailable_after_the_cameras_are_detached():
    slot = CameraSlot()
    with slot.attach(live_cameras()):
        pass

    assert client_for(slot).get(PREVIEW_PATH).status_code == 503


def test_streams_side_by_side_jpeg_frames_as_mjpeg(caplog: pytest.LogCaptureFixture):
    slot = CameraSlot()
    frames = 3

    with slot.attach(live_cameras(limit=frames)), caplog.at_level(logging.ERROR):
        response = client_for(slot).get(PREVIEW_PATH)

    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "multipart/x-mixed-replace; boundary=frame"
    )
    assert response.headers["cache-control"] == "no-store"
    parts = split_parts(response.content)
    assert len(parts) == frames
    for headers, jpeg in parts:
        assert headers["Content-Type"] == "image/jpeg"
        assert_side_by_side(jpeg)


def test_ends_the_stream_and_logs_when_a_camera_fails(
    caplog: pytest.LogCaptureFixture,
):
    slot = CameraSlot()

    with slot.attach(live_cameras(limit=1)), caplog.at_level(logging.ERROR):
        response = client_for(slot).get(PREVIEW_PATH)

    assert len(split_parts(response.content)) == 1
    assert "live preview failed" in caplog.text
    assert "lost the preview" in caplog.text


def test_ends_the_stream_when_the_cameras_are_detached():
    slot = CameraSlot()
    cameras = live_cameras()
    left = cameras.pair.left
    assert isinstance(left, PreviewCamera)

    with attached_in_background(slot, cameras) as detach:

        def detach_after_first_frame() -> None:
            left.captured.wait(WAIT_S)
            detach.set()

        detacher = threading.Thread(target=detach_after_first_frame)
        detacher.start()
        response = client_for(slot, max_fps=50.0).get(PREVIEW_PATH)
        detacher.join(WAIT_S)

    assert response.status_code == 200
    assert len(split_parts(response.content)) >= 1


def test_limits_the_frame_rate_of_a_stream():
    slot = CameraSlot()
    frames = 4
    max_fps = 20.0

    client = TestClient(create_app([preview_router(slot, max_fps=max_fps)]))

    with slot.attach(live_cameras(limit=frames)):
        started = time.monotonic()
        response = client.get(PREVIEW_PATH)
        elapsed = time.monotonic() - started

    assert len(split_parts(response.content)) == frames
    assert elapsed >= (frames - 1) / max_fps


def test_clients_within_the_frame_interval_share_one_capture():
    slot = CameraSlot()
    clock = FakeClock()
    frames = PreviewFrames(slot, min_interval_s=0.2, clock=clock)
    cameras = live_cameras()
    left = cameras.pair.left
    assert isinstance(left, PreviewCamera)

    with slot.attach(cameras):
        first = frames.latest()
        clock.sleep(0.1)
        shared = frames.latest()
        clock.sleep(0.1)
        next_frame = frames.latest()

    assert first is not None
    assert shared is first
    assert next_frame is not None and next_frame is not first
    assert left.previews == 2


def test_gives_no_frame_once_the_cameras_are_detached_even_if_one_is_fresh():
    slot = CameraSlot()
    frames = PreviewFrames(slot, min_interval_s=60.0, clock=FakeClock())
    with slot.attach(live_cameras()):
        assert frames.latest() is not None

    assert frames.latest() is None


def test_streams_over_http_until_the_cameras_are_detached():
    slot = CameraSlot()
    app = create_app([preview_router(slot, max_fps=50.0)])

    with (
        attached_in_background(slot, live_cameras()) as detach,
        serve(app, "127.0.0.1", 0) as server,
        httpx2.Client() as client,
    ):
        [listener] = server.servers[0].sockets
        port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}{PREVIEW_PATH}"
        with client.stream("GET", url) as response:
            chunks = response.iter_bytes()
            first = next(chunks)
            detach.set()
            rest = b"".join(chunks)

    assert response.status_code == 200
    assert first.startswith(b"--frame\r\n")
    assert split_parts(first + rest)
