from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict


@dataclass(frozen=True)
class FrameMetadata:
    sensor_timestamp_ns: int
    exposure_time_us: int
    analogue_gain: float
    colour_gains: tuple[float, float]


class Controls(TypedDict, total=False):
    ExposureTime: int
    AnalogueGain: float
    ColourGains: tuple[float, float]
    AeEnable: bool
    AwbEnable: bool


class Frame(Protocol):
    @property
    def metadata(self) -> FrameMetadata: ...

    def save(self, path: Path, quality: int) -> None: ...


class Camera(Protocol):
    @property
    def camera_id(self) -> str: ...

    @property
    def model(self) -> str: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def set_controls(self, controls: Controls) -> None: ...

    def capture_metadata(self) -> FrameMetadata: ...

    def capture_frame(self) -> Frame: ...


@dataclass(frozen=True)
class CameraPair:
    left: Camera
    right: Camera

    def start(self) -> None:
        self.left.start()
        try:
            self.right.start()
        except BaseException:
            self.left.stop()
            raise

    def stop(self) -> None:
        try:
            self.left.stop()
        finally:
            self.right.stop()
