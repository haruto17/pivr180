import logging
import threading

import pytest

from pivr180_device.aoa.fake import GatedAccessoryPort
from pivr180_device.aoa.frame import (
    MAX_PAYLOAD_BYTES,
    encode_frame,
    json_frame,
    preview_frame,
)
from pivr180_device.aoa.link import Connection
from pivr180_device.aoa.sender import FrameSender


def sender_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "aoa-sender" and thread.is_alive()
    ]


@pytest.fixture
def port() -> GatedAccessoryPort:
    return GatedAccessoryPort()


def test_sends_frames_in_the_order_they_come(port: GatedAccessoryPort):
    first = json_frame({"type": "ok", "id": 1})
    second = json_frame({"type": "ok", "id": 2})

    with FrameSender(Connection(port, "fake phone")) as sender:
        sender.send(first)
        sender.send(second)
        assert port.wait_for_written(2)

    assert port.written == [encode_frame(first), encode_frame(second)]
    assert sender_threads() == []


def test_drops_older_previews_while_the_phone_is_slow_to_read(
    port: GatedAccessoryPort,
):
    previews = [preview_frame(bytes([0xFF, 0xD8, n, 0xFF, 0xD9])) for n in range(3)]
    status = json_frame({"type": "ok", "id": 1})

    with FrameSender(Connection(port, "fake phone")) as sender:
        port.hold()
        sender.send_preview(previews[0])
        assert port.wait_for_writes_started(1)
        sender.send_preview(previews[1])
        sender.send(status)
        sender.send_preview(previews[2])
        port.release()
        assert port.wait_for_written(3)

    assert port.written == [
        encode_frame(previews[0]),
        encode_frame(status),
        encode_frame(previews[2]),
    ]


def test_a_dropped_preview_is_not_sent(port: GatedAccessoryPort):
    previews = [preview_frame(bytes([0xFF, 0xD8, n, 0xFF, 0xD9])) for n in range(2)]
    ok = json_frame({"type": "ok", "id": 1})

    with FrameSender(Connection(port, "fake phone")) as sender:
        port.hold()
        sender.send_preview(previews[0])
        assert port.wait_for_writes_started(1)
        sender.send_preview(previews[1])
        sender.drop_preview()
        sender.send(ok)
        port.release()
        assert port.wait_for_written(2)

    assert port.written == [encode_frame(previews[0]), encode_frame(ok)]


def test_stops_sending_once_a_write_fails(
    port: GatedAccessoryPort, caplog: pytest.LogCaptureFixture
):
    connection = Connection(port, "fake phone")
    port.write_error = OSError("pipe error")

    with (
        caplog.at_level(logging.WARNING),
        FrameSender(connection) as sender,
    ):
        sender.send(json_frame({"type": "ok", "id": 1}))
        assert port.wait_for_writes_started(1)
        sender.send(json_frame({"type": "ok", "id": 2}))

    assert port.written == []
    assert connection.broken
    assert "stopped sending to fake phone (pipe error)" in caplog.text


def test_a_frame_is_reported_sent_once_it_is_written(port: GatedAccessoryPort):
    with FrameSender(Connection(port, "fake phone")) as sender:
        port.hold()
        delivery = sender.send(json_frame({"type": "ok", "id": 1}))
        assert port.wait_for_writes_started(1)

        assert not delivery.wait(0)
        assert not delivery.sent
        port.release()
        assert delivery.wait(5.0)

    assert delivery.sent


def test_a_frame_is_reported_unsent_when_its_write_fails(port: GatedAccessoryPort):
    port.write_error = OSError("pipe error")

    with FrameSender(Connection(port, "fake phone")) as sender:
        failed = sender.send(json_frame({"type": "ok", "id": 1}))
        assert failed.wait(5.0)

    assert not failed.sent


def test_frames_dropped_on_closing_are_reported_unsent(port: GatedAccessoryPort):
    sender = FrameSender(Connection(port, "fake phone"))
    queued = sender.send(json_frame({"type": "ok", "id": 1}))

    sender.close()
    late = sender.send(json_frame({"type": "ok", "id": 2}))

    for delivery in (queued, late):
        assert delivery.wait(0)
        assert not delivery.sent
    assert port.written == []


def test_skips_a_frame_too_large_to_send(
    port: GatedAccessoryPort, caplog: pytest.LogCaptureFixture
):
    after = json_frame({"type": "ok", "id": 2})

    with caplog.at_level(logging.ERROR), FrameSender(Connection(port, "p")) as sender:
        sender.send(preview_frame(b"\0" * (MAX_PAYLOAD_BYTES + 1)))
        sender.send(after)
        assert port.wait_for_written(1)

    assert port.written == [encode_frame(after)]
    assert "could not send a PREVIEW frame to p" in caplog.text


def test_ignores_frames_after_closing(port: GatedAccessoryPort):
    sender = FrameSender(Connection(port, "fake phone"))
    sender.start()
    sender.close()

    sender.send(json_frame({"type": "ok", "id": 1}))
    sender.send_preview(preview_frame(b"\xff\xd8\xff\xd9"))

    assert port.written == []
    assert sender_threads() == []


def test_closing_before_starting_returns_at_once(port: GatedAccessoryPort):
    FrameSender(Connection(port, "fake phone")).close()
