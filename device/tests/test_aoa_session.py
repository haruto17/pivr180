import io
import json
import logging
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from PIL import Image
from referencing import Registry, Resource

from pivr180_device.aoa.fake import GatedAccessoryPort
from pivr180_device.aoa.frame import (
    PROTOCOL_VERSION,
    THUMBNAIL_ID,
    Frame,
    FrameDecoder,
    FrameKind,
    json_frame,
    preview_frame,
)
from pivr180_device.aoa.link import Connection
from pivr180_device.aoa.session import (
    PREVIEW_INTERVAL_S,
    SHUTDOWN_OK_TIMEOUT_S,
    AoaServices,
    AoaSession,
    PreviewStream,
)
from pivr180_device.button import Status
from pivr180_device.camera import CameraPair, FrameMetadata
from pivr180_device.camera.fake import FakeCamera, FakeFrame
from pivr180_device.camera_settings import (
    CameraSettings,
    CameraSettingsControl,
    SettingsFile,
)
from pivr180_device.exposure import ExposureSettings, ExposureSync
from pivr180_device.preview import PreviewFrames
from pivr180_device.slot import CameraSlot, LiveCameras
from pivr180_device.status import StatusBoard
from pivr180_device.storage import CaptureStorage

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"
REQUEST_EXAMPLES_DIR = SCHEMA_DIR / "examples" / "aoa" / "app_to_device"
FREE = 52_613_349_376
SHOWN_CAPTURE = "20261126-031522-000"
DELETED_CAPTURE = "20261125-224001-001"
SESSION_THREADS = {"aoa-sender", "aoa-preview", "aoa-requests"}
ANSWERS = {
    "hello": "welcome",
    "shutter": "ok",
    "get_settings": "settings",
    "set_settings": "settings",
    "get_mode": "mode",
    "set_mode": "mode",
    "list_captures": "captures",
    "get_thumbnail": "thumbnail",
    "delete_capture": "ok",
    "shutdown": "ok",
    "stop_preview": "ok",
    "start_preview": "ok",
}


def example(name: str) -> dict[str, Any]:
    return json.loads((REQUEST_EXAMPLES_DIR / f"{name}.json").read_text("utf-8"))


REQUEST_EXAMPLES = [
    pytest.param(path.stem, id=path.stem)
    for path in sorted(REQUEST_EXAMPLES_DIR.glob("*.json"))
    if path.stem != "hello"
]


@pytest.fixture(scope="module")
def device_message() -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / "aoa.schema.json").read_text("utf-8"))
    registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(
        {"$ref": f"{schema['$id']}#/$defs/device_message"}, registry=registry
    )


class ManualPacer:
    def __init__(self) -> None:
        self._state = threading.Condition()
        self._ticks = 0
        self._interrupted = False
        self.waits: list[float] = []

    def wait(self, seconds: float) -> None:
        with self._state:
            self.waits.append(seconds)
            self._state.notify_all()
            self._state.wait_for(lambda: self._ticks > 0 or self._interrupted)
            if self._ticks > 0:
                self._ticks -= 1

    def interrupt(self) -> None:
        with self._state:
            self._interrupted = True
            self._state.notify_all()

    def tick(self) -> None:
        with self._state:
            self._ticks += 1
            self._state.notify_all()

    def wait_for_waits(self, count: int, timeout_s: float = 5.0) -> bool:
        with self._state:
            return self._state.wait_for(lambda: len(self.waits) >= count, timeout_s)


class RecordingSender:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def send_preview(self, frame: Frame) -> None:
        self.calls.append("send_preview")

    def drop_preview(self) -> None:
        self.calls.append("drop_preview")


def decode(written: list[bytes]) -> list[Frame]:
    return FrameDecoder().feed(b"".join(written))


def messages(written: list[bytes]) -> list[dict[str, Any]]:
    return [
        json.loads(frame.payload)
        for frame in decode(written)
        if frame.kind == FrameKind.JSON
    ]


def previews(written: list[bytes]) -> list[Frame]:
    return [frame for frame in decode(written) if frame.kind == FrameKind.PREVIEW]


