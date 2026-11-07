import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import EXAMPLES_DIR, example_paths, load_json
from jsonschema import Draft202012Validator

CORRECTION_EXAMPLES = example_paths("correction")
Mutation = Callable[[dict[str, Any]], None]


def device_default() -> dict[str, Any]:
    return load_json(EXAMPLES_DIR / "correction" / "device_default.json")


def capture_override() -> dict[str, Any]:
    return load_json(EXAMPLES_DIR / "correction" / "capture_override.json")


def test_schema_is_valid_draft_2020_12(correction_schema: dict[str, Any]) -> None:
    Draft202012Validator.check_schema(correction_schema)
    assert (
        correction_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    )
    assert correction_schema["$id"]


def test_correction_examples_cover_both_scopes() -> None:
    scopes = {load_json(path)["scope"] for path in CORRECTION_EXAMPLES}
    assert scopes == {"device_default", "capture_override"}


@pytest.mark.parametrize("path", CORRECTION_EXAMPLES, ids=lambda p: p.stem)
def test_valid_examples_pass(
    correction_validator: Draft202012Validator, path: Path
) -> None:
    correction_validator.validate(load_json(path))


def _delete(*keys: str) -> Mutation:
    def mutate(correction: dict[str, Any]) -> None:
        target = correction
        for key in keys[:-1]:
            target = target[key]
        del target[keys[-1]]

    return mutate


def _set(value: Any, *keys: str) -> Mutation:
    def mutate(correction: dict[str, Any]) -> None:
        target = correction
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = copy.deepcopy(value)

    return mutate


VALID_VARIANTS = [
    pytest.param(
        device_default, _set(0, "cameras", "left", "center_x_px"), id="zero_center_x"
    ),
    pytest.param(
        device_default, _set(0, "cameras", "right", "center_y_px"), id="zero_center_y"
    ),
    pytest.param(
        device_default, _set(180, "cameras", "left", "rotation_deg"), id="rotation_180"
    ),
    pytest.param(
        device_default,
        _set(-179.9, "cameras", "right", "rotation_deg"),
        id="rotation_just_above_minus_180",
    ),
    pytest.param(
        device_default, _set(0.001, "cameras", "left", "radius_px"), id="tiny_radius"
    ),
    pytest.param(
        capture_override, _delete("cameras", "right"), id="override_left_only"
    ),
]


@pytest.mark.parametrize(("base", "mutate"), VALID_VARIANTS)
def test_valid_variants_pass(
    correction_validator: Draft202012Validator,
    base: Callable[[], dict[str, Any]],
    mutate: Mutation,
) -> None:
    correction = base()
    mutate(correction)
    correction_validator.validate(correction)


def _for_each_scope(mutate: Mutation, case_id: str) -> list[Any]:
    return [
        pytest.param(device_default, mutate, id=f"{case_id}-device_default"),
        pytest.param(capture_override, mutate, id=f"{case_id}-capture_override"),
    ]


INVALID_CASES = [
    *_for_each_scope(_delete("schema_version"), "missing_schema_version"),
    *_for_each_scope(_set(2, "schema_version"), "unknown_schema_version"),
    *_for_each_scope(_delete("scope"), "missing_scope"),
    *_for_each_scope(_set("capture", "scope"), "unknown_scope"),
    *_for_each_scope(_delete("cameras"), "missing_cameras"),
    *_for_each_scope(_set({}, "cameras"), "empty_cameras"),
    *_for_each_scope(_set({}, "cameras", "center"), "extra_camera"),
    *_for_each_scope(_delete("cameras", "left", "center_x_px"), "missing_center_x"),
    *_for_each_scope(_delete("cameras", "right", "center_y_px"), "missing_center_y"),
    *_for_each_scope(_delete("cameras", "left", "radius_px"), "missing_radius"),
    *_for_each_scope(_delete("cameras", "right", "rotation_deg"), "missing_rotation"),
    *_for_each_scope(_set(-0.5, "cameras", "left", "center_x_px"), "negative_center_x"),
    *_for_each_scope(_set(-1, "cameras", "right", "center_y_px"), "negative_center_y"),
    *_for_each_scope(_set(0, "cameras", "left", "radius_px"), "zero_radius"),
    *_for_each_scope(_set(-10, "cameras", "right", "radius_px"), "negative_radius"),
    *_for_each_scope(
        _set(-180, "cameras", "left", "rotation_deg"), "rotation_minus_180"
    ),
    *_for_each_scope(
        _set(180.1, "cameras", "right", "rotation_deg"), "rotation_above_180"
    ),
    *_for_each_scope(_set("2028", "cameras", "left", "center_x_px"), "string_center_x"),
    *_for_each_scope(_set(None, "cameras", "right", "radius_px"), "null_radius"),
    *_for_each_scope(_set(True, "cameras", "left", "rotation_deg"), "boolean_rotation"),
    *_for_each_scope(
        _set([2028, 1520], "cameras", "left", "center_x_px"), "array_center_x"
    ),
    *_for_each_scope(_set(None, "cameras", "left"), "null_camera"),
    *_for_each_scope(_set("x", "notes"), "extra_top_level_property"),
    *_for_each_scope(_set(1, "cameras", "right", "fov_deg"), "extra_camera_property"),
    pytest.param(
        device_default, _delete("cameras", "right"), id="device_default_missing_right"
    ),
    pytest.param(
        device_default, _delete("cameras", "left"), id="device_default_missing_left"
    ),
]


@pytest.mark.parametrize(("base", "mutate"), INVALID_CASES)
def test_invalid_examples_fail(
    correction_validator: Draft202012Validator,
    base: Callable[[], dict[str, Any]],
    mutate: Mutation,
) -> None:
    correction = base()
    mutate(correction)
    assert not correction_validator.is_valid(correction)
