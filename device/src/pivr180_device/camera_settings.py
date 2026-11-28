import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pivr180_device.camera.base import Controls
from pivr180_device.slot import CameraSlot

logger = logging.getLogger(__name__)

SETTINGS_PATH = "/api/settings"
DEFAULT_SETTINGS_FILE = Path("/var/lib/pivr180/camera_settings.json")

WhiteBalance = Literal[
    "auto",
    "incandescent",
    "tungsten",
    "fluorescent",
    "indoor",
    "daylight",
    "cloudy",
]

# Not libcamera.controls.AwbModeEnum: libcamera is installed only on the Pi, and
# these are the values its control_ids_core.yaml assigns to AwbMode.
AWB_MODES: dict[WhiteBalance, int] = {
    "auto": 0,
    "incandescent": 1,
    "tungsten": 2,
    "fluorescent": 3,
    "indoor": 4,
    "daylight": 5,
    "cloudy": 6,
}


class CameraSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    exposure_value: float = Field(ge=-2.0, le=2.0)
    white_balance: WhiteBalance
    contrast: float = Field(ge=0.0, le=2.0)

    def to_controls(self) -> Controls:
        return Controls(
            ExposureValue=self.exposure_value,
            AwbMode=AWB_MODES[self.white_balance],
            Contrast=self.contrast,
        )


DEFAULT_SETTINGS = CameraSettings(
    exposure_value=0.0, white_balance="auto", contrast=1.0
)


class CamerasNotReadyError(RuntimeError):
    pass


class SettingsFile:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> CameraSettings:
        try:
            data = self._path.read_bytes()
        except FileNotFoundError:
            logger.info("no saved camera settings at %s; using defaults", self._path)
            return DEFAULT_SETTINGS
        except OSError:
            logger.warning(
                "cannot read camera settings at %s; using defaults",
                self._path,
                exc_info=True,
            )
            return DEFAULT_SETTINGS
        try:
            settings = CameraSettings.model_validate_json(data)
        except ValidationError as error:
            logger.warning(
                "invalid camera settings at %s; using defaults: %s", self._path, error
            )
            return DEFAULT_SETTINGS
        logger.info("loaded camera settings from %s", self._path)
        return settings

    def save(self, settings: CameraSettings) -> None:
        descriptor, temporary = tempfile.mkstemp(
            dir=self._path.parent, prefix=f".{self._path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(settings.model_dump_json())
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self._path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        _fsync_directory(self._path.parent)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class CameraSettingsControl:
    def __init__(self, slot: CameraSlot, file: SettingsFile | None = None) -> None:
        self._slot = slot
        self._file = file
        self._applying = threading.Lock()
        self._current = DEFAULT_SETTINGS if file is None else file.load()

    @property
    def current(self) -> CameraSettings:
        return self._current

    def apply(self, settings: CameraSettings) -> CameraSettings:
        with self._applying:
            with self._slot.borrow() as cameras:
                if cameras is None:
                    raise CamerasNotReadyError("cameras are not ready")
                cameras.exposure.apply_controls(settings.to_controls())
                changed = settings != self._current
                self._current = settings
            if changed:
                self._save(settings)
        return settings

    def restore(self) -> None:
        with self._applying:
            settings = self._current
            # Not applied when default: the cameras open with these values, and
            # applying would only skip settle frames before the first shot.
            if settings == DEFAULT_SETTINGS:
                return
            with self._slot.borrow() as cameras:
                if cameras is None:
                    raise CamerasNotReadyError("cameras are not ready")
                cameras.exposure.apply_controls(settings.to_controls())
        logger.info("restored camera settings %s", settings.model_dump())

    def _save(self, settings: CameraSettings) -> None:
        if self._file is None:
            return
        try:
            self._file.save(settings)
        except OSError:
            # Not raised: the settings are already on the cameras, and failing
            # the request would make the app treat values in effect as rejected.
            logger.exception(
                "failed to save camera settings to %s; they stay applied but "
                "will not survive a restart",
                self._file.path,
            )


def settings_router(control: CameraSettingsControl) -> APIRouter:
    router = APIRouter()

    @router.get(SETTINGS_PATH)
    def get_settings() -> CameraSettings:
        return control.current

    @router.put(SETTINGS_PATH)
    def put_settings(settings: CameraSettings) -> CameraSettings:
        try:
            return control.apply(settings)
        except CamerasNotReadyError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    return router
