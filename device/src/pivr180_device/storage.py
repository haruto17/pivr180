import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pivr180_device.camera.base import Frame

STILL_SIZE = (4056, 3040)
JPEG_QUALITY = 100
DEFAULT_CAPTURE_ROOT = Path("/data/captures")
LEFT_FILENAME = "left.jpg"
RIGHT_FILENAME = "right.jpg"
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

    def save_pair(self, left: Frame, right: Frame) -> Path:
        with self.new_capture() as directory:
            _save_frame(left, directory / LEFT_FILENAME)
            _save_frame(right, directory / RIGHT_FILENAME)
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


def _save_frame(frame: Frame, path: Path) -> None:
    try:
        frame.save(path, JPEG_QUALITY)
    except Exception as error:
        raise CaptureSaveError(f"failed to save {path}") from error
