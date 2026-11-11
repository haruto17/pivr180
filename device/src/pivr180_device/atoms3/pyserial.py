import glob
import logging
from typing import Protocol

import serial

logger = logging.getLogger(__name__)

DEFAULT_PORT = "/dev/serial/by-id/usb-Espressif*"
BAUD_RATE = 115200
READ_TIMEOUT_S = 0.1
MAX_LINE_BYTES = 256


class _Port(Protocol):
    def read_until(self, expected: bytes, size: int | None) -> bytes: ...

    def close(self) -> None: ...


class PySerialLink:
    def __init__(self, port: _Port, name: str) -> None:
        self._port = port
        self._name = name
        self._buffer = b""

    def read_line(self) -> str | None:
        self._buffer += self._port.read_until(
            b"\n", MAX_LINE_BYTES - len(self._buffer)
        )
        if self._buffer.endswith(b"\n"):
            line, self._buffer = self._buffer[:-1], b""
            return line.decode("ascii", errors="replace")
        if len(self._buffer) >= MAX_LINE_BYTES:
            logger.warning(
                "%s: discarding %d bytes without a line break",
                self._name,
                len(self._buffer),
            )
            self._buffer = b""
        return None

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
    port = serial.Serial(
        path, baudrate=BAUD_RATE, timeout=READ_TIMEOUT_S, exclusive=True
    )
    logger.info("opened %s", path)
    return PySerialLink(port, path)
