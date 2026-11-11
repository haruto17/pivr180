import logging
import time
from collections.abc import Callable, Iterator
from typing import Self

from pivr180_device.atoms3.base import SerialLink

logger = logging.getLogger(__name__)

PRESS = "press"
RELEASE = "release"
SHUTDOWN_HOLD_S = 3.0
RECONNECT_INTERVAL_S = 1.0


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
        self._link: SerialLink | None = None
        self._pressed_at: float | None = None
        self.shutdown_requested = False

    def __iter__(self) -> Iterator[None]:
        while not self.shutdown_requested:
            link = self._connect()
            try:
                line = link.read_line()
            except OSError:
                logger.warning("lost the button link; reconnecting", exc_info=True)
                self.close()
                continue
            now = self._clock()
            if (
                self._pressed_at is not None
                and now - self._pressed_at >= self._shutdown_hold_s
            ):
                logger.info(
                    "button held for %.1f s; shutdown requested",
                    now - self._pressed_at,
                )
                self.shutdown_requested = True
                return
            if line is None:
                continue
            message = line.removesuffix("\r")
            if message == PRESS:
                self._pressed_at = now
            elif message == RELEASE:
                if self._pressed_at is None:
                    logger.debug("ignoring release without a press")
                    continue
                self._pressed_at = None
                yield
            else:
                logger.debug("ignoring unknown button message %r", message)

    def close(self) -> None:
        link, self._link = self._link, None
        # Not kept across links: a press seen before a disconnect has no
        # release to come, and the firmware does not resend the button state.
        self._pressed_at = None
        if link is None:
            return
        try:
            link.close()
        except OSError:
            logger.warning("failed to close the button link", exc_info=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _connect(self) -> SerialLink:
        failed = False
        while self._link is None:
            try:
                self._link = self._open_link()
            except OSError as error:
                if not failed:
                    logger.warning(
                        "button link unavailable (%s); retrying every %.1f s",
                        error,
                        self._reconnect_interval_s,
                    )
                    failed = True
                self._sleep(self._reconnect_interval_s)
        if failed:
            logger.info("button link connected")
        return self._link
