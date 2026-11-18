import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from pivr180_device.camera.base import CameraPair
from pivr180_device.exposure import ExposureSync


@dataclass(frozen=True)
class LiveCameras:
    pair: CameraPair
    exposure: ExposureSync


class CameraSlot:
    def __init__(self) -> None:
        self._state = threading.Condition()
        self._cameras: LiveCameras | None = None
        self._borrowers = 0

    @property
    def ready(self) -> bool:
        with self._state:
            return self._cameras is not None

    @contextmanager
    def attach(self, cameras: LiveCameras) -> Iterator[None]:
        with self._state:
            if self._cameras is not None:
                raise RuntimeError("cameras are already attached")
            self._cameras = cameras
        try:
            yield
        finally:
            with self._state:
                self._cameras = None
                self._state.wait_for(lambda: self._borrowers == 0)

    @contextmanager
    def borrow(self) -> Iterator[LiveCameras | None]:
        with self._state:
            cameras = self._cameras
            if cameras is not None:
                self._borrowers += 1
        try:
            yield cameras
        finally:
            if cameras is not None:
                with self._state:
                    self._borrowers -= 1
                    self._state.notify_all()
