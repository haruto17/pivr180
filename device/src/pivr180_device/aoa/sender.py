import logging
import threading
from collections import deque
from typing import Self

from pivr180_device.aoa.frame import Frame, FrameError
from pivr180_device.aoa.link import Connection

logger = logging.getLogger(__name__)


class Delivery:
    def __init__(self) -> None:
        self._done = threading.Event()
        self._sent = False

    @property
    def sent(self) -> bool:
        return self._done.is_set() and self._sent

    def wait(self, timeout_s: float) -> bool:
        return self._done.wait(timeout_s)

    def finish(self, sent: bool) -> None:
        self._sent = sent
        self._done.set()


class FrameSender:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._state = threading.Condition()
        self._frames: deque[tuple[Frame, Delivery]] = deque()
        self._preview: Frame | None = None
        self._closed = False
        # Not written from the threads that make the frames: a phone that stops
        # reading blocks a write for up to its timeout, which would stall the
        # link's reads, the requests and the capture loop's status updates.
        self._thread = threading.Thread(
            target=self._run, name="aoa-sender", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def send(self, frame: Frame) -> Delivery:
        delivery = Delivery()
        with self._state:
            if self._closed:
                delivery.finish(sent=False)
                return delivery
            self._frames.append((frame, delivery))
            self._state.notify()
        return delivery

    def send_preview(self, frame: Frame) -> None:
        with self._state:
            if self._closed:
                return
            # Not queued behind the previous one: while the phone is slow to read,
            # an older preview is worth nothing once a newer one exists.
            self._preview = frame
            self._state.notify()

    def drop_preview(self) -> None:
        with self._state:
            self._preview = None

    def close(self) -> None:
        with self._state:
            self._discard()
            self._state.notify()
        if self._thread.ident is not None:
            self._thread.join()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _discard(self) -> None:
        self._closed = True
        for _, delivery in self._frames:
            delivery.finish(sent=False)
        self._frames.clear()
        self._preview = None

    def _next(self) -> tuple[Frame, Delivery | None] | None:
        with self._state:
            self._state.wait_for(
                lambda: self._closed or self._frames or self._preview is not None
            )
            if self._closed:
                return None
            if self._frames:
                return self._frames.popleft()
            frame, self._preview = self._preview, None
            return frame, None

    def _run(self) -> None:
        while (item := self._next()) is not None:
            frame, delivery = item
            sent = False
            try:
                self._connection.send(frame)
                sent = True
            except FrameError:
                logger.exception(
                    "could not send a %s frame to %s",
                    frame.kind.name,
                    self._connection.name,
                )
            except OSError as error:
                # Not retried: the link sees the broken connection and reconnects,
                # and this sender goes with the session.
                logger.warning(
                    "stopped sending to %s (%s)", self._connection.name, error
                )
                with self._state:
                    self._discard()
                return
            finally:
                if delivery is not None:
                    delivery.finish(sent)