def answer(frame: Frame) -> tuple[str, int | None]:
    if frame.kind == FrameKind.THUMBNAIL:
        return "thumbnail", THUMBNAIL_ID.unpack_from(frame.payload)[0]
    if frame.kind == FrameKind.JSON:
        message = json.loads(frame.payload)
        return message["type"], message.get("id")
    return "preview", None


def jpeg_bytes(size: tuple[int, int] = (64, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 100, 50)).save(buffer, format="JPEG")
    return buffer.getvalue()


def make_capture(root: Path, capture_id: str, *, sync_warning: bool) -> Path:
    directory = root / capture_id
    directory.mkdir(parents=True)
    (directory / "left.jpg").write_bytes(jpeg_bytes())
    (directory / "right.jpg").write_bytes(jpeg_bytes())
    (directory / "meta.json").write_text(
        json.dumps({"sync": {"warning": sync_warning}}), encoding="utf-8"
    )
    return directory


def metadata() -> FakeFrame:
    return FakeFrame(
        FrameMetadata(
            sensor_timestamp_ns=0,
            exposure_time_us=10_000,
            analogue_gain=1.0,
            colour_gains=(2.0, 1.5),
        )
    )


@dataclass
class Rig:
    port: GatedAccessoryPort
    pacer: ManualPacer
    slot: CameraSlot
    storage: CaptureStorage
    board: StatusBoard
    left: FakeCamera
    right: FakeCamera
    exposure: ExposureSync
    services: AoaServices
    shutters: list[None] = field(default_factory=list)
    shutdowns: list[None] = field(default_factory=list)
    sessions: list[AoaSession] = field(default_factory=list)

    def open(
        self,
        *,
        shutdown_ok_timeout_s: float = SHUTDOWN_OK_TIMEOUT_S,
        **changes: Any,
    ) -> AoaSession:
        services = self.services
        for name, value in changes.items():
            services = _replace(services, name, value)
        session = AoaSession(
            Connection(self.port, "fake phone"),
            services,
            pacer=self.pacer,
            shutdown_ok_timeout_s=shutdown_ok_timeout_s,
        )
        self.sessions.append(session)
        return session

    def frames(self) -> list[Frame]:
        return decode(self.port.written)

    def messages(self) -> list[dict[str, Any]]:
        return messages(self.port.written)

    def wait_for_answer(self, kind: str, request_id: int) -> Frame:
        def answered(written: list[bytes]) -> bool:
            return any(answer(frame) == (kind, request_id) for frame in decode(written))

        assert self.port.wait_until(answered), (kind, request_id, self.messages())
        return next(
            frame for frame in self.frames() if answer(frame) == (kind, request_id)
        )

    def wait_for_message(self, predicate: Callable[[dict[str, Any]], bool]) -> None:
        assert self.port.wait_until(
            lambda written: any(predicate(message) for message in messages(written))
        ), self.messages()

    def wait_for_previews(self, count: int) -> None:
        assert self.port.wait_until(lambda written: len(previews(written)) >= count)

    def handshake(self, session: AoaSession) -> None:
        session.on_frame(json_frame(example("hello")))
        self.wait_for_answer("welcome", 1)
        self.wait_for_message(lambda message: message["type"] == "status")


def _replace(services: AoaServices, name: str, value: Any) -> AoaServices:
    fields = {key: getattr(services, key) for key in services.__dataclass_fields__}
    fields[name] = value
    return AoaServices(**fields)


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    root = tmp_path / "captures"
    make_capture(root, DELETED_CAPTURE, sync_warning=True)
    make_capture(root, SHOWN_CAPTURE, sync_warning=False)
    storage = CaptureStorage(root)
    left = FakeCamera("left", frames=[metadata()], preview_size=(640, 480))
    right = FakeCamera("right", frames=[metadata()], preview_size=(640, 480))
    pair = CameraPair(left=left, right=right)
    pair.start()
    exposure = ExposureSync(pair, settle_frames=0, stable_frames=1)
    slot = CameraSlot()
    board = StatusBoard(storage, measure_free_bytes=lambda path: FREE)
    rig = Rig(
        port=GatedAccessoryPort(),
        pacer=ManualPacer(),
        slot=slot,
        storage=storage,
        board=board,
        left=left,
        right=right,
        exposure=exposure,
        services=None,  # type: ignore[arg-type]
    )
    rig.services = AoaServices(
        slot=slot,
        storage=storage,
        settings=CameraSettingsControl(slot),
        board=board,
        # Not cached by time: the tests count each preview the cameras take.
        preview=PreviewFrames(slot, min_interval_s=0).latest,
        shutter=lambda: rig.shutters.append(None),
        request_shutdown=lambda: rig.shutdowns.append(None),
        software_version="0.1.0",
    )
    with slot.attach(LiveCameras(pair=pair, exposure=exposure)):
        try:
            yield rig
        finally:
            for session in rig.sessions:
                session.on_close()


