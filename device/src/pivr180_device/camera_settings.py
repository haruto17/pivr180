import threading
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from pivr180_device.camera.base import Controls
from pivr180_device.slot import CameraSlot

SETTINGS_PATH = "/api/settings"

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


def settings_router(slot: CameraSlot) -> APIRouter:
    router = APIRouter()
    applying = threading.Lock()
    current = DEFAULT_SETTINGS

    @router.get(SETTINGS_PATH)
    def get_settings() -> CameraSettings:
        return current

    @router.put(SETTINGS_PATH)
    def put_settings(settings: CameraSettings) -> CameraSettings:
        nonlocal current
        with applying, slot.borrow() as cameras:
            if cameras is None:
                raise HTTPException(status_code=503, detail="cameras are not ready")
            cameras.exposure.apply_controls(settings.to_controls())
            current = settings
        return settings

    return router
