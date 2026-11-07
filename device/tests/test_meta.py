import json

import pytest

from pivr180_device import __version__
from pivr180_device.camera import CameraPair, FrameMetadata
from pivr180_device.camera.fake import FakeCamera, FakeFrame
from pivr180_device.meta import build_meta
from pivr180_device.sync import SyncedPair

LEFT_ID = "/base/axi/pcie@1000120000/rp1/i2c@88000/imx477@1a"
RIGHT_ID = "/base/axi/pcie@1000120000/rp1/i2c@80000/imx477@1a"


def make_cameras() -> CameraPair:
    return CameraPair(left=FakeCamera(LEFT_ID), right=FakeCamera(RIGHT_ID))


def make_frame(
    timestamp_ns: int,
    exposure_time_us: int = 8_000,
    analogue_gain: float = 1.5,
    colour_gains: tuple[float, float] = (2.1, 1.8),
) -> FakeFrame:
    return FakeFrame(
        FrameMetadata(
            sensor_timestamp_ns=timestamp_ns,
            exposure_time_us=exposure_time_us,
            analogue_gain=analogue_gain,
            colour_gains=colour_gains,
        )
    )


def synced_pair() -> SyncedPair:
    return SyncedPair(
        left=make_frame(123_456_789_012_345),
        right=make_frame(123_456_789_262_345),
        attempts=1,
        warning=False,
    )


def warning_pair() -> SyncedPair:
    return SyncedPair(
        left=make_frame(223_456_789_012_345),
        right=make_frame(223_456_787_512_345),
        attempts=3,
        warning=True,
    )


@pytest.mark.parametrize(
    "pair", [synced_pair(), warning_pair()], ids=["synced", "warning"]
)
def test_meta_conforms_to_schema(meta_validator, pair):
    meta = build_meta(make_cameras(), pair)

    meta_validator.validate(json.loads(json.dumps(meta)))


def test_meta_records_versions():
    meta = build_meta(make_cameras(), synced_pair())

    assert meta["schema_version"] == 1
    assert meta["software_version"] == __version__


def test_meta_records_each_camera_and_its_saved_frame_timestamp():
    cameras = CameraPair(
        left=FakeCamera(LEFT_ID, model="imx477"),
        right=FakeCamera(RIGHT_ID, model="imx477"),
    )

    meta = build_meta(cameras, synced_pair())

    assert meta["cameras"] == {
        "left": {
            "camera_id": LEFT_ID,
            "model": "imx477",
            "sensor_timestamp_ns": 123_456_789_012_345,
        },
        "right": {
            "camera_id": RIGHT_ID,
            "model": "imx477",
            "sensor_timestamp_ns": 123_456_789_262_345,
        },
    }


def test_meta_records_synced_result():
    meta = build_meta(make_cameras(), synced_pair())

    assert meta["sync"] == {
        "timestamp_diff_ns": 250_000,
        "attempts": 1,
        "warning": False,
    }


def test_meta_records_sync_warning():
    meta = build_meta(make_cameras(), warning_pair())

    assert meta["sync"] == {
        "timestamp_diff_ns": 1_500_000,
        "attempts": 3,
        "warning": True,
    }


def test_meta_records_locked_exposure_from_saved_left_frame():
    pair = SyncedPair(
        left=make_frame(
            0, exposure_time_us=33_000, analogue_gain=4.0, colour_gains=(1.9, 2.2)
        ),
        right=make_frame(
            0, exposure_time_us=1, analogue_gain=1.0, colour_gains=(1.0, 1.0)
        ),
        attempts=1,
        warning=False,
    )

    meta = build_meta(make_cameras(), pair)

    assert meta["exposure"] == {
        "exposure_time_us": 33_000,
        "analogue_gain": 4.0,
        "colour_gains": [1.9, 2.2],
    }
