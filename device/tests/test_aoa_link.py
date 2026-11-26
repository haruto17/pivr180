import errno
import logging
import threading
import time
from collections.abc import Callable

import pytest

from pivr180_device.aoa.accessory import (
    ESPRESSIF_VENDOR_ID,
    GET_PROTOCOL,
    START,
)
from pivr180_device.aoa.fake import (
    FakeAccessoryPort,
    FakeUsbBus,
    FakeUsbDevice,
    fake_accessory,
)
from pivr180_device.aoa.frame import (
    Frame,
    FrameKind,
    encode_frame,
    json_frame,
)
from pivr180_device.aoa.link import (
    AoaLink,
    Connection,
    ConnectionClosedError,
    LoggingSession,
)

HELLO = json_frame({"type": "hello", "id": 1})
SHUTTER = json_frame({"type": "shutter", "id": 2})


class RecordingSession:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.frames: list[Frame] = []
        self.closed = threading.Event()

    def on_frame(self, frame: Frame) -> None:
        self.frames.append(frame)

    def on_close(self) -> None:
        self.closed.set()


class SessionRecorder:
    def __init__(self) -> None:
        self.sessions: list[RecordingSession] = []

    def __call__(self, connection: Connection) -> RecordingSession:
        session = RecordingSession(connection)
        self.sessions.append(session)
        return session


def wait_for(predicate: Callable[[], bool], timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()


def make_link(bus: FakeUsbBus, factory: Callable[[Connection], object]) -> AoaLink:
    return AoaLink(bus, factory, scan_interval_s=0.001)  # type: ignore[arg-type]


def link_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "aoa-link" and thread.is_alive()
    ]


def test_switches_an_android_phone_then_opens_the_accessory_and_reads_frames():
    phone = FakeUsbDevice((1, 2))
    port = FakeAccessoryPort([encode_frame(HELLO) + encode_frame(SHUTTER)])
    accessory = fake_accessory((1, 3), port)
    bus = FakeUsbBus([], [phone], [accessory])
    sessions = SessionRecorder()

    with make_link(bus, sessions):
        assert wait_for(port.drained.is_set)

        assert phone.controls[0] == (GET_PROTOCOL, 2, b"")
        assert phone.controls[-1] == (START, 0, b"")
        assert [session.frames for session in sessions.sessions] == [[HELLO, SHUTTER]]


def test_reassembles_frames_split_across_bulk_reads():
    data = encode_frame(HELLO) + encode_frame(SHUTTER)
    port = FakeAccessoryPort([data[:3], data[3:20], data[20:]])
    bus = FakeUsbBus([], [fake_accessory((1, 3), port)])
    sessions = SessionRecorder()

    with make_link(bus, sessions):
        assert wait_for(port.drained.is_set)

    assert sessions.sessions[0].frames == [HELLO, SHUTTER]


def test_skips_frames_of_unknown_kind():
    unknown = b"\x00\x00\x00\x02\x7fhi"
    port = FakeAccessoryPort([unknown + encode_frame(HELLO)])
    bus = FakeUsbBus([], [fake_accessory((1, 3), port)])
    sessions = SessionRecorder()

    with make_link(bus, sessions):
        assert wait_for(port.drained.is_set)

    assert sessions.sessions[0].frames == [HELLO]


def test_sends_frames_from_another_thread_while_reading():
    port = FakeAccessoryPort()
    bus = FakeUsbBus([], [fake_accessory((1, 3), port)])
    sessions = SessionRecorder()

    with make_link(bus, sessions) as link:
        assert wait_for(lambda: link.connected)
        sender = threading.Thread(
            target=sessions.sessions[0].connection.send, args=(SHUTTER,)
        )
        sender.start()
        sender.join()

        assert port.written == [encode_frame(SHUTTER)]


