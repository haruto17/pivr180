import logging
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from pivr180_device.atoms3 import SerialLink
from pivr180_device.atoms3 import pyserial as pyserial_link
from pivr180_device.atoms3.pyserial import (
    BAUD_RATE,
    DEFAULT_PORT,
    MAX_LINE_BYTES,
    READ_TIMEOUT_S,
    PySerialLink,
    open_serial_link,
    resolve_port,
)


class StubPort:
    def __init__(self, *chunks: bytes | OSError) -> None:
        self._chunks: deque[bytes | OSError] = deque(chunks)
        self.reads: list[tuple[bytes, int | None]] = []
        self.closed = False

    def read_until(self, expected: bytes, size: int | None) -> bytes:
        self.reads.append((expected, size))
        if not self._chunks:
            return b""
        chunk = self._chunks.popleft()
        if isinstance(chunk, OSError):
            raise chunk
        return chunk

    def close(self) -> None:
        self.closed = True


def read_lines(link: PySerialLink, count: int) -> list[str | None]:
    return [link.read_line() for _ in range(count)]


def test_pyserial_link_is_a_serial_link():
    link: SerialLink = PySerialLink(StubPort(), "port")

    assert link.read_line() is None


def test_returns_each_complete_line_without_the_line_feed():
    link = PySerialLink(StubPort(b"press\n", b"release\r\n"), "port")

    assert read_lines(link, 3) == ["press", "release\r", None]


def test_joins_a_line_split_across_read_timeouts():
    port = StubPort(b"pr", b"", b"ess\n")
    link = PySerialLink(port, "port")

    assert read_lines(link, 3) == [None, None, "press"]
    assert port.reads == [
        (b"\n", MAX_LINE_BYTES),
        (b"\n", MAX_LINE_BYTES - 2),
        (b"\n", MAX_LINE_BYTES - 2),
    ]


def test_decodes_non_ascii_bytes_without_failing():
    link = PySerialLink(StubPort(b"\xffpress\n"), "port")

    assert link.read_line() == "�press"


def test_discards_an_oversized_line_through_its_line_feed(
    caplog: pytest.LogCaptureFixture,
):
    port = StubPort(
        b"x" * MAX_LINE_BYTES, b"x" * MAX_LINE_BYTES, b"press\n", b"release\n"
    )
    link = PySerialLink(port, "port")

    with caplog.at_level(logging.WARNING, logger="pivr180_device.atoms3.pyserial"):
        assert read_lines(link, 4) == [None, None, None, "release"]

    assert port.reads[1:] == [(b"\n", MAX_LINE_BYTES)] * 3
    [record] = caplog.records
    assert "port" in record.getMessage()
    assert f"{MAX_LINE_BYTES} bytes" in record.getMessage()


def test_read_errors_propagate():
    link = PySerialLink(StubPort(OSError("device disconnected")), "port")

    with pytest.raises(OSError, match="device disconnected"):
        link.read_line()


def test_close_closes_the_port():
    port = StubPort()

    PySerialLink(port, "port").close()

    assert port.closed


def test_default_port_matches_espressif_devices_by_id():
    assert DEFAULT_PORT.startswith("/dev/serial/by-id/usb-Espressif")


def test_resolve_port_returns_the_only_match(tmp_path: Path):
    device = tmp_path / "usb-Espressif_USB_JTAG_serial_debug_unit_AA:BB-if00"
    device.touch()
    (tmp_path / "usb-FTDI_other-if00").touch()

    assert resolve_port(str(tmp_path / "usb-Espressif*")) == str(device)


def test_resolve_port_accepts_a_literal_path(tmp_path: Path):
    device = tmp_path / "ttyACM0"
    device.touch()

    assert resolve_port(str(device)) == str(device)


def test_resolve_port_fails_when_nothing_matches(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="no serial device matches"):
        resolve_port(str(tmp_path / "usb-Espressif*"))


def test_resolve_port_refuses_to_guess_between_several_matches(tmp_path: Path):
    for name in ("usb-Espressif_a-if00", "usb-Espressif_b-if00"):
        (tmp_path / name).touch()

    with pytest.raises(OSError, match="2 serial devices match") as error:
        resolve_port(str(tmp_path / "usb-Espressif*"))

    assert "usb-Espressif_a-if00" in str(error.value)
    assert "usb-Espressif_b-if00" in str(error.value)


def test_open_serial_link_opens_the_resolved_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    device = tmp_path / "usb-Espressif_a-if00"
    device.touch()
    opened: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_serial(*args: Any, **kwargs: Any) -> StubPort:
        opened.append((args, kwargs))
        return StubPort(b"press\n")

    monkeypatch.setattr(pyserial_link.serial, "Serial", fake_serial)

    link = open_serial_link(str(tmp_path / "usb-Espressif*"))

    assert opened == [
        (
            (str(device),),
            {"baudrate": BAUD_RATE, "timeout": READ_TIMEOUT_S, "exclusive": True},
        )
    ]
    assert link.read_line() == "press"
