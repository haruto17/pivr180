import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Protocol

from pivr180_device import __version__
from pivr180_device.aoa.frame import (
    PROTOCOL_VERSION,
    Frame,
    FrameKind,
    json_frame,
    preview_frame,
    thumbnail_frame,
)
from pivr180_device.aoa.link import Connection
from pivr180_device.aoa.messages import (
    PHOTO_MODE,
    ErrorCode,
    InvalidRequestError,
    Request,
    error_message,
    parse_request,
)
from pivr180_device.aoa.sender import FrameSender
from pivr180_device.camera_settings import CameraSettingsControl, CamerasNotReadyError
from pivr180_device.captures_api import capture_thumbnail, summarize_captures
from pivr180_device.preview import MAX_FPS
from pivr180_device.slot import CameraSlot
from pivr180_device.status import StatusBoard, StatusMessage
from pivr180_device.storage import CaptureNotFoundError, CaptureStorage

logger = logging.getLogger(__name__)

PREVIEW_INTERVAL_S = 1 / MAX_FPS


class Pacer(Protocol):
    def wait(self, seconds: float) -> None: ...

    def interrupt(self) -> None: ...


class EventPacer:
    def __init__(self) -> None:
        self._interrupted = threading.Event()

    def wait(self, seconds: float) -> None:
        self._interrupted.wait(seconds)

    def interrupt(self) -> None:
        self._interrupted.set()


@dataclass(frozen=True)
class AoaServices:
    slot: CameraSlot
    storage: CaptureStorage
    settings: CameraSettingsControl
    board: StatusBoard
    preview: Callable[[], bytes | None]
    shutter: Callable[[], None]
    request_shutdown: Callable[[], None]
    software_version: str = __version__


