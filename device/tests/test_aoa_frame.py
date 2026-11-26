import json

import pytest

from pivr180_device.aoa.frame import (
    MAX_PAYLOAD_BYTES,
    Frame,
    FrameDecoder,
    FrameError,
    FrameKind,
    encode_frame,
    json_frame,
    preview_frame,
    thumbnail_frame,
)

SHUTTER = b'{"type":"shutter","id":7}'
SHUTTER_FRAME = b"\x00\x00\x00\x19\x01" + SHUTTER


def test_encodes_length_kind_and_payload():
    assert encode_frame(Frame(FrameKind.JSON, SHUTTER)) == SHUTTER_FRAME


def test_encodes_an_empty_payload_with_length_zero():
    assert encode_frame(Frame(FrameKind.PREVIEW, b"")) == b"\x00\x00\x00\x00\x02"


def test_encodes_the_length_big_endian():
    encoded = encode_frame(Frame(FrameKind.PREVIEW, b"x" * 0x010203))

    assert encoded[:5] == b"\x00\x01\x02\x03\x02"
    assert len(encoded) == 5 + 0x010203


def test_encodes_a_payload_at_the_limit():
    encoded = encode_frame(Frame(FrameKind.PREVIEW, bytes(MAX_PAYLOAD_BYTES)))

    assert encoded[:4] == b"\x00\x40\x00\x00"


def test_refuses_to_encode_a_payload_over_the_limit():
    with pytest.raises(FrameError):
        encode_frame(Frame(FrameKind.PREVIEW, bytes(MAX_PAYLOAD_BYTES + 1)))


def test_json_frame_is_compact_utf8_json():
    frame = json_frame({"type": "error", "message": "保存に失敗"})

    assert frame.kind is FrameKind.JSON
    assert json.loads(frame.payload.decode("utf-8")) == {
        "type": "error",
        "message": "保存に失敗",
    }
    assert b" " not in frame.payload
    assert "保存に失敗".encode() in frame.payload


def test_json_frame_matches_the_protocol_example():
    assert encode_frame(json_frame({"type": "shutter", "id": 7})) == SHUTTER_FRAME


def test_preview_frame_carries_the_jpeg_as_is():
    assert preview_frame(b"\xff\xd8jpeg") == Frame(FrameKind.PREVIEW, b"\xff\xd8jpeg")


def test_thumbnail_frame_prefixes_the_request_id_big_endian():
    frame = thumbnail_frame(7, b"\xff\xd8jpeg")

    assert encode_frame(frame) == (
        b"\x00\x00\x00\x0a\x03" + b"\x00\x00\x00\x07" + b"\xff\xd8jpeg"
    )


def test_decodes_a_whole_frame():
    assert FrameDecoder().feed(SHUTTER_FRAME) == [Frame(FrameKind.JSON, SHUTTER)]


def test_decodes_a_frame_split_across_reads():
    decoder = FrameDecoder()

    parts = [SHUTTER_FRAME[:2], SHUTTER_FRAME[2:5], SHUTTER_FRAME[5:10]]
    assert [decoder.feed(part) for part in parts] == [[], [], []]
    assert decoder.feed(SHUTTER_FRAME[10:]) == [Frame(FrameKind.JSON, SHUTTER)]


def test_decodes_a_frame_fed_one_byte_at_a_time():
    decoder = FrameDecoder()

    frames = [frame for byte in SHUTTER_FRAME for frame in decoder.feed(bytes([byte]))]

    assert frames == [Frame(FrameKind.JSON, SHUTTER)]


def test_decodes_several_frames_from_one_read_and_keeps_the_rest():
    decoder = FrameDecoder()
    empty = b"\x00\x00\x00\x00\x01"
    data = SHUTTER_FRAME + empty + SHUTTER_FRAME[:7]

    assert decoder.feed(data) == [
        Frame(FrameKind.JSON, SHUTTER),
        Frame(FrameKind.JSON, b""),
    ]
    assert decoder.feed(SHUTTER_FRAME[7:]) == [Frame(FrameKind.JSON, SHUTTER)]


def test_skips_frames_of_unknown_kind_by_their_length():
    decoder = FrameDecoder()
    unknown = b"\x00\x00\x00\x03\x7fabc"

    assert decoder.feed(unknown + SHUTTER_FRAME) == [Frame(FrameKind.JSON, SHUTTER)]


def test_decodes_what_it_encodes():
    frames = [
        json_frame({"type": "ok", "id": 1}),
        preview_frame(bytes(range(256)) * 10),
        thumbnail_frame(2147483647, b"\xff\xd8"),
        Frame(FrameKind.JSON, b""),
    ]

    data = b"".join(encode_frame(frame) for frame in frames)

    assert FrameDecoder().feed(data) == frames


def test_accepts_a_length_at_the_limit():
    decoder = FrameDecoder()

    assert decoder.feed(b"\x00\x40\x00\x00\x02") == []


def test_rejects_a_length_over_the_limit_before_its_payload_arrives():
    with pytest.raises(FrameError):
        FrameDecoder().feed(b"\x00\x40\x00\x01\x02")