def test_leaves_the_atoms3_lite_hubs_and_other_devices_alone():
    atoms3 = FakeUsbDevice(
        (1, 2), vendor_id=ESPRESSIF_VENDOR_ID, interface_classes=(0x02, 0x0A, 0xFF)
    )
    hub = FakeUsbDevice((1, 1), device_class=0x09, interface_classes=(0x09,))
    keyboard = FakeUsbDevice((1, 4), interface_classes=(0x03,))
    bus = FakeUsbBus([atoms3, hub, keyboard])

    with make_link(bus, SessionRecorder()):
        assert wait_for(lambda: bus.finished)

    for device in (atoms3, hub, keyboard):
        assert device.controls == []
        assert device.reset_count == 0
        assert device.opened == 0


def test_asks_a_device_without_aoa_only_once():
    phone = FakeUsbDevice((1, 2), aoa_version=0)
    bus = FakeUsbBus([phone], [phone], [phone])

    with make_link(bus, SessionRecorder()):
        assert wait_for(lambda: bus.finished)

    assert phone.controls == [(GET_PROTOCOL, 2, b"")]


def test_asks_a_device_whose_request_fails_only_once():
    phone = FakeUsbDevice((1, 2), control_error=OSError(errno.EPIPE, "Pipe error"))
    bus = FakeUsbBus([phone], [phone], [phone])

    with make_link(bus, SessionRecorder()):
        assert wait_for(lambda: bus.finished)

    assert phone.controls == [(GET_PROTOCOL, 2, b"")]


def test_switches_a_phone_once_while_it_reenumerates():
    phone = FakeUsbDevice((1, 2))
    bus = FakeUsbBus([phone], [phone], [phone])

    with make_link(bus, SessionRecorder()):
        assert wait_for(lambda: bus.finished)

    assert [control[0] for control in phone.controls].count(START) == 1


def test_retries_a_phone_it_had_no_permission_for_and_warns_once(caplog):
    denied = OSError(errno.EACCES, "Access denied")
    phone = FakeUsbDevice((1, 2), control_error=denied)
    bus = FakeUsbBus([phone], [phone], [phone])

    with caplog.at_level(logging.WARNING), make_link(bus, SessionRecorder()):
        assert wait_for(lambda: bus.finished)
        phone.control_error = None
        assert wait_for(lambda: (START, 0, b"") in phone.controls)

    assert [control[0] for control in phone.controls].count(GET_PROTOCOL) >= 3
    assert sum("no permission" in r.message for r in caplog.records) == 1


def test_switches_a_phone_again_after_it_is_plugged_back_in():
    phone = FakeUsbDevice((1, 2))
    replugged = FakeUsbDevice((1, 2))
    bus = FakeUsbBus([phone], [], [replugged])

    with make_link(bus, SessionRecorder()):
        assert wait_for(lambda: bus.finished)

    assert phone.controls[-1] == (START, 0, b"")
    assert replugged.controls[-1] == (START, 0, b"")


def test_reconnects_with_a_new_session_after_the_cable_is_pulled_and_replugged():
    first_port = FakeAccessoryPort(
        [encode_frame(HELLO), OSError(errno.ENODEV, "No such device")]
    )
    second_port = FakeAccessoryPort([encode_frame(SHUTTER)])
    phone = FakeUsbDevice((1, 5))
    bus = FakeUsbBus(
        [],
        [fake_accessory((1, 3), first_port)],
        [],
        [phone],
        [fake_accessory((1, 6), second_port)],
    )
    sessions = SessionRecorder()

    with make_link(bus, sessions):
        assert wait_for(second_port.drained.is_set)

        first, second = sessions.sessions
        assert first.frames == [HELLO]
        assert first.closed.is_set()
        assert first_port.closed
        assert second.frames == [SHUTTER]
        assert not second.closed.is_set()
        assert phone.controls[-1] == (START, 0, b"")


def test_a_closed_connection_refuses_to_send():
    first_port = FakeAccessoryPort([OSError(errno.ENODEV, "No such device")])
    second_port = FakeAccessoryPort()
    bus = FakeUsbBus(
        [],
        [fake_accessory((1, 3), first_port)],
        [fake_accessory((1, 4), second_port)],
    )
    sessions = SessionRecorder()

    with make_link(bus, sessions):
        assert wait_for(second_port.drained.is_set)
        old = sessions.sessions[0].connection

        assert old.closed
        with pytest.raises(ConnectionClosedError):
            old.send(SHUTTER)
        assert second_port.written == []


