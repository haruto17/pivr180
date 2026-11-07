import math
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from pivr180_device.camera.base import CameraPair, Controls, FrameMetadata


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


class ExposureSync:
    def __init__(self, pair: CameraPair) -> None:
        self._pair = pair
        self._mutex = threading.Lock()
        self._locked_settings: ExposureSettings | None = None

    @property
    def locked_settings(self) -> ExposureSettings | None:
        with self._mutex:
            return self._locked_settings

    def resume_preview(self) -> None:
        with self._mutex:
            self._pair.right.set_controls(Controls(AeEnable=False, AwbEnable=False))
            self._pair.left.set_controls(Controls(AeEnable=True, AwbEnable=True))
            self._locked_settings = None

    def sync_once(self) -> ExposureSettings | None:
        with self._mutex:
            if self._locked_settings is not None:
                return None
            settings = self._read_left()
            self._pair.right.set_controls(settings.to_manual_controls())
            return settings

    def lock(self) -> ExposureSettings:
        settings, _ = self._lock()
        return settings

    @contextmanager
    def locked(self) -> Iterator[ExposureSettings]:
        settings, newly_locked = self._lock()
        try:
            yield settings
        finally:
            if newly_locked:
                self.resume_preview()

    def _lock(self) -> tuple[ExposureSettings, bool]:
        with self._mutex:
            if self._locked_settings is not None:
                return self._locked_settings, False
            settings = self._read_left()
            controls = settings.to_manual_controls()
            # Not left first: a failure on right would leave left locked while
            # still reporting unlocked; right-first failures leave a valid preview.
            self._pair.right.set_controls(controls)
            self._pair.left.set_controls(controls)
            self._locked_settings = settings
            return settings, True

    def _read_left(self) -> ExposureSettings:
        return ExposureSettings.from_metadata(self._pair.left.capture_metadata())
