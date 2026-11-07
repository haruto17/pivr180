import logging
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Self, TypeVar

from pivr180_device.camera.base import Camera, CameraPair, Controls, FrameMetadata

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Not exact equality: the driver rounds ExposureTime to whole sensor lines and
# gains to register steps, so reported values can differ slightly from requests.
APPLIED_REL_TOL = 0.01
# Not checked from the first frame: frames already exposing or queued when
# set_controls is called keep the old settings, and libcamera's delayed controls
# apply ExposureTime/AnalogueGain to the sensor only a couple of frames later.
DEFAULT_SETTLE_FRAMES = 4
DEFAULT_STABLE_FRAMES = 3
DEFAULT_MAX_WAIT_FRAMES = 30


class ExposureNotAppliedError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExposureSettings:
    exposure_time_us: int
    analogue_gain: float
    colour_gains: tuple[float, float]

    def __post_init__(self) -> None:
        if self.exposure_time_us <= 0:
            raise ValueError(
                f"exposure_time_us must be positive, got {self.exposure_time_us}"
            )
        if not (math.isfinite(self.analogue_gain) and self.analogue_gain > 0):
            raise ValueError(
                f"analogue_gain must be positive and finite, got {self.analogue_gain}"
            )
        if len(self.colour_gains) != 2 or not all(
            math.isfinite(gain) and gain > 0 for gain in self.colour_gains
        ):
            raise ValueError(
                "colour_gains must be two positive finite values, "
                f"got {self.colour_gains}"
            )

    @classmethod
    def from_metadata(cls, metadata: FrameMetadata) -> "ExposureSettings":
        return cls(
            exposure_time_us=metadata.exposure_time_us,
            analogue_gain=metadata.analogue_gain,
            colour_gains=metadata.colour_gains,
        )

    def to_manual_controls(self) -> Controls:
        return Controls(
            AeEnable=False,
            AwbEnable=False,
            ExposureTime=self.exposure_time_us,
            AnalogueGain=self.analogue_gain,
            ColourGains=self.colour_gains,
        )

    def is_applied_to(self, metadata: FrameMetadata) -> bool:
        expected = (self.exposure_time_us, self.analogue_gain, *self.colour_gains)
        actual = (
            metadata.exposure_time_us,
            metadata.analogue_gain,
            *metadata.colour_gains,
        )
        return len(actual) == len(expected) and all(
            math.isclose(a, e, rel_tol=APPLIED_REL_TOL)
            for a, e in zip(actual, expected, strict=True)
        )


class ExposureSync:
    def __init__(
        self,
        pair: CameraPair,
        settle_frames: int = DEFAULT_SETTLE_FRAMES,
        stable_frames: int = DEFAULT_STABLE_FRAMES,
        max_wait_frames: int = DEFAULT_MAX_WAIT_FRAMES,
    ) -> None:
        if settle_frames < 0:
            raise ValueError(f"settle_frames must not be negative, got {settle_frames}")
        if stable_frames < 1:
            raise ValueError(f"stable_frames must be at least 1, got {stable_frames}")
        if max_wait_frames < stable_frames:
            raise ValueError(
                f"max_wait_frames must be at least stable_frames ({stable_frames}), "
                f"got {max_wait_frames}"
            )
        self._pair = pair
        self._settle_frames = settle_frames
        self._stable_frames = stable_frames
        self._max_wait_frames = max_wait_frames
        self._mutex = threading.Lock()
        self._shutter = threading.Lock()
        self._locked_settings: ExposureSettings | None = None

    @property
    def locked_settings(self) -> ExposureSettings | None:
        with self._mutex:
            return self._locked_settings

    def resume_preview(self) -> None:
        with self._shutter:
            self._resume_preview()

    def sync_once(self) -> ExposureSettings | None:
        with self._mutex:
            if self._locked_settings is not None:
                return None
            settings = self._read_left()
            self._pair.right.set_controls(settings.to_manual_controls())
            return settings

    def shoot(self, capture: Callable[[ExposureSettings], T]) -> T:
        with self._shutter:
            settings = self._lock()
            try:
                self._wait_until_applied(self._pair.left, settings)
                self._wait_until_applied(self._pair.right, settings)
                return capture(settings)
            finally:
                self._resume_preview()

    def _resume_preview(self) -> None:
        with self._mutex:
            self._pair.right.set_controls(Controls(AeEnable=False, AwbEnable=False))
            self._pair.left.set_controls(Controls(AeEnable=True, AwbEnable=True))
            self._locked_settings = None

    def _lock(self) -> ExposureSettings:
        with self._mutex:
            settings = self._read_left()
            controls = settings.to_manual_controls()
            # Not left first: a failure on right would leave left locked while
            # still reporting unlocked; right-first failures leave a valid preview.
            self._pair.right.set_controls(controls)
            self._pair.left.set_controls(controls)
            self._locked_settings = settings
            return settings

    def _wait_until_applied(self, camera: Camera, settings: ExposureSettings) -> None:
        for _ in range(self._settle_frames):
            camera.capture_metadata()
        last: FrameMetadata | None = None
        consecutive = 0
        for _ in range(self._max_wait_frames):
            last = camera.capture_metadata()
            # Not a single match: a frame still under AE/AWB can coincide with the
            # locked values and be followed by frames where AE/AWB moves them again.
            consecutive = consecutive + 1 if settings.is_applied_to(last) else 0
            if consecutive >= self._stable_frames:
                return
        raise ExposureNotAppliedError(
            f"camera {camera.camera_id} did not report {settings} on "
            f"{self._stable_frames} consecutive frames within "
            f"{self._max_wait_frames} frames after skipping {self._settle_frames}; "
            f"last metadata: {last}"
        )

    def _read_left(self) -> ExposureSettings:
        return ExposureSettings.from_metadata(self._pair.left.capture_metadata())


class ExposurePreview:
    def __init__(self, sync: ExposureSync, paused_poll_s: float = 0.01) -> None:
        self._sync = sync
        self._paused_poll_s = paused_poll_s
        self._state = threading.Lock()
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None

    @property
    def running(self) -> bool:
        with self._state:
            return self._thread is not None and self._thread.is_alive()

    @property
    def error(self) -> BaseException | None:
        with self._state:
            return self._error

    def start(self) -> None:
        with self._state:
            if self._thread is not None:
                raise RuntimeError(
                    "exposure preview is already started or still stopping"
                )
            self._sync.resume_preview()
            stop = threading.Event()
            self._stop = stop
            self._error = None
            self._thread = threading.Thread(
                target=self._run, args=(stop,), name="exposure-preview", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        with self._state:
            thread = self._thread
            if thread is None or self._stop is None:
                return
            self._stop.set()
        thread.join()
        with self._state:
            if self._thread is not thread:
                return
            self._thread = None
            self._stop = None
            error = self._error
            self._error = None
        if error is not None:
            raise RuntimeError("exposure preview stopped on error") from error

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    def _run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                synced = self._sync.sync_once()
            except Exception as error:
                logger.exception("exposure preview sync failed; stopping preview")
                with self._state:
                    self._error = error
                return
            if synced is None:
                stop.wait(self._paused_poll_s)
