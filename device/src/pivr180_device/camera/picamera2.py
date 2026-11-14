import logging
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Protocol

from PIL.Image import Image

from pivr180_device.camera.base import CameraPair, Controls, FrameMetadata
from pivr180_device.storage import STILL_SIZE

logger = logging.getLogger(__name__)

FRAME_RATE = 10.0
PREVIEW_SIZE = (640, 480)
PREVIEW_STREAM = "lores"
# Not YUV420 (the lores default): it would need converting to RGB in Python
# before JPEG encoding, while the Pi 5 ISP can output RGB on lores directly.
PREVIEW_FORMAT = "RGB888"
LIBCAMERA_SYNC_PERIOD_FRAMES = 30
SYNC_CORRECTIONS_BEFORE_READY = 2
SYNC_CORRECTION_MARGIN_FRAMES = 10
# Not a multiple of the sync period (e.g. 30): rpi.sync sends the server's
# timing every LIBCAMERA_SYNC_PERIOD_FRAMES, starting at that frame, so being
# ready on a packet frame would precede the client's frame-length correction
# reaching the sensor.
SYNC_FRAMES = (
    LIBCAMERA_SYNC_PERIOD_FRAMES * SYNC_CORRECTIONS_BEFORE_READY
    + SYNC_CORRECTION_MARGIN_FRAMES
)
BUFFER_COUNT = 2
SYNC_TIMEOUT_S = 30.0
CAPTURE_TIMEOUT_S = 5.0


class _Image(Protocol):
    @property
    def size(self) -> tuple[int, int]: ...

    def save(self, fp: Path, format: str, quality: int) -> None: ...


class Picamera2Frame:
    def __init__(self, metadata: FrameMetadata, image: _Image) -> None:
        self._metadata = metadata
        self._image = image

    @property
    def metadata(self) -> FrameMetadata:
        return self._metadata

    @property
    def size(self) -> tuple[int, int]:
        return self._image.size

    def save(self, path: Path, quality: int) -> None:
        self._image.save(path, format="JPEG", quality=quality)


