import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from pivr180_device.camera_settings import CameraSettings
from pivr180_device.storage import CAPTURE_ID_PATTERN

MAX_REQUEST_ID = 2**31 - 1
PHOTO_MODE = "photo"
SIDES = frozenset({"left", "right"})


class ErrorCode(StrEnum):
    UNSUPPORTED_PROTOCOL_VERSION = "unsupported_protocol_version"
    HANDSHAKE_REQUIRED = "handshake_required"
    INVALID_MESSAGE = "invalid_message"
    CAMERAS_NOT_READY = "cameras_not_ready"
    CAPTURE_NOT_FOUND = "capture_not_found"
    INTERNAL_ERROR = "internal_error"


class InvalidRequestError(ValueError):
    def __init__(self, message: str, request_id: int | None = None) -> None:
        super().__init__(message)
        self.request_id = request_id


@dataclass(frozen=True)
class Request:
    type: str
    id: int
    fields: Mapping[str, Any] = field(default_factory=dict)


def _protocol_version(value: Any) -> int:
    if not _is_int(value) or value < 1:
        raise ValueError("must be an integer of at least 1")
    return value


def _non_empty_string(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("must be a non-empty string")
    return value


def _camera_settings(value: Any) -> CameraSettings:
    try:
        return CameraSettings.model_validate(value, strict=True)
    except ValidationError as error:
        raise ValueError("; ".join(map(_describe, error.errors()))) from None


def _describe(problem: ErrorDetails) -> str:
    location = ".".join(str(part) for part in problem["loc"])
    return f"{location} {problem['msg']}" if location else problem["msg"]


def _capture_mode(value: Any) -> str:
    if value != PHOTO_MODE:
        raise ValueError(f"must be {PHOTO_MODE!r}; video comes in M10")
    return value


def _capture_id(value: Any) -> str:
    if not isinstance(value, str) or not CAPTURE_ID_PATTERN.fullmatch(value):
        raise ValueError("must be YYYYMMDD-HHMMSS-NNN")
    return value


def _side(value: Any) -> str:
    if not isinstance(value, str) or value not in SIDES:
        raise ValueError("must be 'left' or 'right'")
    return value


Field = Callable[[Any], Any]

REQUEST_FIELDS: dict[str, dict[str, Field]] = {
    "hello": {"protocol_version": _protocol_version, "app_version": _non_empty_string},
    "shutter": {},
    "get_settings": {},
    "set_settings": {"settings": _camera_settings},
    "get_mode": {},
    "set_mode": {"mode": _capture_mode},
    "list_captures": {},
    "get_thumbnail": {"capture_id": _capture_id, "side": _side},
    "delete_capture": {"capture_id": _capture_id},
    "shutdown": {},
    "stop_preview": {},
    "start_preview": {},
}


def _is_int(value: Any) -> bool:
    # Not isinstance(value, int) alone: JSON true and false load as bool,
    # which is an int in Python.
    return isinstance(value, int) and not isinstance(value, bool)


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def parse_request(payload: bytes) -> Request:
    try:
        message = json.loads(payload.decode("utf-8"), parse_constant=_reject_constant)
    except ValueError:
        raise InvalidRequestError("frame body is not valid JSON") from None
    if not isinstance(message, dict):
        raise InvalidRequestError("request is not a JSON object")
    request_id = message.get("id")
    if not _is_int(request_id) or not 0 <= request_id <= MAX_REQUEST_ID:
        raise InvalidRequestError("request has no valid id")
    request_type = message.get("type")
    if not isinstance(request_type, str) or request_type not in REQUEST_FIELDS:
        raise InvalidRequestError(f"unknown request type {request_type!r}", request_id)
    expected = REQUEST_FIELDS[request_type]
    unknown = sorted(set(message) - {"type", "id"} - set(expected))
    if unknown:
        raise InvalidRequestError(
            f"{request_type} does not take {', '.join(unknown)}", request_id
        )
    fields: dict[str, Any] = {}
    for name, parse in expected.items():
        if name not in message:
            raise InvalidRequestError(f"{request_type} needs {name}", request_id)
        try:
            fields[name] = parse(message[name])
        except ValueError as error:
            raise InvalidRequestError(
                f"{request_type}.{name} {error}", request_id
            ) from None
    return Request(request_type, request_id, fields)


def error_message(
    code: ErrorCode, message: str, request_id: int | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"type": "error"}
    if request_id is not None:
        error["id"] = request_id
    error["code"] = str(code)
    error["message"] = message
    return error