def session_threads() -> set[str]:
    return {
        thread.name
        for thread in threading.enumerate()
        if thread.name in SESSION_THREADS and thread.is_alive()
    }


def test_answers_hello_with_welcome_then_status_then_previews(
    rig: Rig, device_message: Draft202012Validator
):
    session = rig.open()

    session.on_frame(json_frame(example("hello")))
    rig.wait_for_previews(1)

    welcome, status = rig.messages()
    assert welcome == {
        "type": "welcome",
        "id": 1,
        "protocol_version": PROTOCOL_VERSION,
        "software_version": "0.1.0",
    }
    assert status == {
        "type": "status",
        "state": "idle",
        "capture_count": 2,
        "free_bytes": FREE,
        "last_capture": None,
    }
    for message in (welcome, status):
        device_message.validate(message)
    [preview] = previews(rig.port.written)
    with Image.open(io.BytesIO(preview.payload)) as image:
        assert image.format == "JPEG"
        assert image.size == (1280, 480)


def test_sends_previews_at_most_five_times_a_second(rig: Rig):
    session = rig.open()
    rig.handshake(session)

    for count in range(1, 4):
        assert rig.pacer.wait_for_waits(count)
        rig.pacer.tick()
    rig.wait_for_previews(3)

    assert PREVIEW_INTERVAL_S == pytest.approx(0.2)
    assert set(rig.pacer.waits) == {PREVIEW_INTERVAL_S}


def test_every_request_example_has_an_expected_answer():
    assert {
        example(path.stem)["type"] for path in REQUEST_EXAMPLES_DIR.glob("*.json")
    } == set(ANSWERS)


@pytest.mark.parametrize("name", REQUEST_EXAMPLES)
def test_answers_every_request_example(
    rig: Rig, device_message: Draft202012Validator, name: str
):
    request = example(name)
    session = rig.open()
    rig.handshake(session)

    session.on_frame(json_frame(request))
    frame = rig.wait_for_answer(ANSWERS[request["type"]], request["id"])

    if frame.kind == FrameKind.THUMBNAIL:
        with Image.open(io.BytesIO(frame.payload[THUMBNAIL_ID.size :])) as image:
            assert image.format == "JPEG"
    else:
        device_message.validate(json.loads(frame.payload))


def test_shutter_joins_the_shutter_triggers(rig: Rig):
    session = rig.open()
    rig.handshake(session)

    session.on_frame(json_frame(example("shutter")))
    rig.wait_for_answer("ok", 2)

    assert rig.shutters == [None]


def test_settings_are_applied_to_both_cameras_and_read_back(rig: Rig):
    session = rig.open()
    rig.handshake(session)

    session.on_frame(json_frame(example("set_settings")))
    applied = json.loads(rig.wait_for_answer("settings", 4).payload)
    session.on_frame(json_frame(example("get_settings")))
    read = json.loads(rig.wait_for_answer("settings", 3).payload)

    expected = {"exposure_value": -0.5, "white_balance": "daylight", "contrast": 1.2}
    assert applied["settings"] == expected
    assert read["settings"] == expected
    controls = {"ExposureValue": -0.5, "AwbMode": 5, "Contrast": 1.2}
    assert rig.left.controls == controls
    assert rig.right.controls == controls


