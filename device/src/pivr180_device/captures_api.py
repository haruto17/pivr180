import json
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response
from PIL import Image

from pivr180_device.storage import (
    LEFT_FILENAME,
    META_FILENAME,
    RIGHT_FILENAME,
    CaptureNotFoundError,
    CaptureStorage,
)

THUMBNAIL_SIZE = (480, 480)
THUMBNAIL_QUALITY = 80
# Not no-cache: a capture's images never change once saved, and refetching
# them on every visit would decode the full-size JPEGs again.
THUMBNAIL_CACHE_CONTROL = "private, max-age=86400"
IMAGE_FILENAMES = {"left": LEFT_FILENAME, "right": RIGHT_FILENAME}
Side = Literal["left", "right"]


def summarize_captures(storage: CaptureStorage) -> list[dict[str, Any]]:
    return [_summarize(directory) for directory in storage.list_captures()]


def capture_thumbnail(storage: CaptureStorage, capture_id: str, side: Side) -> bytes:
    directory = storage.find_capture(capture_id)
    return _shrink(directory / IMAGE_FILENAMES[side])


def captures_router(storage: CaptureStorage) -> APIRouter:
    router = APIRouter(prefix="/api/captures")

    @router.get("")
    def list_captures() -> list[dict[str, Any]]:
        return summarize_captures(storage)

    @router.get("/{capture_id}/thumbnails/{side}")
    def thumbnail(capture_id: str, side: Side) -> Response:
        try:
            image = capture_thumbnail(storage, capture_id, side)
        except (CaptureNotFoundError, OSError) as error:
            raise HTTPException(status_code=404) from error
        return Response(
            image,
            media_type="image/jpeg",
            headers={"Cache-Control": THUMBNAIL_CACHE_CONTROL},
        )

    @router.delete("/{capture_id}", status_code=204)
    def delete_capture(capture_id: str) -> None:
        try:
            storage.delete_capture(capture_id)
        except CaptureNotFoundError as error:
            raise HTTPException(status_code=404) from error

    return router


def _summarize(directory: Path) -> dict[str, Any]:
    meta = _read_meta(directory / META_FILENAME)
    has_images = all((directory / name).is_file() for name in IMAGE_FILENAMES.values())
    return {
        "id": directory.name,
        "complete": meta is not None and has_images,
        "sync_warning": _sync_warning(meta),
    }


def _read_meta(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sync_warning(meta: Any) -> bool | None:
    try:
        warning = meta["sync"]["warning"]
    except (KeyError, TypeError):
        return None
    return warning if isinstance(warning, bool) else None


def _shrink(path: Path) -> bytes:
    with Image.open(path) as image:
        # Not left to thumbnail(): its reducing gap decodes the JPEG at 1/4
        # scale, while draft() lets libjpeg decode straight at 1/8.
        image.draft("RGB", THUMBNAIL_SIZE)
        image.thumbnail(THUMBNAIL_SIZE)
        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=THUMBNAIL_QUALITY)
    return buffer.getvalue()
