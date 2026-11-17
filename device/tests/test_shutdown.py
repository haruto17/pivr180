import threading
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pivr180_device.shutdown import (
    SHUTDOWN_HEADER,
    SHUTDOWN_HEADER_VALUE,
    ShutdownRequest,
    shutdown_router,
)


class BlockingTriggers:
    def __init__(self, *triggers: object) -> None:
        self._triggers = triggers
        self.release = threading.Event()

    def __iter__(self) -> Iterator[object]:
        yield from self._triggers
        self.release.wait()


@pytest.fixture
def blocking() -> Iterator[BlockingTriggers]:
    triggers = BlockingTriggers("first", "second")
    yield triggers
    triggers.release.set()


def test_passes_triggers_through_until_they_end():
    request = ShutdownRequest()

    assert list(request.until_requested(["a", "b", "c"])) == ["a", "b", "c"]
    assert not request.requested


def test_request_ends_triggers_that_are_still_waiting(blocking: BlockingTriggers):
    request = ShutdownRequest()
    received: list[object] = []

    for trigger in request.until_requested(blocking):
        received.append(trigger)
        if trigger == "second":
            threading.Timer(0.01, request.request).start()

    assert received == ["first", "second"]
    assert request.requested


def test_triggers_queued_before_a_request_are_dropped(blocking: BlockingTriggers):
    request = ShutdownRequest()
    triggers = request.until_requested(blocking)

    assert next(triggers) == "first"
    request.request()

    assert list(triggers) == []


def test_request_made_before_iterating_yields_nothing(blocking: BlockingTriggers):
    request = ShutdownRequest()
    request.request()

    assert list(request.until_requested(blocking)) == []


def test_request_can_be_repeated(blocking: BlockingTriggers):
    request = ShutdownRequest()
    request.request()
    request.request()

    assert list(request.until_requested(blocking)) == []
    assert request.requested


def test_errors_from_the_triggers_are_raised_to_the_consumer():
    def failing() -> Iterator[object]:
        yield "first"
        raise OSError("button link lost")

    request = ShutdownRequest()
    triggers = request.until_requested(failing())

    assert next(triggers) == "first"
    with pytest.raises(OSError, match="button link lost"):
        next(triggers)


def test_ctrl_c_while_reading_triggers_is_raised_to_the_consumer():
    def interrupted() -> Iterator[object]:
        raise KeyboardInterrupt
        yield

    request = ShutdownRequest()

    with pytest.raises(KeyboardInterrupt):
        list(request.until_requested(interrupted()))


class RequestRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


def client_for(recorder: RequestRecorder) -> TestClient:
    app = FastAPI()
    app.include_router(shutdown_router(recorder))
    return TestClient(app)


def test_post_requests_a_shutdown_and_accepts():
    recorder = RequestRecorder()

    response = client_for(recorder).post(
        "/api/shutdown", headers={SHUTDOWN_HEADER: SHUTDOWN_HEADER_VALUE}
    )

    assert response.status_code == 202
    assert response.json() == {"status": "shutting down"}
    assert recorder.calls == 1


def test_post_without_the_request_header_is_forbidden():
    recorder = RequestRecorder()

    response = client_for(recorder).post("/api/shutdown")

    assert response.status_code == 403
    assert recorder.calls == 0


def test_post_with_a_wrong_request_header_is_forbidden():
    recorder = RequestRecorder()

    response = client_for(recorder).post(
        "/api/shutdown", headers={SHUTDOWN_HEADER: "capture"}
    )

    assert response.status_code == 403
    assert recorder.calls == 0


def test_get_does_not_request_a_shutdown():
    recorder = RequestRecorder()

    response = client_for(recorder).get("/api/shutdown")

    assert response.status_code == 405
    assert recorder.calls == 0