def test_settings_set_from_the_app_are_saved_for_the_next_start(
    rig: Rig, tmp_path: Path
):
    file = SettingsFile(tmp_path / "camera_settings.json")
    session = rig.open(settings=CameraSettingsControl(rig.slot, file))
    rig.handshake(session)

    session.on_frame(json_frame(example("set_settings")))
    rig.wait_for_answer("settings", 4)

    assert file.load() == CameraSettings(
        exposure_value=-0.5, white_balance="daylight", contrast=1.2
    )


def test_mode_is_photo(rig: Rig):
    session = rig.open()
    rig.handshake(session)

    session.on_frame(json_frame(example("get_mode")))
    session.on_frame(json_frame(example("set_mode")))

    for request_id in (5, 6):
        frame = rig.wait_for_answer("mode", request_id)
        assert json.loads(frame.payload)["mode"] == "photo"


def test_lists_captures_newest_first(rig: Rig):
    session = rig.open()
    rig.handshake(session)

    session.on_frame(json_frame(example("list_captures")))
    frame = rig.wait_for_answer("captures", 7)

    assert json.loads(frame.payload)["captures"] == [
        {"id": SHOWN_CAPTURE, "complete": True, "sync_warning": False},
        {"id": DELETED_CAPTURE, "complete": True, "sync_warning": True},
    ]


@pytest.mark.parametrize("side", ["left", "right"])
def test_thumbnail_is_a_small_jpeg_of_the_side(rig: Rig, side: str):
    (rig.storage.root / SHOWN_CAPTURE / f"{side}.jpg").write_bytes(
        jpeg_bytes((960, 720))
    )
    session = rig.open()
    rig.handshake(session)

    session.on_frame(json_frame({**example("get_thumbnail"), "side": side}))
    frame = rig.wait_for_answer("thumbnail", 8)

    with Image.open(io.BytesIO(frame.payload[THUMBNAIL_ID.size :])) as image:
        assert image.size == (480, 360)


def test_deleting_a_capture_answers_ok_then_updates_the_status(rig: Rig):
    session = rig.open()
    rig.handshake(session)

    session.on_frame(json_frame(example("delete_capture")))
    rig.wait_for_message(
        lambda message: message["type"] == "status" and message["capture_count"] == 1
    )

    assert not (rig.storage.root / DELETED_CAPTURE).exists()
    assert [(message["type"], message.get("id")) for message in rig.messages()] == [
        ("welcome", 1),
        ("status", None),
        ("ok", 9),
        ("status", None),
    ]


@pytest.mark.parametrize(
    "request_",
    [
        pytest.param(
            {"type": "delete_capture", "id": 9, "capture_id": "20200101-000000-000"},
            id="delete_unknown",
        ),
        pytest.param(
            {
                "type": "get_thumbnail",
                "id": 9,
                "capture_id": "20200101-000000-000",
                "side": "left",
            },
            id="thumbnail_of_unknown",
        ),
    ],
)
def test_unknown_captures_are_not_found(
    rig: Rig, device_message: Draft202012Validator, request_: dict[str, Any]
):
    session = rig.open()
    rig.handshake(session)

    session.on_frame(json_frame(request_))
    error = json.loads(rig.wait_for_answer("error", 9).payload)

    assert error["code"] == "capture_not_found"
    device_message.validate(error)


def test_thumbnail_of_a_missing_side_is_not_found(rig: Rig):
    (rig.storage.root / SHOWN_CAPTURE / "right.jpg").unlink()
    session = rig.open()
    rig.handshake(session)

    session.on_frame(json_frame({**example("get_thumbnail"), "side": "right"}))
    error = json.loads(rig.wait_for_answer("error", 8).payload)

    assert error["code"] == "capture_not_found"
    assert error["message"] == f"no right image in capture {SHOWN_CAPTURE}"


def test_shutdown_answers_ok_and_asks_main_to_power_off(rig: Rig):
    session = rig.open()
    rig.handshake(session)

    session.on_frame(json_frame(example("shutdown")))
    rig.wait_for_answer("ok", 10)

    assert rig.shutdowns == [None]