def test_send_fails_after_the_link_is_closed():
    port = FakeAccessoryPort()
    accessory = fake_accessory((1, 3), port)
    bus = FakeUsbBus([], [accessory])
    sessions = SessionRecorder()

    with make_link(bus, sessions) as link:
        assert wait_for(lambda: link.connected)

    connection = sessions.sessions[0].connection
    with pytest.raises(ConnectionClosedError):
        connection.send(SHUTTER)
    assert sessions.sessions[0].closed.is_set()
    assert port.closed
    assert accessory.reset_count == 0
    assert not link.connected


def test_resets_and_reconnects_after_a_frame_over_the_length_limit():
    port = FakeAccessoryPort([b"\x00\x40\x00\x01\x01"])
    accessory = fake_accessory((1, 3), port)
    phone = FakeUsbDevice((1, 5))
    bus = FakeUsbBus([], [accessory], [phone])
    sessions = SessionRecorder()

    with make_link(bus, sessions):
        assert wait_for(lambda: (START, 0, b"") in phone.controls)

    assert accessory.reset_count == 1
    assert port.closed
    assert sessions.sessions[0].closed.is_set()


def test_resets_the_connection_after_a_failed_send():
    port = FakeAccessoryPort(write_error=OSError(errno.ETIMEDOUT, "Timed out"))
    accessory = fake_accessory((1, 3), port)
    bus = FakeUsbBus([], [accessory])
    sessions = SessionRecorder()

    with make_link(bus, sessions) as link:
        assert wait_for(lambda: link.connected)
        connection = sessions.sessions[0].connection
        with pytest.raises(OSError):
            connection.send(SHUTTER)

        assert sessions.sessions[0].closed.wait(5.0)
        assert port.closed
        assert wait_for(lambda: accessory.reset_count >= 1)
        with pytest.raises(ConnectionClosedError):
            connection.send(SHUTTER)


def test_resets_an_accessory_left_from_before_start_before_opening_it():
    port = FakeAccessoryPort()
    stale = fake_accessory((1, 3), port)
    opened_at_reset: list[int] = []
    reset = stale.reset

    def recording_reset() -> None:
        opened_at_reset.append(stale.opened)
        reset()

    stale.reset = recording_reset  # type: ignore[method-assign]
    bus = FakeUsbBus([stale])
    sessions = SessionRecorder()

    with make_link(bus, sessions):
        assert wait_for(port.drained.is_set)

    assert opened_at_reset == [0]
    assert stale.opened == 1


def test_keeps_scanning_while_usb_is_unavailable_and_warns_once(caplog):
    port = FakeAccessoryPort([encode_frame(HELLO)])
    unavailable = OSError("libusb is not available")
    bus = FakeUsbBus(unavailable, unavailable, [], [fake_accessory((1, 3), port)])
    sessions = SessionRecorder()

    with caplog.at_level(logging.WARNING), make_link(bus, sessions):
        assert wait_for(port.drained.is_set)

    assert sessions.sessions[0].frames == [HELLO]
    assert sum("USB is unavailable" in r.message for r in caplog.records) == 1


def test_retries_opening_an_accessory_and_warns_once(caplog):
    port = FakeAccessoryPort([encode_frame(HELLO)])
    denied = OSError(errno.EACCES, "Access denied")
    accessory = fake_accessory((1, 3), port, open_errors=[denied, denied])
    bus = FakeUsbBus([], [accessory])
    sessions = SessionRecorder()

    with caplog.at_level(logging.WARNING), make_link(bus, sessions):
        assert wait_for(port.drained.is_set)

    assert sessions.sessions[0].frames == [HELLO]
    assert sum("could not open" in r.message for r in caplog.records) == 1


