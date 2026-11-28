import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import EXAMPLES_DIR, load_json
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

AOA_EXAMPLES_DIR = EXAMPLES_DIR / "aoa"
DIRECTIONS = {
    "app_to_device": "app_message",
    "device_to_app": "device_message",
}
Mutation = Callable[[dict[str, Any]], None]


def aoa_examples(direction: str) -> list[Path]:
    return sorted((AOA_EXAMPLES_DIR / direction).glob("*.json"))


ALL_EXAMPLES = [
    pytest.param(direction, path, id=f"{direction}/{path.stem}")
    for direction in DIRECTIONS
    for path in aoa_examples(direction)
]


def message_validator(
    aoa_schema: dict[str, Any], definition: str
) -> Draft202012Validator:
    registry = Registry().with_resource(
        aoa_schema["$id"], Resource.from_contents(aoa_schema)
    )
    return Draft202012Validator(
        {"$ref": f"{aoa_schema['$id']}#/$defs/{definition}"}, registry=registry
    )


def message_types(aoa_schema: dict[str, Any], definition: str) -> set[str]:
    refs = [entry["$ref"] for entry in aoa_schema["$defs"][definition]["oneOf"]]
    return {ref.removeprefix("#/$defs/") for ref in refs}


def example(direction: str, name: str) -> dict[str, Any]:
    return load_json(AOA_EXAMPLES_DIR / direction / f"{name}.json")


def test_schema_is_valid_draft_2020_12(aoa_schema: dict[str, Any]) -> None:
    Draft202012Validator.check_schema(aoa_schema)
    assert aoa_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert aoa_schema["$id"]


def test_message_type_matches_definition_name(aoa_schema: dict[str, Any]) -> None:
    for direction in DIRECTIONS.values():
        for name in message_types(aoa_schema, direction):
            assert aoa_schema["$defs"][name]["properties"]["type"] == {"const": name}


@pytest.mark.parametrize(("direction", "definition"), DIRECTIONS.items())
def test_every_message_type_has_an_example(
    aoa_schema: dict[str, Any], direction: str, definition: str
) -> None:
    types = {load_json(path)["type"] for path in aoa_examples(direction)}
    assert types == message_types(aoa_schema, definition)


@pytest.mark.parametrize(("direction", "path"), ALL_EXAMPLES)
def test_example_name_starts_with_its_type(direction: str, path: Path) -> None:
    message_type = load_json(path)["type"]
    assert path.stem == message_type or path.stem.startswith(f"{message_type}_")


@pytest.mark.parametrize(("direction", "path"), ALL_EXAMPLES)
def test_examples_pass_for_their_direction(
    aoa_schema: dict[str, Any],
    aoa_validator: Draft202012Validator,
    direction: str,
    path: Path,
) -> None:
    message = load_json(path)
    message_validator(aoa_schema, DIRECTIONS[direction]).validate(message)
    aoa_validator.validate(message)


@pytest.mark.parametrize(("direction", "path"), ALL_EXAMPLES)
def test_examples_fail_for_the_other_direction(
    aoa_schema: dict[str, Any], direction: str, path: Path
) -> None:
    (other,) = set(DIRECTIONS.values()) - {DIRECTIONS[direction]}
    assert not message_validator(aoa_schema, other).is_valid(load_json(path))


def _delete(*keys: Any) -> Mutation:
    def mutate(message: dict[str, Any]) -> None:
        target = message
        for key in keys[:-1]:
            target = target[key]
        del target[keys[-1]]

    return mutate


def _set(value: Any, *keys: Any) -> Mutation:
    def mutate(message: dict[str, Any]) -> None:
        target = message
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = copy.deepcopy(value)

    return mutate


APP = "app_to_device"
DEVICE = "device_to_app"

VALID_VARIANTS = [
    pytest.param(APP, "shutter", _set(0, "id"), id="zero_id"),
    pytest.param(APP, "shutter", _set(2_147_483_647, "id"), id="max_id"),
    pytest.param(
        APP, "hello", _set(3, "protocol_version"), id="hello_newer_protocol_version"
    ),
    pytest.param(
        APP, "set_settings", _set(-2, "settings", "exposure_value"), id="min_ev"
    ),
    pytest.param(
        APP, "set_settings", _set(2, "settings", "exposure_value"), id="max_ev"
    ),
    pytest.param(
        APP, "set_settings", _set(0, "settings", "contrast"), id="min_contrast"
    ),
    pytest.param(
        APP, "set_settings", _set(2, "settings", "contrast"), id="max_contrast"
    ),
    pytest.param(
        APP, "set_settings", _set("auto", "settings", "white_balance"), id="awb_auto"
    ),
    pytest.param(APP, "get_thumbnail", _set("right", "side"), id="thumbnail_right"),
    pytest.param(DEVICE, "status_idle", _set(0, "free_bytes"), id="no_free_space"),
    pytest.param(
        DEVICE,
        "status_idle",
        _set(True, "last_capture", "sync_warning"),
        id="last_capture_sync_warning",
    ),
]


