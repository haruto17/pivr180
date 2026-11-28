import queue
import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

SHUTDOWN_PATH = "/api/shutdown"
SHUTDOWN_HEADER = "X-Pivr180-Request"
SHUTDOWN_HEADER_VALUE = "shutdown"


@dataclass(frozen=True)
class _Trigger:
    value: object


@dataclass(frozen=True)
class _End:
    pass


@dataclass(frozen=True)
class _Wake:
    pass


class ShutdownRequest:
    def __init__(self) -> None:
        self._requested = threading.Event()
        self._events: queue.Queue[_Trigger | _End | _Wake | BaseException] = (
            queue.Queue()
        )

    @property
    def requested(self) -> bool:
        return self._requested.is_set()

    def request(self) -> None:
        self._requested.set()
        self._events.put(_Wake())

    def trigger(self, value: object) -> None:
        self._events.put(_Trigger(value))

    def until_requested(self, triggers: Iterable[object]) -> Iterator[object]:
        # Not iterated here: reading stdin blocks with no way to interrupt it,
        # so a request made meanwhile would wait for the next line.
        # Not joined: the reader may stay blocked on a trigger that never comes,
        # and as a daemon it does not keep the process from exiting.
        threading.Thread(
            target=self._read, args=(triggers,), name="shutter-triggers", daemon=True
        ).start()
        while True:
            event = self._events.get()
            # Not checked against the event alone: triggers queued during a
            # capture arrive before the wake-up and must not shoot again.
            if self.requested or isinstance(event, _End):
                return
            if isinstance(event, BaseException):
                raise event
            if isinstance(event, _Trigger):
                yield event.value

    def _read(self, triggers: Iterable[object]) -> None:
        try:
            for trigger in triggers:
                self._events.put(_Trigger(trigger))
        # Not logged here: the consumer re-raises it, Ctrl+C included, and main
        # handles it as if it had been raised in its own thread.
        except BaseException as error:  # noqa: BLE001
            self._events.put(error)
        else:
            self._events.put(_End())


def shutdown_router(request_shutdown: Callable[[], None]) -> APIRouter:
    router = APIRouter()

    @router.post(SHUTDOWN_PATH, status_code=status.HTTP_202_ACCEPTED)
    def shutdown(
        x_pivr180_request: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        # Not an Origin check: the phone reaches the Pi as pivr180.local or by
        # IP, so comparing Origin with Host is fragile. A form cannot send a
        # custom header, and a cross-origin fetch with one needs a CORS
        # preflight, which this server never allows.
        if x_pivr180_request != SHUTDOWN_HEADER_VALUE:
            raise HTTPException(status.HTTP_403_FORBIDDEN)
        # Not powering off here: the capture under way has to end and the
        # cameras and the button have to be released first, which main does.
        request_shutdown()
        return {"status": "shutting down"}

    return router
