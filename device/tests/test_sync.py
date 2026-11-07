import pytest

from pivr180_device.camera import CameraPair, FrameMetadata
from pivr180_device.camera.fake import FakeCamera, FakeFrame
from pivr180_device.sync import (
    MAX_ATTEMPTS,
    MAX_TIMESTAMP_DIFF_NS,
    capture_synced_pair,
    select_closest_pair,
)


def make_frame(sensor_timestamp_ns: int) -> FakeFrame:
    return FakeFrame(
        FrameMetadata(
            sensor_timestamp_ns=sensor_timestamp_ns,
            exposure_time_us=10_000,
            analogue_gain=1.0,
            colour_gains=(2.0, 1.5),
        )
    )


def make_pair(
    left_frames: list[FakeFrame], right_frames: list[FakeFrame]
) -> tuple[CameraPair, FakeCamera, FakeCamera]:
    left = FakeCamera("left", frames=left_frames)
    right = FakeCamera("right", frames=right_frames)
    pair = CameraPair(left=left, right=right)
    pair.start()
    return pair, left, right


def remaining(camera: FakeCamera) -> int:
    count = 0
    while True:
        try:
            camera.capture_frame()
        except RuntimeError:
            return count
        count += 1


def test_defaults_follow_the_spec():
    assert MAX_TIMESTAMP_DIFF_NS == 1_000_000
    assert MAX_ATTEMPTS == 3


def test_select_closest_pair_picks_smallest_timestamp_difference():
    left = [make_frame(1_000_000), make_frame(34_000_000)]
    right = [make_frame(33_900_000), make_frame(67_000_000)]

    assert select_closest_pair(left, right) == (left[1], right[0])


def test_select_closest_pair_prefers_earlier_candidate_on_tie():
    left = [make_frame(10), make_frame(30)]
    right = [make_frame(20)]

    chosen_left, chosen_right = select_closest_pair(left, right)

    assert chosen_left is left[0]
    assert chosen_right is right[0]


@pytest.mark.parametrize(
    ("left_frames", "right_frames"),
    [([], [make_frame(0)]), ([make_frame(0)], []), ([], [])],
)
def test_select_closest_pair_rejects_empty_candidates(left_frames, right_frames):
    with pytest.raises(ValueError):
        select_closest_pair(left_frames, right_frames)


def test_returns_closest_pair_on_first_attempt():
    left_frames = [make_frame(100_000_000), make_frame(133_000_000)]
    right_frames = [make_frame(132_900_000), make_frame(166_000_000)]
    pair, _, _ = make_pair(left_frames, right_frames)

    result = capture_synced_pair(pair)

    assert result.left is left_frames[1]
    assert result.right is right_frames[0]
    assert result.left_timestamp_ns == 133_000_000
    assert result.right_timestamp_ns == 132_900_000
    assert result.timestamp_diff_ns == 100_000
    assert result.attempts == 1
    assert result.warning is False


def test_difference_of_exactly_one_millisecond_is_accepted():
    pair, _, _ = make_pair(
        [make_frame(0), make_frame(50_000_000)],
        [make_frame(1_000_000), make_frame(60_000_000)],
    )

    result = capture_synced_pair(pair)

    assert result.timestamp_diff_ns == 1_000_000
    assert result.attempts == 1
    assert result.warning is False


def test_retakes_when_difference_exceeds_one_millisecond():
    first_left = [make_frame(0), make_frame(50_000_000)]
    first_right = [make_frame(1_000_001), make_frame(60_000_000)]
    second_left = [make_frame(100_000_000), make_frame(133_000_000)]
    second_right = [make_frame(100_000_500), make_frame(140_000_000)]
    pair, _, _ = make_pair(first_left + second_left, first_right + second_right)

    result = capture_synced_pair(pair)

    assert result.left is second_left[0]
    assert result.right is second_right[0]
    assert result.timestamp_diff_ns == 500
    assert result.attempts == 2
    assert result.warning is False


def test_succeeds_on_last_attempt():
    left_frames = [make_frame(t) for t in (0, 10_000_000, 20_000_000)]
    right_frames = [make_frame(t) for t in (5_000_000, 15_000_000, 20_000_000)]
    pair, _, _ = make_pair(left_frames, right_frames)

    result = capture_synced_pair(pair, frames_per_camera=1)

    assert result.left is left_frames[2]
    assert result.right is right_frames[2]
    assert result.attempts == 3
    assert result.warning is False


def test_returns_best_pair_with_warning_when_all_attempts_exceed():
    left_frames = [make_frame(t) for t in (0, 10_000_000, 20_000_000)]
    right_frames = [make_frame(t) for t in (5_000_000, 11_500_000, 23_000_000)]
    pair, _, _ = make_pair(left_frames, right_frames)

    result = capture_synced_pair(pair, frames_per_camera=1)

    assert result.left is left_frames[1]
    assert result.right is right_frames[1]
    assert result.timestamp_diff_ns == 1_500_000
    assert result.attempts == 3
    assert result.warning is True


def test_does_not_capture_more_than_max_attempts():
    left_frames = [make_frame(t * 10_000_000) for t in range(4)]
    right_frames = [make_frame(t * 10_000_000 + 2_000_000) for t in range(4)]
    pair, left, right = make_pair(left_frames, right_frames)

    capture_synced_pair(pair, frames_per_camera=1)

    assert remaining(left) == 1
    assert remaining(right) == 1


def test_stops_capturing_once_pair_is_within_tolerance():
    pair, left, right = make_pair(
        [make_frame(0), make_frame(10_000_000)],
        [make_frame(0), make_frame(10_000_000)],
    )

    capture_synced_pair(pair, frames_per_camera=1)

    assert remaining(left) == 1
    assert remaining(right) == 1


def test_interleaves_left_and_right_captures():
    order: list[str] = []

    class RecordingCamera(FakeCamera):
        def capture_frame(self) -> FakeFrame:
            order.append(self.camera_id)
            return super().capture_frame()

    left = RecordingCamera("left", frames=[make_frame(0), make_frame(1)])
    right = RecordingCamera("right", frames=[make_frame(0), make_frame(1)])
    pair = CameraPair(left=left, right=right)
    pair.start()

    capture_synced_pair(pair, frames_per_camera=2)

    assert order == ["left", "right", "left", "right"]


def test_respects_custom_tolerance_and_attempts():
    pair, _, _ = make_pair([make_frame(0)], [make_frame(2_000)])

    result = capture_synced_pair(
        pair, frames_per_camera=1, max_attempts=1, max_diff_ns=1_000
    )

    assert result.attempts == 1
    assert result.warning is True


def test_propagates_capture_errors():
    pair, _, _ = make_pair([make_frame(0)], [])

    with pytest.raises(RuntimeError):
        capture_synced_pair(pair, frames_per_camera=1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"frames_per_camera": 0},
        {"max_attempts": 0},
        {"max_diff_ns": -1},
    ],
)
def test_rejects_invalid_arguments(kwargs):
    pair, left, right = make_pair([make_frame(0)], [make_frame(0)])

    with pytest.raises(ValueError):
        capture_synced_pair(pair, **kwargs)

    assert remaining(left) == 1
    assert remaining(right) == 1
