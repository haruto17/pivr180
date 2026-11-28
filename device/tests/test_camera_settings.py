import threading
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pivr180_device.camera import CameraPair, FrameMetadata
from pivr180_device.camera.fake import FakeCamera, FakeFrame
from pivr180_device.camera_settings import (
    SETTINGS_PATH,
    CameraSettings,
    CameraSettingsControl,
    settings_router,
)
from pivr180_device.exposure import ExposureSettings, ExposureSync
from pivr180_device.slot import CameraSlot, LiveCameras
from pivr180_device.web import create_app

DEFAULTS = {"exposure_value": 0.0, "white_balance": "auto", "contrast": 1.0}
CHANGED = {"exposure_value": -1.5, "white_balance": "daylight", "contrast": 1.2}
CHANGED_CONTROLS = {"ExposureValue": -1.5, "AwbMode": 5, "Contrast": 1.2}


def make_frame() -> FakeFrame:
    return FakeFrame(
        FrameMetadata(
            sensor_timestamp_ns=0,
            exposure_time_us=10_000,
            analogue_gain=1.0,
            colour_gains=(2.0, 1.5),
        )
    )


def live_cameras() -> tuple[LiveCameras, FakeCamera, FakeCamera]:
    left = FakeCamera("left", frames=[make_frame(), make_frame()])
    right = FakeCamera("right", frames=[make_frame()])
    pair = CameraPair(left=left, right=right)
    pair.start()
    exposure = ExposureSync(pair, settle_frames=0, stable_frames=1)
    return LiveCameras(pair=pair, exposure=exposure), left, right


@pytest.fixture
def slot() -> CameraSlot:
    return CameraSlot()


@pytest.fixture
def client(slot: CameraSlot) -> TestClient:
    return TestClient(create_app([settings_router(CameraSettingsControl(slot))]))


@pytest.fixture
def attached(slot: CameraSlot) -> Iterator[tuple[LiveCameras, FakeCamera, FakeCamera]]:
    cameras = live_cameras()
    with slot.attach(cameras[0]):
        yield cameras


@pytest.mark.parametrize(
    ("white_balance", "awb_mode"),
    [
        ("auto", 0),
        ("incandescent", 1),
        ("tungsten", 2),
        ("fluorescent", 3),
        ("indoor", 4),
        ("daylight", 5),
        ("cloudy", 6),
    ],
)
def test_settings_convert_to_libcamera_controls(white_balance: str, awb_mode: int):
    settings = CameraSettings.model_validate(
        {"exposure_value": 0.5, "white_balance": white_balance, "contrast": 1.5}
    )

    assert settings.to_controls() == {
        "ExposureValue": 0.5,
        "AwbMode": awb_mode,
        "Contrast": 1.5,
    }


def test_get_returns_the_defaults_before_any_change(client: TestClient):
    response = client.get(SETTINGS_PATH)

    assert response.status_code == 200
    assert response.json() == DEFAULTS


def test_put_applies_the_settings_to_both_cameras(
    client: TestClient, attached: tuple[LiveCameras, FakeCamera, FakeCamera]
):
    _, left, right = attached

    response = client.put(SETTINGS_PATH, json=CHANGED)

    assert response.status_code == 200
    assert response.json() == CHANGED
    assert left.controls == CHANGED_CONTROLS
    assert right.controls == CHANGED_CONTROLS


def test_get_returns_the_settings_last_put(
    client: TestClient, attached: tuple[LiveCameras, FakeCamera, FakeCamera]
):
    client.put(SETTINGS_PATH, json=CHANGED)

    assert client.get(SETTINGS_PATH).json() == CHANGED


@pytest.mark.parametrize(
    "body",
    [
        {**CHANGED, "exposure_value": -2.1},
        {**CHANGED, "exposure_value": 2.1},
        {**CHANGED, "exposure_value": "bright"},
        {**CHANGED, "white_balance": "custom"},
        {**CHANGED, "contrast": -0.1},
        {**CHANGED, "contrast": 2.1},
        {"exposure_value": -1.5, "white_balance": "daylight"},
        {**CHANGED, "saturation": 1.0},
    ],
)
def test_put_rejects_invalid_settings_without_applying_them(
    client: TestClient,
    attached: tuple[LiveCameras, FakeCamera, FakeCamera],
    body: dict[str, Any],
):
    _, left, right = attached

    response = client.put(SETTINGS_PATH, json=body)

    assert response.status_code == 422
    assert left.controls_history == []
    assert right.controls_history == []
    assert client.get(SETTINGS_PATH).json() == DEFAULTS


@pytest.mark.parametrize("value", [-2.0, 2.0])
def test_put_accepts_the_exposure_value_limits(
    client: TestClient,
    attached: tuple[LiveCameras, FakeCamera, FakeCamera],
    value: float,
):
    response = client.put(SETTINGS_PATH, json={**CHANGED, "exposure_value": value})

    assert response.status_code == 200


@pytest.mark.parametrize("value", [0.0, 2.0])
def test_put_accepts_the_contrast_limits(
    client: TestClient,
    attached: tuple[LiveCameras, FakeCamera, FakeCamera],
    value: float,
):
    response = client.put(SETTINGS_PATH, json={**CHANGED, "contrast": value})

    assert response.status_code == 200


def test_put_is_unavailable_until_the_cameras_are_ready(client: TestClient):
    response = client.put(SETTINGS_PATH, json=CHANGED)

    assert response.status_code == 503
    assert client.get(SETTINGS_PATH).json() == DEFAULTS


def test_get_keeps_the_settings_after_the_cameras_are_detached(
    slot: CameraSlot, client: TestClient
):
    cameras, _, _ = live_cameras()
    with slot.attach(cameras):
        client.put(SETTINGS_PATH, json=CHANGED)

    assert client.put(SETTINGS_PATH, json=DEFAULTS).status_code == 503
    assert client.get(SETTINGS_PATH).json() == CHANGED


def test_put_during_a_shot_applies_after_the_shot(
    client: TestClient, attached: tuple[LiveCameras, FakeCamera, FakeCamera]
):
    cameras, left, right = attached
    entered = threading.Event()
    release = threading.Event()
    contrast_during_shot: list[float | None] = []

    def capture(settings: ExposureSettings) -> None:
        entered.set()
        release.wait(timeout=5)
        contrast_during_shot.append(left.controls.get("Contrast"))
        contrast_during_shot.append(right.controls.get("Contrast"))

    shooting = threading.Thread(target=cameras.exposure.shoot, args=(capture,))
    shooting.start()
    assert entered.wait(timeout=5)
    responses = []
    putting = threading.Thread(
        target=lambda: responses.append(client.put(SETTINGS_PATH, json=CHANGED))
    )
    putting.start()
    putting.join(timeout=0.2)
    still_putting = putting.is_alive()
    release.set()
    shooting.join(timeout=5)
    putting.join(timeout=5)

    assert still_putting
    assert contrast_during_shot == [None, None]
    assert [response.status_code for response in responses] == [200]
    assert left.controls["Contrast"] == 1.2
    assert right.controls["Contrast"] == 1.2
