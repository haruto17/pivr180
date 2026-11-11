import logging
from collections import deque

import pytest

from pivr180_device.atoms3.fake import FakeClock, FakeSerialLink, ScriptExhausted
from pivr180_device.button import RECONNECT_INTERVAL_S, SHUTDOWN_HOLD_S, ButtonShutter


class LinkOpener:
    def __init__(self, *links: FakeSerialLink | OSError) -> None:
        self._links: deque[FakeSerialLink | OSError] = deque(links)
        self.opened = 0

    def __call__(self) -> FakeSerialLink:
        if not self._links:
            raise AssertionError("no more fake links to open")
        link = self._links.popleft()
        if isinstance(link, OSError):
            raise link
        self.opened += 1
        return link


def make_shutter(clock: FakeClock, *links: FakeSerialLink | OSError) -> ButtonShutter:
    return ButtonShutter(LinkOpener(*links), clock=clock, sleep=clock.sleep)


def shot_times(shutter: ButtonShutter, clock: FakeClock) -> list[float]:
    times: list[float] = []
    try:
        for _ in shutter:
            times.append(clock.now)
    except ScriptExhausted:
        pass
    return times


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def test_short_press_shoots_once_on_release(clock: FakeClock):
    link = FakeSerialLink(clock, [(0.0, "press"), (0.5, "release")])
    shutter = make_shutter(clock, link)

    assert shot_times(shutter, clock) == [0.5]
    assert not shutter.shutdown_requested


def test_each_short_press_shoots(clock: FakeClock):
    link = FakeSerialLink(
        clock,
        [(0.0, "press"), (0.2, "release"), (5.0, "press"), (7.5, "release")],
    )
    shutter = make_shutter(clock, link)

    assert shot_times(shutter, clock) == [0.2, 7.5]
    assert not shutter.shutdown_requested


def test_holding_for_3_s_requests_shutdown_without_waiting_for_release(
    clock: FakeClock,
):
    link = FakeSerialLink(clock, [(0.0, "press"), (10.0, "release")])
    shutter = make_shutter(clock, link)

    assert shot_times(shutter, clock) == []
    assert shutter.shutdown_requested
    assert clock.now == SHUTDOWN_HOLD_S


@pytest.mark.parametrize(
    ("released_at", "shots", "shutdown"),
    [
        (2.99, [2.99], False),
        (3.0, [], True),
    ],
)
def test_release_just_before_3_s_shoots_and_at_3_s_shuts_down(
    clock: FakeClock, released_at: float, shots: list[float], shutdown: bool
):
    link = FakeSerialLink(clock, [(0.0, "press"), (released_at, "release")])
    shutter = make_shutter(clock, link)

    assert shot_times(shutter, clock) == shots
    assert shutter.shutdown_requested is shutdown


def test_long_press_is_measured_from_the_press_not_from_startup(clock: FakeClock):
    link = FakeSerialLink(clock, [(10.0, "press"), (12.5, "release")])
    shutter = make_shutter(clock, link)

    assert shot_times(shutter, clock) == [12.5]
    assert not shutter.shutdown_requested


def test_shutdown_is_requested_once_and_ends_the_triggers(clock: FakeClock):
    link = FakeSerialLink(
        clock,
        [(0.0, "press"), (0.5, "release"), (1.0, "press"), (9.0, "release")],
    )
    shutter = make_shutter(clock, link)

    assert shot_times(shutter, clock) == [0.5]
    assert shutter.shutdown_requested
    assert list(shutter) == []


def test_strips_a_trailing_carriage_return(clock: FakeClock):
    link = FakeSerialLink(clock, [(0.0, "press\r"), (0.5, "release\r")])

    assert shot_times(make_shutter(clock, link), clock) == [0.5]