class Picamera2Camera:
    def __init__(
        self,
        picam2: Any,
        camera_id: str,
        sync_mode: Any,
        *,
        is_sync_server: bool,
        size: tuple[int, int] = STILL_SIZE,
        preview_size: tuple[int, int] = PREVIEW_SIZE,
        frame_rate: float = FRAME_RATE,
        sync_frames: int = SYNC_FRAMES,
        sync_timeout_s: float = SYNC_TIMEOUT_S,
        capture_timeout_s: float = CAPTURE_TIMEOUT_S,
    ) -> None:
        self._picam2 = picam2
        self._camera_id = camera_id
        self._sync_mode = sync_mode
        self._is_sync_server = is_sync_server
        self._size = size
        self._preview_size = preview_size
        self._frame_rate = frame_rate
        self._sync_frames = sync_frames
        self._sync_timeout_s = sync_timeout_s
        self._capture_timeout_s = capture_timeout_s
        self._started = False
        self._synced = False
        self._preview = threading.Condition()
        self._preview_wanted = False
        self._preview_image: Image | None = None
        self._preview_count = 0

    @property
    def camera_id(self) -> str:
        return self._camera_id

    @property
    def model(self) -> str:
        return str(self._picam2.camera_properties["Model"])

    def start(self) -> None:
        controls: dict[str, Any] = {
            "FrameRate": self._frame_rate,
            "SyncMode": self._sync_mode,
        }
        if self._is_sync_server:
            controls["SyncFrames"] = self._sync_frames
        config = self._picam2.create_still_configuration(
            main={"size": self._size},
            lores={"size": self._preview_size, "format": PREVIEW_FORMAT},
            buffer_count=BUFFER_COUNT,
            controls=controls,
        )
        self._picam2.configure(config)
        # Not capture_request for the preview: it would take frames from the
        # exposure copy and the shot running on other threads.
        self._picam2.post_callback = self._on_request
        self._picam2.start()
        self._started = True
        self._synced = False

    def stop(self) -> None:
        self._mark_stopped()
        self._picam2.stop()

    def close(self) -> None:
        self._mark_stopped()
        self._picam2.close()

    def set_controls(self, controls: Controls) -> None:
        self._picam2.set_controls(dict(controls))

    def capture_metadata(self) -> FrameMetadata:
        request = self._capture_request()
        try:
            return self._to_frame_metadata(request.get_metadata())
        finally:
            request.release()

    def capture_frame(self) -> Picamera2Frame:
        request = self._capture_request()
        try:
            metadata = self._to_frame_metadata(request.get_metadata())
            # Not kept until save(): holding the request would starve the
            # camera's buffer pool, so the pixels are copied out instead.
            image = request.make_image("main")
        finally:
            request.release()
        return Picamera2Frame(metadata, image)

    def capture_preview(self) -> Image:
        with self._preview:
            if not self._started:
                raise RuntimeError(f"camera {self._camera_id} is not started")
            count = self._preview_count
            self._preview_wanted = True
            arrived = self._preview.wait_for(
                lambda: self._preview_count != count or not self._started,
                self._capture_timeout_s,
            )
            if not self._started:
                raise RuntimeError(f"camera {self._camera_id} stopped")
            if not arrived or self._preview_image is None:
                raise TimeoutError(
                    f"camera {self._camera_id}: no preview frame arrived "
                    f"within {self._capture_timeout_s}s"
                )
            return self._preview_image

    def _on_request(self, request: Any) -> None:
        with self._preview:
            if not self._preview_wanted:
                return
            self._preview_wanted = False
        try:
            image = request.make_image(PREVIEW_STREAM)
        except Exception:
            # Not raised: this runs on Picamera2's camera thread, which would
            # stop delivering frames to the preview and the shots.
            logger.exception("camera %s: failed to make a preview", self._camera_id)
            return
        with self._preview:
            self._preview_image = image
            self._preview_count += 1
            self._preview.notify_all()

    def _mark_stopped(self) -> None:
        with self._preview:
            self._started = False
            self._synced = False
            self._preview.notify_all()

    def _capture_request(self) -> Any:
        if not self._started:
            raise RuntimeError(f"camera {self._camera_id} is not started")
        if self._synced:
            return self._wait_for_request(
                self._picam2.capture_request,
                self._capture_timeout_s,
                "no frame arrived",
            )
        request = self._wait_for_request(
            self._picam2.capture_sync_request,
            self._sync_timeout_s,
            "cameras did not synchronise",
        )
        self._synced = True
        return request

    def _wait_for_request(
        self, capture: Callable[..., Any], timeout_s: float, reason: str
    ) -> Any:
        try:
            return capture(wait=timeout_s)
        except TimeoutError as error:
            self._picam2.cancel_all_and_flush()
            raise TimeoutError(
                f"camera {self._camera_id}: {reason} within {timeout_s}s"
            ) from error

    def _to_frame_metadata(self, metadata: Mapping[str, Any]) -> FrameMetadata:
        try:
            red_gain, blue_gain = metadata["ColourGains"]
            return FrameMetadata(
                sensor_timestamp_ns=int(metadata["SensorTimestamp"]),
                exposure_time_us=int(metadata["ExposureTime"]),
                analogue_gain=float(metadata["AnalogueGain"]),
                colour_gains=(float(red_gain), float(blue_gain)),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(
                f"camera {self._camera_id}: unexpected frame metadata: {error!r}"
            ) from error


@contextmanager
def open_camera_pair(
    left_index: int = 0,
    right_index: int = 1,
) -> Iterator[CameraPair]:
    if left_index == right_index:
        raise ValueError(f"left and right camera indexes must differ: {left_index}")

    # Not imported at module level: picamera2 and libcamera exist only as apt
    # packages on the Pi, and this module must stay importable on a Mac.
    from libcamera import controls
    from picamera2 import Picamera2

    camera_info = Picamera2.global_camera_info()
    with ExitStack() as stack:
        cameras = []
        for index, sync_mode, is_sync_server in (
            (left_index, controls.rpi.SyncModeEnum.Server, True),
            (right_index, controls.rpi.SyncModeEnum.Client, False),
        ):
            if not 0 <= index < len(camera_info):
                raise RuntimeError(
                    f"camera index {index} not found; "
                    f"{len(camera_info)} camera(s) attached"
                )
            camera = Picamera2Camera(
                Picamera2(index),
                camera_info[index]["Id"],
                sync_mode,
                is_sync_server=is_sync_server,
            )
            stack.callback(camera.close)
            cameras.append(camera)
        yield CameraPair(left=cameras[0], right=cameras[1])