@pytest.mark.parametrize(("direction", "name", "mutate"), VALID_VARIANTS)
def test_valid_variants_pass(
    aoa_validator: Draft202012Validator,
    direction: str,
    name: str,
    mutate: Mutation,
) -> None:
    message = example(direction, name)
    mutate(message)
    aoa_validator.validate(message)


INVALID_CASES = [
    pytest.param(APP, "shutter", _delete("type"), id="missing_type"),
    pytest.param(APP, "shutter", _set("shoot", "type"), id="unknown_type"),
    pytest.param(APP, "shutter", _delete("id"), id="request_missing_id"),
    pytest.param(APP, "shutter", _set(-1, "id"), id="negative_id"),
    pytest.param(APP, "shutter", _set(2_147_483_648, "id"), id="id_above_int_max"),
    pytest.param(APP, "shutter", _set(1.5, "id"), id="non_integer_id"),
    pytest.param(APP, "shutter", _set("2", "id"), id="string_id"),
    pytest.param(APP, "shutter", _set(1, "count"), id="extra_request_property"),
    pytest.param(
        APP, "hello", _delete("protocol_version"), id="hello_missing_protocol_version"
    ),
    pytest.param(APP, "hello", _set(0, "protocol_version"), id="protocol_version_0"),
    pytest.param(
        APP, "hello", _set("1", "protocol_version"), id="string_protocol_version"
    ),
    pytest.param(APP, "hello", _delete("app_version"), id="hello_missing_app_version"),
    pytest.param(APP, "hello", _set("", "app_version"), id="empty_app_version"),
    pytest.param(APP, "set_settings", _delete("settings"), id="missing_settings"),
    pytest.param(
        APP,
        "set_settings",
        _delete("settings", "exposure_value"),
        id="missing_exposure_value",
    ),
    pytest.param(
        APP,
        "set_settings",
        _delete("settings", "white_balance"),
        id="missing_white_balance",
    ),
    pytest.param(
        APP, "set_settings", _delete("settings", "contrast"), id="missing_contrast"
    ),
    pytest.param(
        APP, "set_settings", _set(-2.1, "settings", "exposure_value"), id="ev_below_min"
    ),
    pytest.param(
        APP, "set_settings", _set(2.1, "settings", "exposure_value"), id="ev_above_max"
    ),
    pytest.param(
        APP, "set_settings", _set(-0.1, "settings", "contrast"), id="contrast_below_0"
    ),
    pytest.param(
        APP, "set_settings", _set(2.1, "settings", "contrast"), id="contrast_above_max"
    ),
    pytest.param(
        APP,
        "set_settings",
        _set("sunny", "settings", "white_balance"),
        id="unknown_white_balance",
    ),
    pytest.param(
        APP, "set_settings", _set(5, "settings", "white_balance"), id="numeric_awb_mode"
    ),
    pytest.param(
        APP,
        "set_settings",
        _set(8000, "settings", "exposure_time_us"),
        id="extra_settings_property",
    ),
    pytest.param(APP, "set_mode", _set("video", "mode"), id="video_mode"),
    pytest.param(APP, "set_mode", _delete("mode"), id="set_mode_missing_mode"),
    pytest.param(
        APP, "get_thumbnail", _delete("capture_id"), id="thumbnail_missing_capture_id"
    ),
    pytest.param(
        APP,
        "get_thumbnail",
        _set("../20261126-031522-000", "capture_id"),
        id="capture_id_with_path",
    ),
    pytest.param(
        APP,
        "get_thumbnail",
        _set("20261126-031522", "capture_id"),
        id="capture_id_without_sequence",
    ),
    pytest.param(APP, "get_thumbnail", _delete("side"), id="thumbnail_missing_side"),
    pytest.param(APP, "get_thumbnail", _set("both", "side"), id="unknown_side"),
    pytest.param(
        APP, "delete_capture", _delete("capture_id"), id="delete_missing_capture_id"
    ),
    pytest.param(APP, "stop_preview", _delete("id"), id="stop_preview_missing_id"),
    pytest.param(APP, "stop_preview", _set(5, "fps"), id="stop_preview_extra_property"),
    pytest.param(APP, "start_preview", _delete("id"), id="start_preview_missing_id"),
    pytest.param(
        APP, "start_preview", _set(5, "max_fps"), id="start_preview_extra_property"
    ),
    pytest.param(
        DEVICE,
        "welcome",
        _delete("software_version"),
        id="welcome_missing_software_version",
    ),
    pytest.param(
        DEVICE, "welcome", _set(0, "protocol_version"), id="welcome_protocol_version_0"
    ),
    pytest.param(DEVICE, "ok", _delete("id"), id="ok_missing_id"),
    pytest.param(DEVICE, "settings", _delete("settings"), id="settings_missing_body"),
    pytest.param(
        DEVICE, "settings", _set(3, "settings", "exposure_value"), id="settings_ev_3"
    ),
    pytest.param(DEVICE, "mode", _set("video", "mode"), id="mode_video"),
    pytest.param(DEVICE, "captures", _delete("captures"), id="missing_captures"),
    pytest.param(
        DEVICE, "captures", _delete("captures", 0, "id"), id="capture_missing_id"
    ),
    pytest.param(
        DEVICE,
        "captures",
        _delete("captures", 0, "complete"),
        id="capture_missing_complete",
    ),
    pytest.param(
        DEVICE,
        "captures",
        _delete("captures", 0, "sync_warning"),
        id="capture_missing_sync_warning",
    ),
    pytest.param(
        DEVICE,
        "captures",
        _set("bad", "captures", 0, "id"),
        id="capture_invalid_id",
    ),
    pytest.param(
        DEVICE,
        "captures",
        _set(1, "captures", 0, "size_bytes"),
        id="extra_capture_property",
    ),
    pytest.param(DEVICE, "status_idle", _set(1, "id"), id="status_with_id"),
    pytest.param(DEVICE, "status_idle", _delete("state"), id="missing_state"),
    pytest.param(DEVICE, "status_idle", _set("busy", "state"), id="unknown_state"),
    pytest.param(
        DEVICE,
        "status_idle",
        _set("disk full", "error_message"),
        id="error_message_while_idle",
    ),
    pytest.param(
        DEVICE,
        "status_capturing",
        _set("disk full", "error_message"),
        id="error_message_while_capturing",
    ),
    pytest.param(
        DEVICE, "status_error", _delete("error_message"), id="error_without_message"
    ),
    pytest.param(
        DEVICE, "status_error", _set("", "error_message"), id="empty_error_message"
    ),
    pytest.param(
        DEVICE, "status_idle", _delete("capture_count"), id="missing_capture_count"
    ),
    pytest.param(
        DEVICE, "status_idle", _set(-1, "capture_count"), id="negative_capture_count"
    ),
    pytest.param(DEVICE, "status_idle", _delete("free_bytes"), id="missing_free_bytes"),
    pytest.param(
        DEVICE, "status_idle", _set(-1, "free_bytes"), id="negative_free_bytes"
    ),
    pytest.param(
        DEVICE,
        "status_idle",
        _set(1_500_000_000.5, "free_bytes"),
        id="non_integer_free_bytes",
    ),
    pytest.param(
        DEVICE, "status_idle", _delete("last_capture"), id="missing_last_capture"
    ),
    pytest.param(
        DEVICE,
        "status_idle",
        _delete("last_capture", "id"),
        id="last_capture_missing_id",
    ),
    pytest.param(
        DEVICE,
        "status_idle",
        _delete("last_capture", "sync_warning"),
        id="last_capture_missing_sync_warning",
    ),
    pytest.param(
        DEVICE,
        "status_idle",
        _set(None, "last_capture", "sync_warning"),
        id="last_capture_null_sync_warning",
    ),
    pytest.param(
        DEVICE,
        "status_idle",
        _set("20261126-031522-000", "last_capture"),
        id="last_capture_as_string",
    ),
    pytest.param(DEVICE, "status_idle", _set(1, "battery"), id="extra_status_property"),
    pytest.param(DEVICE, "error", _delete("code"), id="error_missing_code"),
    pytest.param(DEVICE, "error", _set("not_found", "code"), id="unknown_error_code"),
    pytest.param(DEVICE, "error", _delete("message"), id="error_missing_message"),
    pytest.param(DEVICE, "error", _set("", "message"), id="error_empty_message"),
    pytest.param(DEVICE, "error", _set(None, "id"), id="error_null_id"),
]


@pytest.mark.parametrize(("direction", "name", "mutate"), INVALID_CASES)
def test_invalid_examples_fail(
    aoa_validator: Draft202012Validator,
    direction: str,
    name: str,
    mutate: Mutation,
) -> None:
    message = example(direction, name)
    mutate(message)
    assert not aoa_validator.is_valid(message)
