from collections.abc import Sequence
from dataclasses import dataclass

from pivr180_device.camera.base import CameraPair, Frame

MAX_TIMESTAMP_DIFF_NS = 1_000_000
MAX_ATTEMPTS = 3
FRAMES_PER_CAMERA = 2


@dataclass(frozen=True)
class SyncedPair:
    left: Frame
    right: Frame
    attempts: int
    warning: bool

    @property
    def left_timestamp_ns(self) -> int:
        return self.left.metadata.sensor_timestamp_ns

    @property
    def right_timestamp_ns(self) -> int:
        return self.right.metadata.sensor_timestamp_ns

    @property
    def timestamp_diff_ns(self) -> int:
        return abs(self.left_timestamp_ns - self.right_timestamp_ns)


def timestamp_diff_ns(left: Frame, right: Frame) -> int:
    return abs(left.metadata.sensor_timestamp_ns - right.metadata.sensor_timestamp_ns)


def select_closest_pair(
    left_frames: Sequence[Frame], right_frames: Sequence[Frame]
) -> tuple[Frame, Frame]:
    if not left_frames or not right_frames:
        raise ValueError("both cameras must provide at least one frame")
    return min(
        ((left, right) for left in left_frames for right in right_frames),
        key=lambda candidate: timestamp_diff_ns(*candidate),
    )


def capture_synced_pair(
    pair: CameraPair,
    *,
    frames_per_camera: int = FRAMES_PER_CAMERA,
) -> SyncedPair:
    if frames_per_camera < 1:
        raise ValueError(f"frames_per_camera must be >= 1, got {frames_per_camera}")

    best: tuple[Frame, Frame] | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        left_frames: list[Frame] = []
        right_frames: list[Frame] = []
        # Not all left frames first: every right frame would then be later than
        # every left frame, so no candidate pair could be from the same instant.
        for _ in range(frames_per_camera):
            left_frames.append(pair.left.capture_frame())
            right_frames.append(pair.right.capture_frame())
        candidate = select_closest_pair(left_frames, right_frames)
        if timestamp_diff_ns(*candidate) <= MAX_TIMESTAMP_DIFF_NS:
            return SyncedPair(*candidate, attempts=attempt, warning=False)
        if best is None or timestamp_diff_ns(*candidate) < timestamp_diff_ns(*best):
            best = candidate

    assert best is not None
    return SyncedPair(*best, attempts=MAX_ATTEMPTS, warning=True)
