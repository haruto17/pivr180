import logging
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pivr180_device.button import Status
from pivr180_device.storage import CaptureNotFoundError, CaptureStorage

logger = logging.getLogger(__name__)

UNKNOWN_ERROR = "an error occurred; see the Pi log"

StatusMessage = dict[str, Any]
StatusListener = Callable[[StatusMessage], None]


@dataclass(frozen=True)
class LastCapture:
    id: str
    sync_warning: bool


def free_bytes(root: Path) -> int:
    path = root
    # Not the root alone: it is created only by the first capture.
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


class StatusBoard:
    def __init__(
        self,
        storage: CaptureStorage,
        measure_free_bytes: Callable[[Path], int] = free_bytes,
    ) -> None:
        self._storage = storage
        self._measure_free_bytes = measure_free_bytes
        # Not released while calling listeners: messages computed one after
        # another must reach every listener in that order.
        self._lock = threading.Lock()
        self._listeners: list[StatusListener] = []
        self._state = Status.IDLE
        self._error_message: str | None = None
        self._last_capture: LastCapture | None = None
        self._capture_count = 0
        self._free_bytes = 0
        self._published: StatusMessage | None = None

    def show(self, status: Status, error_message: str | None = None) -> None:
        with self._lock:
            self._state = status
            self._error_message = (
                (error_message or UNKNOWN_ERROR) if status == Status.ERROR else None
            )
            self._publish()

    def saved(self, capture_id: str, sync_warning: bool) -> None:
        with self._lock:
            # Not taken on trust: the capture loop reports a save only after
            # resuming the preview, and the app may have deleted it meanwhile.
            try:
                self._storage.find_capture(capture_id)
            except CaptureNotFoundError:
                logger.info("%s was deleted before its save was reported", capture_id)
            else:
                self._last_capture = LastCapture(capture_id, sync_warning)
            self._measure()
            self._publish()

    def deleted(self, capture_id: str) -> None:
        with self._lock:
            if self._last_capture is not None and self._last_capture.id == capture_id:
                self._last_capture = None
            self._measure()
            self._publish()

    def subscribe(self, listener: StatusListener) -> Callable[[], None]:
        with self._lock:
            # Not only measured on saves: space may have been freed or used by
            # other means since, and a new connection should see it.
            self._measure()
            message = self._message()
            self._published = message
            # Not returned to the caller to pass on: a change on the capture
            # loop could then reach the listener before this first message.
            self._call(listener, message)
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def _measure(self) -> None:
        # Not done on show(): it runs on the capture loop before each shot, and
        # neither the count nor the free space changes until a shot is saved.
        try:
            self._capture_count = len(self._storage.list_captures())
            self._free_bytes = self._measure_free_bytes(self._storage.root)
        except OSError as error:
            logger.warning(
                "could not measure the captures in %s (%s); keeping the last values",
                self._storage.root,
                error,
            )

    def _message(self) -> StatusMessage:
        message: StatusMessage = {"type": "status", "state": str(self._state)}
        if self._error_message is not None:
            message["error_message"] = self._error_message
        message["capture_count"] = self._capture_count
        message["free_bytes"] = self._free_bytes
        message["last_capture"] = (
            None
            if self._last_capture is None
            else {
                "id": self._last_capture.id,
                "sync_warning": self._last_capture.sync_warning,
            }
        )
        return message

    def _publish(self) -> None:
        message = self._message()
        if message == self._published:
            return
        self._published = message
        for listener in list(self._listeners):
            self._call(listener, message)

    def _call(self, listener: StatusListener, message: StatusMessage) -> None:
        try:
            listener(message)
        # Not raised: the caller is the capture loop, which must go on shooting
        # whatever happens to the phone.
        except Exception:
            logger.exception("failed to pass the status on")
