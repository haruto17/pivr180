import asyncio
import io
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from PIL import Image

from pivr180_device.slot import CameraSlot

logger = logging.getLogger(__name__)

PREVIEW_PATH = "/api/preview.mjpg"
MAX_FPS = 5.0
JPEG_QUALITY = 70
BOUNDARY = "frame"


def side_by_side_jpeg(
    left: Image.Image, right: Image.Image, quality: int = JPEG_QUALITY
) -> bytes:
    canvas = Image.new(
        "RGB", (left.width + right.width, max(left.height, right.height))
    )
    canvas.paste(left.convert("RGB"), (0, 0))
    canvas.paste(right.convert("RGB"), (left.width, 0))
    buffer = io.BytesIO()
    canvas.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


class PreviewFrames:
    def __init__(
        self,
        slot: CameraSlot,
        min_interval_s: float = 1 / MAX_FPS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._slot = slot
        self._min_interval_s = min_interval_s
        self._clock = clock
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._taken_at = 0.0

    def latest(self) -> bytes | None:
        with self._lock, self._slot.borrow() as cameras:
            if cameras is None:
                self._jpeg = None
                return None
            now = self._clock()
            # Not captured per client: each phone would cost another capture
            # and JPEG encoding on the Pi, which shares the CPU with shooting.
            if self._jpeg is not None and now - self._taken_at < self._min_interval_s:
                return self._jpeg
            left = cameras.pair.left.capture_preview()
            right = cameras.pair.right.capture_preview()
            self._jpeg = side_by_side_jpeg(left, right)
            self._taken_at = now
            return self._jpeg


def mjpeg_part(jpeg: bytes) -> bytes:
    header = (
        f"--{BOUNDARY}\r\n"
        "Content-Type: image/jpeg\r\n"
        f"Content-Length: {len(jpeg)}\r\n\r\n"
    ).encode("ascii")
    return header + jpeg + b"\r\n"


def preview_router(
    slot: CameraSlot,
    max_fps: float = MAX_FPS,
    clock: Callable[[], float] = time.monotonic,
) -> APIRouter:
    interval_s = 1 / max_fps
    frames = PreviewFrames(slot, interval_s, clock)
    router = APIRouter()

    async def stream() -> AsyncIterator[bytes]:
        while True:
            try:
                jpeg = await run_in_threadpool(frames.latest)
            except Exception:
                logger.exception("live preview failed; ending the stream")
                return
            if jpeg is None:
                return
            yield mjpeg_part(jpeg)
            # Not shortened by the time taken to capture: the next frame would
            # then come within the interval and get the same cached JPEG again.
            await asyncio.sleep(interval_s)

    @router.get(PREVIEW_PATH)
    async def preview() -> StreamingResponse:
        if not slot.ready:
            raise HTTPException(status_code=503, detail="cameras are not ready")
        return StreamingResponse(
            stream(),
            media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store"},
        )

    return router
