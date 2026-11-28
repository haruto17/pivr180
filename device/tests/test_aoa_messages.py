import json
from pathlib import Path
from typing import Any

import pytest

from pivr180_device.aoa.messages import (
    REQUEST_FIELDS,
    InvalidRequestError,
    parse_request,
)
from pivr180_device.camera_settings import CameraSettings

AOA_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "schema" / "examples" / "aoa"
REQUEST_EXAMPLES = sorted((AOA_EXAMPLES_DIR / "app_to_device").glob("*.json"))


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def encode(message: Any) -> bytes:
    return json.dumps(message).encode("utf-8")


def test_every_request_in_the_examples_is_known():
    assert {load(path)["type"] for path in REQUEST_EXAMPLES} == set(REQUEST_FIELDS)


@pytest.mark.parametrize("path", REQUEST_EXAMPLES, ids=lambda path: path.stem)
def test_parses_every_request_example(path: Path):
    example = load(path)

    request = parse_request(path.read_bytes())

    assert request.type == example["type"]
    assert request.id == example["id"]
    assert set(request.fields) == set(example) - {"type", "id"}


def test_parses_settings_into_camera_settings():
    request = parse_request(
        (AOA_EXAMPLES_DIR / "app_to_device" / "set_settings.json").read_bytes()
    )

    assert request.fields["settings"] == CameraSettings(
        exposure_value=-0.5, white_balance="daylight", contrast=1.2
    )


@pytest.mark.parametrize("request_id", [0, 2**31 - 1])
def test_accepts_the_request_id_limits(request_id: int):
    assert parse_request(encode({"type": "shutter", "id": request_id})).id == request_id


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        pytest.param(b"{", "not valid JSON", id="broken_json"),
        pytest.param(b"\xff\xfe", "not valid JSON", id="not_utf8"),
        pytest.param(b"", "not valid JSON", id="empty"),
        pytest.param(b'{"type":"shutter","id":NaN}', "not valid JSON", id="nan"),
        pytest.param(b'["shutter", 1]', "not a JSON object", id="array"),
        pytest.param(encode({"type": "shutter"}), "no valid id", id="missing_id"),
        pytest.param(encode({"type": "shutter", "id": -1}), "no valid id", id="neg"),
        pytest.param(
            encode({"type": "shutter", "id": 2**31}), "no valid id", id="above_max"
        ),
        pytest.param(encode({"type": "shutter", "id": 1.5}), "no valid id", id="float"),
        pytest.param(encode({"type": "shutter", "id": "1"}), "no valid id", id="str"),
        pytest.param(encode({"type": "shutter", "id": True}), "no valid id", id="bool"),
    ],
)
def test_rejects_frames_without_a_readable_id(payload: bytes, reason: str):
    with pytest.raises(InvalidRequestError, match=reason) as raised:
        parse_request(payload)

    assert raised.value.request_id is None


SETTINGS = {"exposure_value": 0.0, "white_balance": "auto", "contrast": 1.0}


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        pytest.param({"id": 4}, "unknown request type None", id="missing_type"),
        pytest.param({"type": "shoot", "id": 4}, "unknown request type", id="unknown"),
        pytest.param({"type": "welcome", "id": 4}, "unknown request type", id="reply"),
        pytest.param(
            {"type": "shutter", "id": 4, "count": 2},
            "shutter does not take count",
            id="extra_field",
        ),
        pytest.param(
            {"type": "hello", "id": 4, "app_version": "0.1.0"},
            "hello needs protocol_version",
            id="hello_without_version",
        ),
        pytest.param(
            {"type": "hello", "id": 4, "protocol_version": 0, "app_version": "0.1.0"},
            "hello.protocol_version",
            id="protocol_version_0",
        ),
        pytest.param(
            {"type": "hello", "id": 4, "protocol_version": "2", "app_version": "0"},
            "hello.protocol_version",
            id="string_protocol_version",
        ),
        pytest.param(
            {"type": "hello", "id": 4, "protocol_version": 2, "app_version": ""},
            "hello.app_version",
            id="empty_app_version",
        ),
        pytest.param(
            {"type": "set_settings", "id": 4},
            "set_settings needs settings",
            id="missing_settings",
        ),
        pytest.param(
            {"type": "set_settings", "id": 4, "settings": "auto"},
            "set_settings.settings",
            id="settings_not_an_object",
        ),
        pytest.param(
            {"type": "set_settings", "id": 4, "settings": {**SETTINGS, "contrast": 3}},
            "contrast",
            id="contrast_above_max",
        ),
        pytest.param(
            {
                "type": "set_settings",
                "id": 4,
                "settings": {**SETTINGS, "exposure_value": "1"},
            },
            "exposure_value",
            id="string_exposure_value",
        ),
        pytest.param(
            {
                "type": "set_settings",
                "id": 4,
                "settings": {**SETTINGS, "white_balance": "sunny"},
            },
            "white_balance",
            id="unknown_white_balance",
        ),
        pytest.param(
            {"type": "set_settings", "id": 4, "settings": {**SETTINGS, "iso": 100}},
            "iso",
            id="extra_setting",
        ),
        pytest.param(
            {"type": "set_mode", "id": 4, "mode": "video"},
            "set_mode.mode",
            id="video_mode",
        ),
        pytest.param(
            {
                "type": "get_thumbnail",
                "id": 4,
                "capture_id": "../20261126-031522-000",
                "side": "left",
            },
            "get_thumbnail.capture_id",
            id="capture_id_with_path",
        ),
        pytest.param(
            {
                "type": "get_thumbnail",
                "id": 4,
                "capture_id": "20261126-031522-000",
                "side": ["left"],
            },
            "get_thumbnail.side",
            id="side_as_list",
        ),
        pytest.param(
            {"type": "delete_capture", "id": 4, "capture_id": 20261126},
            "delete_capture.capture_id",
            id="numeric_capture_id",
        ),
    ],
)
def test_rejects_invalid_requests_with_their_id(message: dict[str, Any], reason: str):
    with pytest.raises(InvalidRequestError, match=reason) as raised:
        parse_request(encode(message))

    assert raised.value.request_id == 4
