import json
import logging
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum

logger = logging.getLogger(__name__)

HEADER = struct.Struct(">IB")
THUMBNAIL_ID = struct.Struct(">I")
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024


class FrameKind(IntEnum):
    JSON = 0x01
    PREVIEW = 0x02
    THUMBNAIL = 0x03


class FrameError(ValueError):
    pass


@dataclass(frozen=True)
class Frame:
    kind: FrameKind
    payload: bytes


def encode_frame(frame: Frame) -> bytes:
    if len(frame.payload) > MAX_PAYLOAD_BYTES:
        raise FrameError(
            f"payload of {len(frame.payload)} bytes exceeds {MAX_PAYLOAD_BYTES}"
        )
    return HEADER.pack(len(frame.payload), frame.kind) + frame.payload


def json_frame(message: Mapping[str, object]) -> Frame:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    return Frame(FrameKind.JSON, body.encode("utf-8"))


def preview_frame(jpeg: bytes) -> Frame:
    return Frame(FrameKind.PREVIEW, jpeg)


def thumbnail_frame(request_id: int, jpeg: bytes) -> Frame:
    return Frame(FrameKind.THUMBNAIL, THUMBNAIL_ID.pack(request_id) + jpeg)


class FrameDecoder:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        self._buffer += data
        frames: list[Frame] = []
        while len(self._buffer) >= HEADER.size:
            length, kind = HEADER.unpack_from(self._buffer)
            if length > MAX_PAYLOAD_BYTES:
                raise FrameError(f"frame length {length} exceeds {MAX_PAYLOAD_BYTES}")
            end = HEADER.size + length
            if len(self._buffer) < end:
                break
            payload = bytes(self._buffer[HEADER.size : end])
            del self._buffer[:end]
            try:
                frame_kind = FrameKind(kind)
            except ValueError:
                logger.debug("skipping a frame of unknown kind 0x%02x", kind)
                continue
            frames.append(Frame(frame_kind, payload))
        return frames
