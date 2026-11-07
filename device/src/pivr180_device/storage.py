import json
import shutil
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pivr180_device.camera.base import CameraPair, Frame
from pivr180_device.meta import build_meta
from pivr180_device.sync import SyncedPair

STILL_SIZE = (4056, 3040)
JPEG_QUALITY = 100
DEFAULT_CAPTURE_ROOT = Path("/data/captures")
LEFT_FILENAME = "left.jpg"
RIGHT_FILENAME = "right.jpg"
META_FILENAME = "meta.json"
MAX_CAPTURES_PER_SECOND = 1000


class CaptureSaveError(Exception):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CaptureStorage:
    def __init__(
        self,
        root: Path = DEFAULT_CAPTURE_ROOT,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._root = root
        self._clock = clock

    @property
    def root(self) -> Path:
        return self._root

    @contextmanager
    def new_capture(self) -> Iterator[Path]:
        directory = self._reserve_directory()
        try:
            yield directory
        except BaseException as error:
            try:
                shutil.rmtree(directory)
            except OSError as cleanup_error:
                error.add_note(
                    f"failed to remove incomplete capture {directory}: {cleanup_error}"
                )
            raise

    def save_capture(self, cameras: CameraPair, synced: SyncedPair) -> Path:
        _check_size("left", synced.left)
        _check_size("right", synced.right)
        meta_text = _serialize_meta(build_meta(cameras, synced))
        with self.new_capture() as directory:
            _save_frame(synced.left, directory / LEFT_FILENAME)
            _save_frame(synced.right, directory / RIGHT_FILENAME)
            _write_meta(meta_text, directory / META_FILENAME)
        return directory

    def _reserve_directory(self) -> Path:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError(f"clock must return a timezone-aware datetime: {now!r}")
        prefix = now.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
        try:
            self._root.mkdir(exist_ok=True)
        except OSError as error:
            raise CaptureSaveError(
                f"failed to prepare capture root {self._root}"
            ) from error
        for sequence in range(MAX_CAPTURES_PER_SECOND):
            directory = self._root / f"{prefix}-{sequence:03d}"
            try:
                directory.mkdir()
            except FileExistsError:
                continue
            except OSError as error:
                raise CaptureSaveError(
                    f"failed to create capture directory {directory}"
                ) from error
            return directory
        raise CaptureSaveError(
            f"more than {MAX_CAPTURES_PER_SECOND} captures in {prefix} under {self._root}"
        )


def _check_size(side: str, frame: Frame) -> None:
    if frame.size != STILL_SIZE:
        width, height = frame.size
        raise CaptureSaveError(
            f"{side} frame is {width}x{height}, expected "
            f"{STILL_SIZE[0]}x{STILL_SIZE[1]}"
        )


def _save_frame(frame: Frame, path: Path) -> None:
    try:
        frame.save(path, JPEG_QUALITY)
    except Exception as error:
        raise CaptureSaveError(f"failed to save {path}") from error


def _serialize_meta(meta: Mapping[str, Any]) -> str:
    try:
        return json.dumps(meta, indent=2, allow_nan=False) + "\n"
    except (TypeError, ValueError) as error:
        raise CaptureSaveError("failed to serialize capture meta") from error


def _write_meta(text: str, path: Path) -> None:
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as error:
        raise CaptureSaveError(f"failed to save {path}") from error
