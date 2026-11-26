import json
from pathlib import Path
from typing import Any

import pytest

from pivr180_device.aoa.frame import (
    THUMBNAIL_ID,
    Frame,
    FrameDecoder,
    FrameError,
    FrameKind,
    encode_frame,
    json_frame,
    preview_frame,
    thumbnail_frame,
)

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "schema" / "examples" / "aoa"
FRAMES = sorted((EXAMPLES_DIR / "frames").glob("*.json"))
HEADERS = sorted((EXAMPLES_DIR / "frame_headers").glob("*.json"))
KNOWN_KINDS = {kind.value for kind in FrameKind}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def known(paths: list[Path]) -> list[Path]:
    return [path for path in paths if load(path)["frame_type"] in KNOWN_KINDS]


def unknown(paths: list[Path]) -> list[Path]:
    return [path for path in paths if load(path)["frame_type"] not in KNOWN_KINDS]


def ids(paths: list[Path]) -> list[str]:
    return [path.stem for path in paths]


def test_examples_cover_every_kind_and_both_limits():
    kinds = {load(path)["frame_type"] for path in FRAMES}
    limits = {load(path)["within_limit"] for path in HEADERS}

    assert KNOWN_KINDS <= kinds
    assert unknown(FRAMES)
    assert limits == {True, False}


@pytest.mark.parametrize("path", known(FRAMES), ids=ids(known(FRAMES)))
def test_encodes_the_example_frame_from_its_type_and_body(path: Path):
    example = load(path)
    frame = Frame(FrameKind(example["frame_type"]), bytes.fromhex(example["body"]))

    assert encode_frame(frame).hex() == example["frame"]


@pytest.mark.parametrize("path", known(FRAMES), ids=ids(known(FRAMES)))
def test_decodes_the_example_frame_into_its_type_and_body(path: Path):
    example = load(path)

    frames = FrameDecoder().feed(bytes.fromhex(example["frame"]))

    assert [(frame.kind, frame.payload.hex()) for frame in frames] == [
        (example["frame_type"], example["body"])
    ]


@pytest.mark.parametrize("path", known(FRAMES), ids=ids(known(FRAMES)))
def test_example_body_matches_its_message_or_jpeg(path: Path):
    example = load(path)
    body = bytes.fromhex(example["body"])
    kind = FrameKind(example["frame_type"])

    if kind is FrameKind.JSON:
        assert json.loads(body.decode("utf-8")) == example["message"]
        assert json.loads(json_frame(example["message"]).payload) == example["message"]
    elif kind is FrameKind.PREVIEW:
        jpeg = bytes.fromhex(example["jpeg"])
        assert body == jpeg
        assert preview_frame(jpeg).payload == body
    else:
        jpeg = bytes.fromhex(example["jpeg"])
        (thumbnail_id,) = THUMBNAIL_ID.unpack_from(body)
        assert thumbnail_id == example["thumbnail_id"]
        assert body[THUMBNAIL_ID.size :] == jpeg
        assert thumbnail_frame(example["thumbnail_id"], jpeg).payload == body


@pytest.mark.parametrize("path", unknown(FRAMES), ids=ids(unknown(FRAMES)))
def test_skips_the_example_frame_of_unknown_type_and_reads_the_next(path: Path):
    example = load(path)
    following = known(FRAMES)[0]
    next_example = load(following)

    frames = FrameDecoder().feed(
        bytes.fromhex(example["frame"]) + bytes.fromhex(next_example["frame"])
    )

    assert [(frame.kind, frame.payload.hex()) for frame in frames] == [
        (next_example["frame_type"], next_example["body"])
    ]


@pytest.mark.parametrize("path", HEADERS, ids=ids(HEADERS))
def test_example_header_is_accepted_only_within_the_limit(path: Path):
    example = load(path)
    header = bytes.fromhex(example["header"])
    assert int.from_bytes(header[:4], "big") == example["length"]
    assert header[4] == example["frame_type"]

    if example["within_limit"]:
        assert FrameDecoder().feed(header) == []
    else:
        with pytest.raises(FrameError):
            FrameDecoder().feed(header)
