import glob
import logging
from typing import Protocol

import serial

logger = logging.getLogger(__name__)

DEFAULT_PORT = "/dev/serial/by-id/usb-Espressif*"
BAUD_RATE = 115200
READ_TIMEOUT_S = 0.1
WRITE_TIMEOUT_S = 0.5
MAX_LINE_BYTES = 256


class _Port(Protocol):
    def read_until(self, expected: bytes, size: int | None) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


class PySerialLink:
    def __init__(self, port: _Port, name: str) -> None:
        self._port = port
        self._name = name
        self._buffer = b""
        self._discarding = False

    def read_line(self) -> str | None:
        chunk = self._port.read_until(b"\n", MAX_LINE_BYTES - len(self._buffer))
        if self._discarding:
            if chunk.endswith(b"\n"):
                self._discarding = False
            return None
        self._buffer += chunk
        if self._buffer.endswith(b"\n"):
            line, self._buffer = self._buffer[:-1], b""
            return line.decode("ascii", errors="replace")
        if len(self._buffer) >= MAX_LINE_BYTES:
            logger.warning(
                "%s: discarding a line longer than %d bytes",
                self._name,
                MAX_LINE_BYTES,
            )
            self._buffer = b""
            self._discarding = True
        return None

    def write_line(self, line: str) -> None:
        self._port.write(f"{line}\n".encode("ascii"))

    def close(self) -> None:
        self._port.close()


def resolve_port(pattern: str) -> str:
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"no serial device matches {pattern}")
    if len(matches) > 1:
        raise OSError(
            f"{len(matches)} serial devices match {pattern}: {', '.join(matches)}"
        )
    return matches[0]


def open_serial_link(pattern: str = DEFAULT_PORT) -> PySerialLink:
    path = resolve_port(pattern)
    # Not without write_timeout: if the AtomS3 Lite stops draining its input, a
    # blocking write would stall the thread that also times the button.
    port = serial.Serial(
        path,
        baudrate=BAUD_RATE,
        timeout=READ_TIMEOUT_S,
        write_timeout=WRITE_TIMEOUT_S,
        exclusive=True,
    )
    logger.info("opened %s", path)
    return PySerialLink(port, path)