def test_shutdown_is_asked_for_only_once_the_ok_is_written(rig: Rig):
    written_by_then: list[list[dict[str, Any]]] = []
    session = rig.open(request_shutdown=lambda: written_by_then.append(rig.messages()))
    rig.handshake(session)

    session.on_frame(json_frame(example("shutdown")))

    [messages_then] = written_by_then
    assert messages_then[-1] == {"type": "ok", "id": 10}


def test_shutdown_goes_ahead_when_the_phone_does_not_take_the_ok_in_time(
    rig: Rig, caplog: pytest.LogCaptureFixture
):
    session = rig.open(shutdown_ok_timeout_s=0)
    rig.handshake(session)
    rig.port.hold()
    try:
        with caplog.at_level(logging.WARNING):
            session.on_frame(json_frame(example("shutdown")))

        assert rig.shutdowns == [None]
        assert {"type": "ok", "id": 10} not in rig.messages()
        assert "could not send the shutdown ok to fake phone within 0.0 s" in (
            caplog.text
        )
    finally:
        rig.port.release()


def test_shutdown_goes_ahead_when_the_ok_cannot_be_written(
    rig: Rig, caplog: pytest.LogCaptureFixture
):
    session = rig.open()
    rig.handshake(session)
    rig.port.write_error = OSError("pipe error")

    with caplog.at_level(logging.WARNING):
        session.on_frame(json_frame(example("shutdown")))

    assert rig.shutdowns == [None]
    assert "could not send the shutdown ok to fake phone; shutting down" in (
        caplog.text
    )


def test_status_changes_are_sent_after_the_handshake(rig: Rig):
    session = rig.open()
    rig.board.show(Status.CAPTURING)
    rig.handshake(session)

    rig.board.show(Status.ERROR, "capture failed: disk full")
    rig.wait_for_message(lambda message: message.get("state") == "error")

    statuses = [m for m in rig.messages() if m["type"] == "status"]
    assert [status["state"] for status in statuses] == ["capturing", "error"]
    assert statuses[1]["error_message"] == "capture failed: disk full"


def test_stop_preview_stops_taking_previews(rig: Rig):
    session = rig.open()
    rig.handshake(session)
    rig.wait_for_previews(1)

    session.on_frame(json_frame(example("stop_preview")))
    rig.wait_for_answer("ok", 11)
    rig.pacer.tick()
    session.on_close()

    assert len(previews(rig.port.written)) == 1
    assert (rig.left.previews, rig.right.previews) == (1, 1)


def test_start_preview_resumes_previews_after_its_answer(rig: Rig):
    session = rig.open()
    rig.handshake(session)
    rig.wait_for_previews(1)
    session.on_frame(json_frame(example("stop_preview")))
    rig.wait_for_answer("ok", 11)
    rig.pacer.tick()

    session.on_frame(json_frame(example("start_preview")))
    rig.wait_for_previews(2)

    assert [answer(frame) for frame in rig.frames()] == [
        ("welcome", 1),
        ("status", None),
        ("preview", None),
        ("ok", 11),
        ("ok", 12),
        ("preview", None),
    ]


def test_a_preview_taken_while_pausing_is_not_sent():
    taking = threading.Event()
    release = threading.Event()

    def preview() -> bytes:
        taking.set()
        release.wait()
        return b"\xff\xd8\xff\xd9"

    sender = RecordingSender()
    pacer = ManualPacer()
    stream = PreviewStream(preview, sender, "fake phone", pacer)  # type: ignore[arg-type]
    stream.start()
    try:
        stream.resume()
        assert taking.wait(timeout=5)
        stream.pause()
        release.set()
        assert pacer.wait_for_waits(1)
    finally:
        release.set()
        stream.close()

    assert "send_preview" not in sender.calls


def test_pausing_drops_the_preview_waiting_to_be_sent():
    sender = RecordingSender()
    pacer = ManualPacer()
    stream = PreviewStream(lambda: b"\xff\xd8\xff\xd9", sender, "fake phone", pacer)  # type: ignore[arg-type]
    stream.start()
    try:
        stream.resume()
        assert pacer.wait_for_waits(1)
        stream.pause()
    finally:
        stream.close()

    assert sender.calls == ["send_preview", "drop_preview"]


