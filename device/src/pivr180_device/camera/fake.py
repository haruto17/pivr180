from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pivr180_device.camera.base import Controls, FrameMetadata


@dataclass
class FakeFrame:
    metadata: FrameMetadata
    image: bytes = b""
    saves: list[tuple[Path, int]] = field(default_factory=list)

    def save(self, path: Path, quality: int) -> None:
        path.write_bytes(self.image)
        self.saves.append((path, quality))


class FakeCamera:
    def __init__(
        self,
        camera_id: str,
        model: str = "imx477",
        frames: Iterable[FakeFrame] = (),
    ) -> None:
        self._camera_id = camera_id
        self._model = model
        self._frames: deque[FakeFrame] = deque(frames)
        self.started = False
        self.controls_history: list[Controls] = []

    @property
    def camera_id(self) -> str:
        return self._camera_id

    @property
    def model(self) -> str:
        return self._model

    @property
    def controls(self) -> Controls:
        merged: Controls = {}
        for controls in self.controls_history:
            merged.update(controls)
        return merged

    def push(self, *frames: FakeFrame) -> None:
        self._frames.extend(frames)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def set_controls(self, controls: Controls) -> None:
        self.controls_history.append(Controls(**controls))

    def capture_metadata(self) -> FrameMetadata:
        return self._next_frame().metadata

    def capture_frame(self) -> FakeFrame:
        return self._next_frame()

    def _next_frame(self) -> FakeFrame:
        if not self.started:
            raise RuntimeError(f"camera {self._camera_id} is not started")
        if not self._frames:
            raise RuntimeError(f"camera {self._camera_id} has no scripted frames left")
        return self._frames.popleft()
