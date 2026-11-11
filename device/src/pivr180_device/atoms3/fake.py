from collections import deque
from collections.abc import Iterable


class ScriptExhausted(Exception):
    pass


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeSerialLink:
    def __init__(
        self,
        clock: FakeClock,
        script: Iterable[tuple[float, str | OSError]] = (),
        read_timeout_s: float = 0.25,
    ) -> None:
        self._clock = clock
        self._script: deque[tuple[float, str | OSError]] = deque(script)
        self._read_timeout_s = read_timeout_s
        self.closed = False

    def read_line(self) -> str | None:
        if self.closed:
            raise OSError("fake serial link is closed")
        if not self._script:
            raise ScriptExhausted("fake serial link has no scripted lines left")
        at, item = self._script[0]
        deadline = self._clock.now + self._read_timeout_s
        if at > deadline:
            self._clock.now = deadline
            return None
        self._script.popleft()
        self._clock.now = max(self._clock.now, at)
        if isinstance(item, OSError):
            raise item
        return item

    def close(self) -> None:
        self.closed = True
