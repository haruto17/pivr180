from typing import Any

from pivr180_device import __version__
from pivr180_device.camera.base import Camera, CameraPair, Frame
from pivr180_device.sync import SyncedPair

SCHEMA_VERSION = 1


def build_meta(cameras: CameraPair, synced: SyncedPair) -> dict[str, Any]:
    # Exposure/WB is locked identically on both cameras (ADR 0003), so the left
    # frame alone is recorded instead of reconciling two copies of the same values.
    exposure = synced.left.metadata
    return {
        "schema_version": SCHEMA_VERSION,
        "software_version": __version__,
        "cameras": {
            "left": _camera_meta(cameras.left, synced.left),
            "right": _camera_meta(cameras.right, synced.right),
        },
        "sync": {
            "timestamp_diff_ns": synced.timestamp_diff_ns,
            "attempts": synced.attempts,
            "warning": synced.warning,
        },
        "exposure": {
            "exposure_time_us": exposure.exposure_time_us,
            "analogue_gain": exposure.analogue_gain,
            "colour_gains": list(exposure.colour_gains),
        },
    }


def _camera_meta(camera: Camera, frame: Frame) -> dict[str, Any]:
    return {
        "camera_id": camera.camera_id,
        "model": camera.model,
        "sensor_timestamp_ns": frame.metadata.sensor_timestamp_ns,
    }