class PreviewStream:
    def __init__(
        self,
        preview: Callable[[], bytes | None],
        sender: FrameSender,
        name: str,
        pacer: Pacer,
        interval_s: float = PREVIEW_INTERVAL_S,
    ) -> None:
        self._preview = preview
        self._sender = sender
        self._name = name
        self._pacer = pacer
        self._interval_s = interval_s
        self._state = threading.Condition()
        self._streaming = False
        self._closed = False
        # Not run on the link's thread: encoding a JPEG takes tens of ms, and the
        # link has to keep reading the app's requests meanwhile.
        self._thread = threading.Thread(
            target=self._run, name="aoa-preview", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def resume(self) -> None:
        with self._state:
            self._streaming = True
            self._state.notify()

    def pause(self) -> None:
        with self._state:
            self._streaming = False

    def close(self) -> None:
        with self._state:
            self._closed = True
            self._state.notify()
        self._pacer.interrupt()
        if self._thread.ident is not None:
            self._thread.join()

    def _wait_until_streaming(self) -> bool:
        with self._state:
            self._state.wait_for(lambda: self._closed or self._streaming)
            return not self._closed

    def _run(self) -> None:
        failing = False
        while self._wait_until_streaming():
            try:
                jpeg = self._preview()
            # Not ending the stream: the camera may recover, and the capture
            # loop decides what a camera error means for shooting.
            except Exception:
                if not failing:
                    logger.exception(
                        "preview for %s failed; retrying every %.1f s",
                        self._name,
                        self._interval_s,
                    )
                    failing = True
                jpeg = None
            else:
                if failing:
                    logger.info("preview for %s is back", self._name)
                    failing = False
            if jpeg is not None:
                self._sender.send_preview(preview_frame(jpeg))
            # Not shortened by the time taken to encode: the shared preview would
            # then often hand back the JPEG it has just sent.
            self._pacer.wait(self._interval_s)


Job = Callable[[], None]


class RequestWorker:
    def __init__(self) -> None:
        self._state = threading.Condition()
        self._jobs: deque[Job] = deque()
        self._closed = False
        # Not run on the link's thread: these requests read or delete files, or
        # wait for a shot under way, and the link has to keep reading meanwhile.
        self._thread = threading.Thread(
            target=self._run, name="aoa-requests", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def submit(self, job: Job) -> None:
        with self._state:
            if self._closed:
                return
            self._jobs.append(job)
            self._state.notify()

    def close(self) -> None:
        with self._state:
            self._closed = True
            # Not run after the connection is gone: nobody would get the answers.
            self._jobs.clear()
            self._state.notify()
        if self._thread.ident is not None:
            self._thread.join()

    def _next(self) -> Job | None:
        with self._state:
            self._state.wait_for(lambda: self._closed or self._jobs)
            if self._closed:
                return None
            return self._jobs.popleft()

    def _run(self) -> None:
        while (job := self._next()) is not None:
            job()


class Phase(Enum):
    AWAITING_HELLO = auto()
    READY = auto()
    REJECTED = auto()


class AoaSession:
    def __init__(
        self,
        connection: Connection,
        services: AoaServices,
        *,
        pacer: Pacer | None = None,
    ) -> None:
        self._name = connection.name
        self._services = services
        self._phase = Phase.AWAITING_HELLO
        self._unsubscribe: Callable[[], None] | None = None
        self._sender = FrameSender(connection)
        self._preview = PreviewStream(
            services.preview,
            self._sender,
            connection.name,
            EventPacer() if pacer is None else pacer,
        )
        self._requests = RequestWorker()
        self._sender.start()
        self._preview.start()
        self._requests.start()

    def on_frame(self, frame: Frame) -> None:
        if frame.kind != FrameKind.JSON:
            self._reject(f"a {frame.kind.name} frame is not a request")
            return
        try:
            request = parse_request(frame.payload)
        except InvalidRequestError as error:
            self._reject(str(error), error.request_id)
            return
        logger.info("received %s (id %d) from %s", request.type, request.id, self._name)
        if self._phase == Phase.REJECTED:
            logger.info(
                "ignoring %s from %s after a protocol version mismatch",
                request.type,
                self._name,
            )
            return
        if request.type == "hello":
            self._hello(request)
            return
        if self._phase == Phase.AWAITING_HELLO:
            self._error(request, ErrorCode.HANDSHAKE_REQUIRED, "send hello first")
            return
        self._handle(request)

    def on_close(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
        self._preview.close()
        self._requests.close()
        self._sender.close()

    def _hello(self, request: Request) -> None:
        version = request.fields["protocol_version"]
        if version != PROTOCOL_VERSION:
            logger.warning(
                "%s speaks protocol version %d, device speaks %d",
                self._name,
                version,
                PROTOCOL_VERSION,
            )
            self._phase = Phase.REJECTED
            self._preview.pause()
            if self._unsubscribe is not None:
                self._unsubscribe()
                self._unsubscribe = None
            self._error(
                request,
                ErrorCode.UNSUPPORTED_PROTOCOL_VERSION,
                f"device speaks protocol version {PROTOCOL_VERSION}, "
                f"app speaks {version}",
            )
            return
        logger.info("%s runs app version %s", self._name, request.fields["app_version"])
        self._send(
            {
                "type": "welcome",
                "id": request.id,
                "protocol_version": PROTOCOL_VERSION,
                "software_version": self._services.software_version,
            }
        )
        if self._unsubscribe is not None:
            self._unsubscribe()
        self._unsubscribe = self._services.board.subscribe(self._send_status)
        if self._phase == Phase.AWAITING_HELLO:
            self._preview.resume()
        self._phase = Phase.READY

    def _handle(self, request: Request) -> None:
        match request.type:
            case "shutter":
                self._shutter(request)
            case "get_settings":
                self._send_settings(request)
            case "get_mode" | "set_mode":
                self._send({"type": "mode", "id": request.id, "mode": PHOTO_MODE})
            case "shutdown":
                self._ok(request)
                logger.info("%s asked to shut down", self._name)
                # Not powering off here: main does it once the capture under way
                # has ended and the cameras and the button are released.
                self._services.request_shutdown()
            case "stop_preview":
                self._preview.pause()
                self._ok(request)
            case "start_preview":
                self._ok(request)
                self._preview.resume()
            case "set_settings":
                self._later(request, self._set_settings)
            case "list_captures":
                self._later(request, self._list_captures)
            case "get_thumbnail":
                self._later(request, self._get_thumbnail)
            case "delete_capture":
                self._later(request, self._delete_capture)
            case _:
                self._error(
                    request,
                    ErrorCode.INTERNAL_ERROR,
                    f"{request.type} is not handled",
                )

    def _shutter(self, request: Request) -> None:
        if not self._services.slot.ready:
            self._error(request, ErrorCode.CAMERAS_NOT_READY, "cameras are not ready")
            return
        self._services.shutter()
        self._ok(request)

    def _send_settings(self, request: Request) -> None:
        settings = self._services.settings.current
        self._send(
            {"type": "settings", "id": request.id, "settings": settings.model_dump()}
        )

    def _set_settings(self, request: Request) -> None:
        try:
            self._services.settings.apply(request.fields["settings"])
        except CamerasNotReadyError as error:
            self._error(request, ErrorCode.CAMERAS_NOT_READY, str(error))
            return
        self._send_settings(request)

    def _list_captures(self, request: Request) -> None:
        captures = summarize_captures(self._services.storage)
        self._send({"type": "captures", "id": request.id, "captures": captures})

    def _get_thumbnail(self, request: Request) -> None:
        capture_id = request.fields["capture_id"]
        side = request.fields["side"]
        try:
            jpeg = capture_thumbnail(self._services.storage, capture_id, side)
        except (CaptureNotFoundError, FileNotFoundError):
            self._error(
                request,
                ErrorCode.CAPTURE_NOT_FOUND,
                f"no {side} image in capture {capture_id}",
            )
            return
        self._sender.send(thumbnail_frame(request.id, jpeg))

    def _delete_capture(self, request: Request) -> None:
        capture_id = request.fields["capture_id"]
        try:
            self._services.storage.delete_capture(capture_id)
        except CaptureNotFoundError:
            self._error(
                request, ErrorCode.CAPTURE_NOT_FOUND, f"no capture {capture_id}"
            )
            return
        logger.info("deleted %s for %s", capture_id, self._name)
        self._ok(request)
        self._services.board.deleted(capture_id)

    def _later(self, request: Request, handle: Callable[[Request], None]) -> None:
        def job() -> None:
            try:
                handle(request)
            # Not left to end the worker: the app is owed an answer, and the
            # next request may well succeed.
            except Exception as error:
                logger.exception(
                    "failed to handle %s (id %d) from %s",
                    request.type,
                    request.id,
                    self._name,
                )
                self._error(
                    request,
                    ErrorCode.INTERNAL_ERROR,
                    f"{request.type} failed: {str(error) or type(error).__name__}",
                )

        self._requests.submit(job)

    def _send_status(self, status: StatusMessage) -> None:
        self._send(status)

    def _ok(self, request: Request) -> None:
        self._send({"type": "ok", "id": request.id})

    def _error(self, request: Request, code: ErrorCode, message: str) -> None:
        self._send(error_message(code, message, request.id))

    def _reject(self, message: str, request_id: int | None = None) -> None:
        logger.warning("invalid request from %s: %s", self._name, message)
        if self._phase == Phase.REJECTED:
            return
        self._send(error_message(ErrorCode.INVALID_MESSAGE, message, request_id))

    def _send(self, message: dict[str, Any]) -> None:
        self._sender.send(json_frame(message))