def test_previews_go_on_during_a_shot(rig: Rig):
    session = rig.open()
    rig.handshake(session)
    rig.wait_for_previews(1)
    shooting = threading.Event()
    release = threading.Event()

    def capture(settings: ExposureSettings) -> None:
        shooting.set()
        release.wait()

    rig.left.push(metadata(), metadata())
    rig.right.push(metadata(), metadata())
    shot = threading.Thread(target=rig.exposure.shoot, args=(capture,))
    shot.start()
    try:
        assert shooting.wait(timeout=5)
        rig.pacer.tick()
        rig.wait_for_previews(2)
    finally:
        release.set()
        shot.join()


def test_slow_requests_do_not_hold_up_the_others(rig: Rig):
    session = rig.open()
    rig.handshake(session)
    shooting = threading.Event()
    release = threading.Event()

    def capture(settings: ExposureSettings) -> None:
        shooting.set()
        release.wait()

    rig.left.push(metadata(), metadata())
    rig.right.push(metadata(), metadata())
    shot = threading.Thread(target=rig.exposure.shoot, args=(capture,))
    shot.start()
    try:
        assert shooting.wait(timeout=5)
        session.on_frame(json_frame(example("set_settings")))
        session.on_frame(json_frame(example("get_mode")))
        rig.wait_for_answer("mode", 5)
        answered_during_shot = [answer(frame) for frame in rig.frames()]
    finally:
        release.set()
        shot.join()
    rig.wait_for_answer("settings", 4)

    assert ("settings", 4) not in answered_during_shot


def test_requests_need_cameras_that_are_ready(rig: Rig):
    session = rig.open(slot=CameraSlot(), settings=CameraSettingsControl(CameraSlot()))
    rig.handshake(session)

    session.on_frame(json_frame(example("shutter")))
    session.on_frame(json_frame(example("set_settings")))

    for request_id in (2, 4):
        error = json.loads(rig.wait_for_answer("error", request_id).payload)
        assert error["code"] == "cameras_not_ready"
    assert rig.shutters == []


def test_previews_wait_for_the_cameras(rig: Rig):
    session = rig.open(preview=PreviewFrames(CameraSlot(), min_interval_s=0).latest)
    rig.handshake(session)

    assert rig.pacer.wait_for_waits(1)
    rig.pacer.tick()
    assert rig.pacer.wait_for_waits(2)

    assert previews(rig.port.written) == []


def test_a_failing_preview_is_logged_once_and_retried(
    rig: Rig, caplog: pytest.LogCaptureFixture
):
    results: list[Exception | bytes] = [
        RuntimeError("no preview frame arrived"),
        RuntimeError("no preview frame arrived"),
        b"\xff\xd8\xff\xd9",
    ]

    def preview() -> bytes:
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    session = rig.open(preview=preview)
    with caplog.at_level(logging.INFO, logger="pivr180_device.aoa.session"):
        rig.handshake(session)
        for count in (1, 2):
            assert rig.pacer.wait_for_waits(count)
            rig.pacer.tick()
        rig.wait_for_previews(1)
        assert rig.pacer.wait_for_waits(3)

    assert caplog.text.count("preview for fake phone failed") == 1
    assert "preview for fake phone is back" in caplog.text
    assert previews(rig.port.written)[0].payload == b"\xff\xd8\xff\xd9"


def test_failed_requests_answer_internal_error(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, device_message: Draft202012Validator
):
    def list_captures() -> list[Path]:
        raise PermissionError("captures are unreadable")

    session = rig.open()
    rig.handshake(session)
    monkeypatch.setattr(rig.storage, "list_captures", list_captures)

    session.on_frame(json_frame(example("list_captures")))
    error = json.loads(rig.wait_for_answer("error", 7).payload)
    session.on_frame(json_frame(example("get_mode")))
    rig.wait_for_answer("mode", 5)

    assert error == {
        "type": "error",
        "id": 7,
        "code": "internal_error",
        "message": "list_captures failed: captures are unreadable",
    }
    device_message.validate(error)


