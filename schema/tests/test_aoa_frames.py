import json
import re
from pathlib import Path
from typing import Any

import pytest
from conftest import EXAMPLES_DIR, load_json
from test_aoa_schema import DIRECTIONS, message_validator

FRAMES_DIR = EXAMPLES_DIR / "aoa" / "frames"
FRAME_HEADERS_DIR = EXAMPLES_DIR / "aoa" / "frame_headers"
MAX_LENGTH = 4 * 1024 * 1024
JSON, PREVIEW, THUMBNAIL = 0x01, 0x02, 0x03
DECODED_KEYS = {
    JSON: {"message"},
    PREVIEW: {"jpeg"},
    THUMBNAIL: {"thumbnail_id", "jpeg"},
}
FRAME_KEYS = {"direction", "frame", "frame_type", "body"}
HEX = re.compile(r"(?:[0-9a-f]{2})*")


def frame_paths() -> list[Path]:
    return sorted(FRAMES_DIR.glob("*.json"))


def frame_header_paths() -> list[Path]:
    return sorted(FRAME_HEADERS_DIR.glob("*.json"))


def from_hex(value: str) -> bytes:
    assert HEX.fullmatch(value)
    return bytes.fromhex(value)


FRAMES = [pytest.param(path, id=path.stem) for path in frame_paths()]
JPEG_FRAMES = [
    pytest.param(path, id=path.stem)
    for path in frame_paths()
    if "jpeg" in load_json(path)
]
FRAME_HEADERS = [pytest.param(path, id=path.stem) for path in frame_header_paths()]


@pytest.mark.parametrize("path", FRAMES)
def test_frame_is_length_type_and_body(path: Path) -> None:
    example = load_json(path)
    frame = from_hex(example["frame"])
    body = from_hex(example["body"])

    assert int.from_bytes(frame[0:4], "big") == len(body)
    assert frame[4] == example["frame_type"]
    assert frame[5:] == body
    assert len(body) <= MAX_LENGTH


@pytest.mark.parametrize("path", FRAMES)
def test_frame_has_only_keys_for_its_type(path: Path) -> None:
    example = load_json(path)
    expected = FRAME_KEYS | DECODED_KEYS.get(example["frame_type"], set())
    assert set(example) == expected
    assert example["direction"] in DIRECTIONS


@pytest.mark.parametrize("path", FRAMES)
def test_frame_body_matches_its_decoded_form(
    aoa_schema: dict[str, Any], path: Path
) -> None:
    example = load_json(path)
    body = from_hex(example["body"])

    frame_type = example["frame_type"]
    if frame_type == JSON:
        assert json.loads(body.decode("utf-8")) == example["message"]
        validator = message_validator(aoa_schema, DIRECTIONS[example["direction"]])
        validator.validate(example["message"])
    elif frame_type == PREVIEW:
        assert example["direction"] == "device_to_app"
        assert body == from_hex(example["jpeg"])
    elif frame_type == THUMBNAIL:
        assert example["direction"] == "device_to_app"
        assert body[0:4] == example["thumbnail_id"].to_bytes(4, "big")
        assert body[4:] == from_hex(example["jpeg"])


@pytest.mark.parametrize("path", JPEG_FRAMES)
def test_frame_jpeg_has_start_and_end_markers(path: Path) -> None:
    jpeg = from_hex(load_json(path)["jpeg"])
    assert jpeg.startswith(b"\xff\xd8")
    assert jpeg.endswith(b"\xff\xd9")


def test_frames_cover_every_type_and_boundary() -> None:
    examples = [load_json(path) for path in frame_paths()]
    types = {example["frame_type"] for example in examples}

    assert {JSON, PREVIEW, THUMBNAIL} <= types
    assert types - {JSON, PREVIEW, THUMBNAIL}
    assert any(example["body"] == "" for example in examples)
    assert {
        example["direction"] for example in examples if example["frame_type"] == JSON
    } == set(DIRECTIONS)
    assert any(
        max(from_hex(example["body"])) >= 0x80
        for example in examples
        if example["frame_type"] == JSON
    )


@pytest.mark.parametrize("path", FRAME_HEADERS)
def test_frame_header_is_length_and_type(path: Path) -> None:
    example = load_json(path)
    header = from_hex(example["header"])

    assert set(example) == {"header", "length", "frame_type", "within_limit"}
    assert len(header) == 5
    assert int.from_bytes(header[0:4], "big") == example["length"]
    assert header[4] == example["frame_type"]
    assert example["within_limit"] == (example["length"] <= MAX_LENGTH)


def test_frame_headers_cover_the_length_limit() -> None:
    lengths = {load_json(path)["length"] for path in frame_header_paths()}
    assert {MAX_LENGTH, MAX_LENGTH + 1} <= lengths
