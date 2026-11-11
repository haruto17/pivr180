import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Self

from pivr180_device.atoms3.base import SerialLink

logger = logging.getLogger(__name__)

PRESS = "press"
RELEASE = "release"
SHUTDOWN_HOLD_S = 3.0
RECONNECT_INTERVAL_S = 1.0


@dataclass(frozen=True)
class _Shoot:
    released_at: float


@dataclass(frozen=True)
class _Shutdown:
    pass


class ButtonShutter:
    def __init__(
        self,
        open_link: Callable[[], SerialLink],
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        shutdown_hold_s: float = SHUTDOWN_HOLD_S,
        reconnect_interval_s: float = RECONNECT_INTERVAL_S,
    ) -> None:
        self._open_link = open_link
        self._clock = clock
        self._sleep = sleep
        self._shutdown_hold_s = shutdown_hold_s
        self._reconnect_interval_s = reconnect_interval_s
        self._events: queue.Queue[_Shoot | _Shutdown | Exception] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None
        self.shutdown_requested = False

    def start(self) -> None:
        if self._thread is not None:
            return
        # Not read from the consuming loop: a capture blocks it for seconds, and
        # lines read after it would be timed together, turning a hold into a
        # short press.
        self._thread = threading.Thread(
            target=self._read, name="button-reader", daemon=True
        )
        self._thread.start()

    def __iter__(self) -> Iterator[float]:
        self.start()
        while not self.shutdown_requested:
            if self._error is not None:
                raise self._error
            event = self._events.get()
            if isinstance(event, Exception):
                self._error = event
                raise event
            if isinstance(event, _Shutdown):
                self.shutdown_requested = True
                return
            yield event.released_at

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _read(self) -> None:
        link: SerialLink | None = None
        pressed_at: float | None = None
        failed = False
        try:
            while not self._stop.is_set():
                if link is None:
                    try:
                        link = self._open_link()
                    except OSError as error:
                        if not failed:
                            logger.warning(
                                "button link unavailable (%s); retrying every %.1f s",
                                error,
                                self._reconnect_interval_s,
                            )
                            failed = True
                        self._sleep(self._reconnect_interval_s)
                        continue
                    if failed:
                        logger.info("button link connected")
                        failed = False
                try:
                    line = link.read_line()
                except OSError:
                    logger.warning("lost the button link; reconnecting", exc_info=True)
                    _close_link(link)
                    link = None
                    # Not kept across links: a press seen before a disconnect has
                    # no release to come, and the firmware does not resend it.
                    pressed_at = None
                    self._sleep(self._reconnect_interval_s)
                    continue
                now = self._clock()
                if pressed_at is not None and now - pressed_at >= self._shutdown_hold_s:
                    logger.info(
                        "button held for %.1f s; shutdown requested", now - pressed_at
                    )
                    self._events.put(_Shutdown())
                    return
                if line is None:
                    continue
                message = line.removesuffix("\r")
                if message == PRESS:
                    pressed_at = now
                elif message == RELEASE:
                    if pressed_at is None:
                        logger.debug("ignoring release without a press")
                        continue
                    pressed_at = None
                    self._events.put(_Shoot(now))
                else:
                    logger.debug("ignoring unknown button message %r", message)
        # Not logged here: the consumer re-raises it, and main logs it once.
        except Exception as error:  # noqa: BLE001
            self._events.put(error)
        finally:
            if link is not None:
                _close_link(link)


def _close_link(link: SerialLink) -> None:
    try:
        link.close()
    except OSError:
        logger.warning("failed to close the button link", exc_info=True)
