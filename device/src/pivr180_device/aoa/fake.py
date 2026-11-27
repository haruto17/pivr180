import threading
import time
from collections import deque
from collections.abc import Hashable, Iterable, Sequence

from pivr180_device.aoa.accessory import (
    GET_PROTOCOL,
    GOOGLE_VENDOR_ID,
    STILL_IMAGE_CLASS,
)
from pivr180_device.aoa.base import UsbDevice

IDLE_READ_S = 0.001
ACCESSORY_PRODUCT_ID = 0x2D00


class FakeAccessoryPort:
    def __init__(
        self,
        reads: Iterable[bytes | OSError] = (),
        *,
        write_error: OSError | None = None,
    ) -> None:
        self._reads: deque[bytes | OSError] = deque(reads)
        self.write_error = write_error
        self.written: list[bytes] = []
        self.drained = threading.Event()
        self.closed = False

    def read(self) -> bytes:
        if self.closed:
            raise OSError("fake accessory port is closed")
        if not self._reads:
            self.drained.set()
            time.sleep(IDLE_READ_S)
            return b""
        item = self._reads.popleft()
        if isinstance(item, OSError):
            raise item
        return item

    def write(self, data: bytes) -> None:
        if self.closed:
            raise OSError("fake accessory port is closed")
        if self.write_error is not None:
            raise self.write_error
        self.written.append(data)

    def close(self) -> None:
        self.closed = True


class FakeUsbDevice:
    def __init__(
        self,
        key: Hashable,
        *,
        vendor_id: int = 0x1234,
        product_id: int = 0x5678,
        device_class: int = 0x00,
        interface_classes: Iterable[int] = (STILL_IMAGE_CLASS,),
        aoa_version: int = 2,
        control_error: OSError | None = None,
        ports: Iterable[FakeAccessoryPort] = (),
        open_errors: Iterable[OSError] = (),
        reset_errors: Iterable[OSError] = (),
    ) -> None:
        self.key = key
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.device_class = device_class
        self.interface_classes = frozenset(interface_classes)
        self.aoa_version = aoa_version
        self.control_error = control_error
        self._ports: deque[FakeAccessoryPort] = deque(ports)
        self._open_errors: deque[OSError] = deque(open_errors)
        self._reset_errors: deque[OSError] = deque(reset_errors)
        self.controls: list[tuple[int, int, bytes]] = []
        self.reset_count = 0
        self.opened = 0

    @property
    def name(self) -> str:
        return f"fake {self.key}"

    def control_in(self, request: int, length: int) -> bytes:
        self.controls.append((request, length, b""))
        if self.control_error is not None:
            raise self.control_error
        if request == GET_PROTOCOL:
            return self.aoa_version.to_bytes(2, "little")[:length]
        return b""

    def control_out(self, request: int, index: int, data: bytes) -> None:
        self.controls.append((request, index, data))
        if self.control_error is not None:
            raise self.control_error

    def reset(self) -> None:
        self.reset_count += 1
        if self._reset_errors:
            raise self._reset_errors.popleft()

    def open_accessory(self) -> FakeAccessoryPort:
        if self._open_errors:
            raise self._open_errors.popleft()
        if not self._ports:
            raise OSError(f"{self.name} is not an accessory")
        self.opened += 1
        if len(self._ports) > 1:
            return self._ports.popleft()
        return self._ports[0]


def fake_accessory(
    key: Hashable,
    *ports: FakeAccessoryPort,
    open_errors: Iterable[OSError] = (),
    reset_errors: Iterable[OSError] = (),
) -> FakeUsbDevice:
    return FakeUsbDevice(
        key,
        vendor_id=GOOGLE_VENDOR_ID,
        product_id=ACCESSORY_PRODUCT_ID,
        interface_classes=(0xFF,),
        ports=ports,
        open_errors=open_errors,
        reset_errors=reset_errors,
    )


class FakeUsbBus:
    def __init__(self, *scans: Sequence[UsbDevice] | OSError) -> None:
        self._scans = list(scans)
        self.scanned = 0
        self.lock = threading.Lock()

    @property
    def finished(self) -> bool:
        with self.lock:
            return self.scanned > len(self._scans)

    def devices(self) -> list[UsbDevice]:
        with self.lock:
            index = min(self.scanned, len(self._scans) - 1)
            self.scanned += 1
        scan = self._scans[index]
        if isinstance(scan, OSError):
            raise scan
        return list(scan)
