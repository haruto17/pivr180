import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import EXAMPLES_DIR, example_paths, load_json
from jsonschema import Draft202012Validator

META_EXAMPLES = example_paths("meta")
Mutation = Callable[[dict[str, Any]], None]


def valid_meta() -> dict[str, Any]:
    return load_json(EXAMPLES_DIR / "meta" / "synced.json")


def test_schema_is_valid_draft_2020_12(meta_schema: dict[str, Any]) -> None:
    Draft202012Validator.check_schema(meta_schema)
    assert meta_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert meta_schema["$id"]


def test_meta_examples_exist() -> None:
    assert META_EXAMPLES


@pytest.mark.parametrize("path", META_EXAMPLES, ids=lambda p: p.stem)
def test_valid_examples_pass(meta_validator: Draft202012Validator, path: Path) -> None:
    meta_validator.validate(load_json(path))


@pytest.mark.parametrize("path", META_EXAMPLES, ids=lambda p: p.stem)
def test_examples_diff_matches_timestamps(path: Path) -> None:
    meta = load_json(path)
    left = meta["cameras"]["left"]["sensor_timestamp_ns"]
    right = meta["cameras"]["right"]["sensor_timestamp_ns"]
    assert meta["sync"]["timestamp_diff_ns"] == abs(left - right)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda m: m["sync"].update(attempts=2), id="within_tolerance_after_retry"
        ),
        pytest.param(
            lambda m: m["sync"].update(timestamp_diff_ns=1_000_000),
            id="diff_exactly_1ms",
        ),
    ],
)
def test_valid_variants_pass(
    meta_validator: Draft202012Validator, mutate: Mutation
) -> None:
    meta = valid_meta()
    mutate(meta)
    meta_validator.validate(meta)


def _delete(*keys: str) -> Mutation:
    def mutate(meta: dict[str, Any]) -> None:
        target = meta
        for key in keys[:-1]:
            target = target[key]
        del target[keys[-1]]

    return mutate


def _set(value: Any, *keys: str) -> Mutation:
    def mutate(meta: dict[str, Any]) -> None:
        target = meta
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = copy.deepcopy(value)

    return mutate


INVALID_CASES = [
    pytest.param(_delete("schema_version"), id="missing_schema_version"),
    pytest.param(_set(2, "schema_version"), id="unknown_schema_version"),
    pytest.param(_delete("software_version"), id="missing_software_version"),
    pytest.param(_set("", "software_version"), id="empty_software_version"),
    pytest.param(_delete("cameras", "right"), id="missing_right_camera"),
    pytest.param(_delete("cameras", "left", "camera_id"), id="missing_camera_id"),
    pytest.param(_delete("cameras", "right", "model"), id="missing_model"),
    pytest.param(
        _delete("cameras", "left", "sensor_timestamp_ns"), id="missing_sensor_timestamp"
    ),
    pytest.param(
        _set(1.5, "cameras", "left", "sensor_timestamp_ns"),
        id="non_integer_sensor_timestamp",
    ),
    pytest.param(
        _set(-1, "cameras", "right", "sensor_timestamp_ns"),
        id="negative_sensor_timestamp",
    ),
    pytest.param(_set("", "cameras", "left", "camera_id"), id="empty_camera_id"),
    pytest.param(_set({}, "cameras", "center"), id="extra_camera"),
    pytest.param(_delete("sync", "timestamp_diff_ns"), id="missing_timestamp_diff"),
    pytest.param(_set(-1, "sync", "timestamp_diff_ns"), id="negative_timestamp_diff"),
    pytest.param(_delete("sync", "warning"), id="missing_warning"),
    pytest.param(_delete("sync", "attempts"), id="missing_attempts"),
    pytest.param(_set(0, "sync", "attempts"), id="zero_attempts"),
    pytest.param(_set(4, "sync", "attempts"), id="too_many_attempts"),
    pytest.param(_set(True, "sync", "warning"), id="warning_within_tolerance"),
    pytest.param(
        _set(1_000_001, "sync", "timestamp_diff_ns"), id="no_warning_beyond_tolerance"
    ),
    pytest.param(
        lambda m: m["sync"].update(
            timestamp_diff_ns=1_500_000, attempts=2, warning=True
        ),
        id="warning_before_final_attempt",
    ),
    pytest.param(_delete("exposure", "exposure_time_us"), id="missing_exposure_time"),
    pytest.param(_set(0, "exposure", "exposure_time_us"), id="zero_exposure_time"),
    pytest.param(
        _set(8000.5, "exposure", "exposure_time_us"), id="non_integer_exposure_time"
    ),
    pytest.param(_delete("exposure", "analogue_gain"), id="missing_analogue_gain"),
    pytest.param(_set(0.5, "exposure", "analogue_gain"), id="analogue_gain_below_1"),
    pytest.param(_delete("exposure", "colour_gains"), id="missing_colour_gains"),
    pytest.param(_set([2.1], "exposure", "colour_gains"), id="colour_gains_too_short"),
    pytest.param(
        _set([2.1, 1.8, 1.0], "exposure", "colour_gains"), id="colour_gains_too_long"
    ),
    pytest.param(_set([0, 1.8], "exposure", "colour_gains"), id="zero_colour_gain"),
    pytest.param(
        _set(["2.1", 1.8], "exposure", "colour_gains"), id="string_colour_gain"
    ),
    pytest.param(
        _set({"red": 2.1, "blue": 1.8}, "exposure", "colour_gains"),
        id="colour_gains_object",
    ),
    pytest.param(_set("x", "notes"), id="extra_top_level_property"),
    pytest.param(_set(1, "cameras", "left", "lens"), id="extra_camera_property"),
    pytest.param(_set(1, "sync", "threshold_ns"), id="extra_sync_property"),
    pytest.param(_set(1, "exposure", "digital_gain"), id="extra_exposure_property"),
]


@pytest.mark.parametrize("mutate", INVALID_CASES)
def test_invalid_examples_fail(
    meta_validator: Draft202012Validator, mutate: Mutation
) -> None:
    meta = valid_meta()
    mutate(meta)
    assert not meta_validator.is_valid(meta)