@pytest.mark.parametrize("line", ["", "hello", "PRESS", "press ", "re lease", "\r"])
def test_ignores_unknown_lines(clock: FakeClock, line: str):
    link = FakeSerialLink(
        clock,
        [(0.0, line), (0.1, "press"), (0.2, line), (0.3, "release"), (0.4, line)],
    )

    assert shot_times(make_shutter(clock, link), clock) == [0.3]


def test_ignores_release_without_a_press(clock: FakeClock):
    link = FakeSerialLink(
        clock,
        [(0.0, "release"), (1.0, "press"), (1.5, "release"), (2.0, "release")],
    )

    assert shot_times(make_shutter(clock, link), clock) == [1.5]


def test_repeated_press_restarts_the_long_press(clock: FakeClock):
    link = FakeSerialLink(clock, [(0.0, "press"), (2.0, "press"), (4.5, "release")])
    shutter = make_shutter(clock, link)

    assert shot_times(shutter, clock) == [4.5]
    assert not shutter.shutdown_requested


def test_reconnects_after_a_disconnect_and_forgets_the_press(
    clock: FakeClock, caplog: pytest.LogCaptureFixture
):
    first = FakeSerialLink(clock, [(0.0, "press"), (1.0, OSError("unplugged"))])
    second = FakeSerialLink(clock, [(1.5, "release"), (2.0, "press"), (2.5, "release")])
    shutter = make_shutter(clock, first, second)

    with caplog.at_level(logging.WARNING, logger="pivr180_device.button"):
        assert shot_times(shutter, clock) == [2.5]

    assert first.closed
    assert not second.closed
    assert any("lost the button link" in r.getMessage() for r in caplog.records)


def test_hold_across_a_disconnect_does_not_shut_down(clock: FakeClock):
    first = FakeSerialLink(clock, [(0.0, "press"), (1.0, OSError("unplugged"))])
    second = FakeSerialLink(clock, [(10.0, "release")])
    shutter = make_shutter(clock, first, second)

    assert shot_times(shutter, clock) == []
    assert not shutter.shutdown_requested


def test_retries_opening_the_link_until_it_appears(
    clock: FakeClock, caplog: pytest.LogCaptureFixture
):
    link = FakeSerialLink(clock, [(5.0, "press"), (5.5, "release")])
    opener = LinkOpener(
        FileNotFoundError("no serial device matches /dev/serial/by-id/x"),
        FileNotFoundError("no serial device matches /dev/serial/by-id/x"),
        link,
    )
    shutter = ButtonShutter(opener, clock=clock, sleep=clock.sleep)

    with caplog.at_level(logging.INFO, logger="pivr180_device.button"):
        assert shot_times(shutter, clock) == [5.5]

    assert opener.opened == 1
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "/dev/serial/by-id/x" in warnings[0].getMessage()
    assert any("connected" in r.getMessage() for r in caplog.records)


def test_waits_the_reconnect_interval_between_attempts(clock: FakeClock):
    link = FakeSerialLink(clock, [(0.0, "press"), (0.0, "release")])
    shutter = make_shutter(clock, OSError("busy"), OSError("busy"), link)

    assert shot_times(shutter, clock) == [2 * RECONNECT_INTERVAL_S]


def test_context_exit_closes_the_link(clock: FakeClock):
    link = FakeSerialLink(clock, [(0.0, "press"), (0.5, "release"), (9.0, "press")])

    with make_shutter(clock, link) as shutter:
        next(iter(shutter))

    assert link.closed


def test_close_logs_link_close_errors_instead_of_raising(
    clock: FakeClock, caplog: pytest.LogCaptureFixture
):
    class FailingCloseLink(FakeSerialLink):
        def close(self) -> None:
            raise OSError("already gone")

    link = FailingCloseLink(clock, [(0.0, "press"), (0.5, "release")])
    shutter = make_shutter(clock, link)
    next(iter(shutter))

    with caplog.at_level(logging.WARNING, logger="pivr180_device.button"):
        shutter.close()

    [record] = caplog.records
    assert "failed to close" in record.getMessage()
    assert record.exc_info is not None