def test_requests_before_hello_need_the_handshake(
    rig: Rig, device_message: Draft202012Validator
):
    session = rig.open()

    session.on_frame(json_frame(example("get_settings")))
    error = json.loads(rig.wait_for_answer("error", 3).payload)

    assert error["code"] == "handshake_required"
    device_message.validate(error)
    assert rig.pacer.waits == []


def test_another_protocol_version_is_rejected_and_nothing_else_answered(
    rig: Rig, device_message: Draft202012Validator
):
    session = rig.open()

    session.on_frame(json_frame({**example("hello"), "protocol_version": 1}))
    session.on_frame(json_frame(example("get_settings")))
    session.on_frame(json_frame(example("hello")))
    session.on_frame(json_frame({"type": "shutter"}))
    rig.board.show(Status.CAPTURING)
    session.on_close()

    [error] = rig.messages()
    assert error == {
        "type": "error",
        "id": 1,
        "code": "unsupported_protocol_version",
        "message": f"device speaks protocol version {PROTOCOL_VERSION}, app speaks 1",
    }
    device_message.validate(error)
    assert rig.left.previews == 0


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        pytest.param(
            Frame(FrameKind.JSON, b"{"), "frame body is not valid JSON", id="not_json"
        ),
        pytest.param(
            json_frame({"type": "shutter"}), "request has no valid id", id="no_id"
        ),
        pytest.param(
            preview_frame(b"\xff\xd8\xff\xd9"),
            "a PREVIEW frame is not a request",
            id="preview_frame",
        ),
    ],
)
def test_unreadable_frames_are_answered_without_an_id(
    rig: Rig, device_message: Draft202012Validator, frame: Frame, reason: str
):
    session = rig.open()
    rig.handshake(session)

    session.on_frame(frame)
    error = json.loads(rig.wait_for_answer("error", None).payload)
    session.on_frame(json_frame(example("get_mode")))
    rig.wait_for_answer("mode", 5)

    assert error == {"type": "error", "code": "invalid_message", "message": reason}
    device_message.validate(error)


def test_invalid_requests_are_answered_with_their_id(
    rig: Rig, device_message: Draft202012Validator
):
    session = rig.open()
    rig.handshake(session)

    session.on_frame(json_frame({"type": "set_mode", "id": 6, "mode": "video"}))
    error = json.loads(rig.wait_for_answer("error", 6).payload)

    assert error["code"] == "invalid_message"
    assert error["message"].startswith("set_mode.mode must be 'photo'")
    device_message.validate(error)


def test_logs_the_type_of_each_request(rig: Rig, caplog: pytest.LogCaptureFixture):
    session = rig.open()

    with caplog.at_level(logging.INFO, logger="pivr180_device.aoa.session"):
        rig.handshake(session)
        session.on_frame(json_frame(example("get_settings")))
        rig.wait_for_answer("settings", 3)

    assert "received hello (id 1) from fake phone" in caplog.text
    assert "received get_settings (id 3) from fake phone" in caplog.text


def test_hello_again_answers_welcome_and_status_again(rig: Rig):
    session = rig.open()
    rig.handshake(session)

    session.on_frame(json_frame({**example("hello"), "id": 20}))
    rig.wait_for_answer("welcome", 20)
    rig.wait_for_message(
        lambda message: len([m for m in rig.messages() if m["type"] == "status"]) == 2
    )
    rig.board.show(Status.CAPTURING)
    rig.wait_for_message(lambda message: message.get("state") == "capturing")

    statuses = [m for m in rig.messages() if m["type"] == "status"]
    assert [status["state"] for status in statuses] == ["idle", "idle", "capturing"]


def test_closing_stops_the_threads_and_the_status(rig: Rig):
    session = rig.open()
    rig.handshake(session)
    rig.wait_for_previews(1)

    session.on_close()
    rig.board.show(Status.CAPTURING)

    assert session_threads() == set()
    assert [m["type"] for m in rig.messages()] == ["welcome", "status"]


def test_closing_before_the_handshake_stops_the_threads(rig: Rig):
    rig.open().on_close()

    assert session_threads() == set()
    assert rig.port.written == []
