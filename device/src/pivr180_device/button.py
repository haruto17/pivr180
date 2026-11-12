import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from pivr180_device.atoms3.base import SerialLink

logger = logging.getLogger(__name__)

PRESS = "press"
RELEASE = "release"
SHUTDOWN_HOLD_S = 3.0
RECONNECT_INTERVAL_S = 1.0
STATUS_INTERVAL_S = 1.0


class Status(StrEnum):
    IDLE = "idle"
    CAPTURING = "capturing"
    ERROR = "error"


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
        status_interval_s: float = STATUS_INTERVAL_S,
    ) -> None:
        self._open_link = open_link
        self._clock = clock
        self._sleep = sleep
        self._shutdown_hold_s = shutdown_hold_s
        self._reconnect_interval_s = reconnect_interval_s
        self._status_interval_s = status_interval_s
        self._status_lock = threading.Lock()
        self._status: Status | None = None
        self._events: queue.Queue[_Shoot | _Shutdown | Exception] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None
        self._shutdown = threading.Event()
        self._done = False

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown.is_set()

    def show(self, status: Status) -> None:
        with self._status_lock:
            self._status = status

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
        while not self._done:
            if self._error is not None:
                raise self._error
            event = self._events.get()
            if isinstance(event, Exception):
                self._error = event
                raise event
            if isinstance(event, _Shutdown):
                self._done = True
                return
            yield event.released_at

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            return
        with self._status_lock:
            status, self._status = self._status, None
        if status is not None:
            # Not left unsent: without the reader, an error before it starts would
            # leave the AtomS3 Lite showing that it is still booting.
            self._show_once(status)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _read(self) -> None:
        link: SerialLink | None = None
        pressed_at: float | None = None
        failed = False
        sent: Status | None = None
        sent_at = 0.0
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
                    sent = None
                now = self._clock()
                status = self._due_status(sent, sent_at, now)
                try:
                    # Not written from the thread that calls show(): this thread
                    # reopens and closes the link, so it is the only one to use it.
                    if status is not None:
                        link.write_line(status)
                        sent, sent_at = status, now
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
                    # Not left to the consumer: an error in the capture under way
                    # would leave the loop before it reads this event.
                    self._shutdown.set()
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
                if self._stop.is_set():
                    self._flush_status(link, sent)
                _close_link(link)

    def _due_status(
        self, sent: Status | None, sent_at: float, now: float
    ) -> Status | None:
        with self._status_lock:
            status = self._status
        if status is None:
            return None
        if status != sent or now - sent_at >= self._status_interval_s:
            return status
        return None

    def _flush_status(self, link: SerialLink, sent: Status | None) -> None:
        with self._status_lock:
            status = self._status
        if status is None or status == sent:
            return
        try:
            link.write_line(status)
        except OSError:
            logger.warning(
                "failed to show %s on the AtomS3 Lite", status, exc_info=True
            )

    def _show_once(self, status: Status) -> None:
        try:
            link = self._open_link()
        except OSError as error:
            logger.warning("could not show %s on the AtomS3 Lite (%s)", status, error)
            return
        try:
            link.write_line(status)
        except OSError:
            logger.warning(
                "failed to show %s on the AtomS3 Lite", status, exc_info=True
            )
        finally:
            _close_link(link)


def _close_link(link: SerialLink) -> None:
    try:
        link.close()
    except OSError:
        logger.warning("failed to close the button link", exc_info=True)