def test_a_session_error_is_logged_and_the_next_frame_still_arrives(caplog):
    port = FakeAccessoryPort([encode_frame(HELLO), encode_frame(SHUTTER)])
    accessory = fake_accessory((1, 3), port)
    bus = FakeUsbBus([], [accessory])
    received: list[Frame] = []

    class FailingOnHello(RecordingSession):
        def on_frame(self, frame: Frame) -> None:
            received.append(frame)
            if frame == HELLO:
                raise ValueError("bad hello")

    with caplog.at_level(logging.ERROR), make_link(bus, FailingOnHello) as link:
        assert wait_for(port.drained.is_set)
        assert link.connected

    assert received == [HELLO, SHUTTER]
    assert accessory.reset_count == 0
    assert any("failed to handle a frame" in r.message for r in caplog.records)


def test_an_unexpected_error_stops_only_the_link_thread(caplog):
    bus = FakeUsbBus([])

    def broken_devices() -> list:
        raise RuntimeError("bug")

    bus.devices = broken_devices  # type: ignore[method-assign]

    with caplog.at_level(logging.ERROR), make_link(bus, SessionRecorder()):
        assert wait_for(lambda: link_threads() == [])

    assert any("unexpected error" in r.message for r in caplog.records)


def test_close_stops_the_thread_while_connected():
    port = FakeAccessoryPort()
    bus = FakeUsbBus([], [fake_accessory((1, 3), port)])
    link = make_link(bus, SessionRecorder())

    with link:
        assert wait_for(lambda: link.connected)

    assert link_threads() == []


def test_close_stops_the_thread_while_waiting_between_scans():
    link = AoaLink(FakeUsbBus([]), SessionRecorder(), scan_interval_s=60.0)
    started = time.monotonic()

    with link:
        pass

    assert time.monotonic() - started < 5.0
    assert link_threads() == []


def test_logging_session_logs_each_frame(caplog):
    session = LoggingSession(Connection(FakeAccessoryPort(), "phone"))

    with caplog.at_level(logging.INFO):
        session.on_frame(Frame(FrameKind.PREVIEW, b"abc"))

    assert "PREVIEW frame of 3 bytes from phone" in caplog.text


def test_retries_resetting_a_left_accessory_it_had_no_permission_for():
    port = FakeAccessoryPort([encode_frame(HELLO)])
    denied = OSError(errno.EACCES, "Access denied")
    stale = fake_accessory((1, 3), port, reset_errors=[denied])
    bus = FakeUsbBus([stale])
    sessions = SessionRecorder()

    with make_link(bus, sessions):
        assert wait_for(port.drained.is_set)

    assert stale.reset_count == 2
    assert stale.opened == 1
    assert sessions.sessions[0].frames == [HELLO]


def test_opens_a_left_accessory_that_keeps_its_address_after_the_reset():
    port = FakeAccessoryPort([encode_frame(HELLO)])
    stale = fake_accessory((1, 3), port)
    bus = FakeUsbBus([stale])
    sessions = SessionRecorder()

    with make_link(bus, sessions):
        assert wait_for(port.drained.is_set)

    assert stale.reset_count == 1
    assert sessions.sessions[0].frames == [HELLO]


def test_reopens_an_accessory_that_keeps_its_address_after_a_recovery_reset():
    first_port = FakeAccessoryPort([b"\x00\x40\x00\x01\x01"])
    second_port = FakeAccessoryPort([encode_frame(HELLO)])
    accessory = fake_accessory((1, 3), first_port, second_port)
    bus = FakeUsbBus([], [accessory])
    sessions = SessionRecorder()

    with make_link(bus, sessions):
        assert wait_for(second_port.drained.is_set)

    assert accessory.reset_count == 1
    assert first_port.closed
    first, second = sessions.sessions
    assert first.closed.is_set()
    assert second.frames == [HELLO]


def test_gives_up_on_a_left_accessory_whose_reset_fails_otherwise(caplog):
    port = FakeAccessoryPort()
    broken = OSError(errno.EIO, "Input/Output Error")
    stale = fake_accessory((1, 3), port, reset_errors=[broken, broken])
    bus = FakeUsbBus([stale], [stale], [stale])

    with caplog.at_level(logging.WARNING), make_link(bus, SessionRecorder()):
        assert wait_for(lambda: bus.finished)

    assert stale.reset_count == 1
    assert stale.opened == 0
