import errno
from typing import Any

import pytest
import usb.core
import usb.util

from pivr180_device.aoa import pyusb as aoa_pyusb
from pivr180_device.aoa.accessory import AccessoryIdentity, switch_to_accessory
from pivr180_device.aoa.base import AccessoryPort, UsbBus, UsbDevice
from pivr180_device.aoa.pyusb import (
    CONTROL_TIMEOUT_MS,
    READ_SIZE,
    READ_TIMEOUT_MS,
    WRITE_TIMEOUT_MS,
    PyUsbAccessoryPort,
    PyUsbBus,
    PyUsbDevice,
)

BULK = usb.util.ENDPOINT_TYPE_BULK
INTERRUPT = usb.util.ENDPOINT_TYPE_INTR


class StubEndpoint:
    def __init__(
        self, address: int, attributes: int = BULK, max_packet_size: int = 512
    ) -> None:
        self.bEndpointAddress = address
        self.bmAttributes = attributes
        self.wMaxPacketSize = max_packet_size
        self.reads: list[bytes | Exception] = []
        self.read_calls: list[tuple[int, int]] = []
        self.writes: list[tuple[bytes, int]] = []
        self.short_by = 0

    def read(self, size: int, timeout: int) -> bytes:
        self.read_calls.append((size, timeout))
        item = self.reads.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def write(self, data: bytes, timeout: int) -> int:
        self.writes.append((bytes(data), timeout))
        return max(len(data) - self.short_by, 0)


class StubInterface:
    def __init__(self, number: int, cls: int, endpoints: list[StubEndpoint]) -> None:
        self.bInterfaceNumber = number
        self.bInterfaceClass = cls
        self._endpoints = endpoints

    def __iter__(self):
        return iter(self._endpoints)


class StubConfiguration:
    def __init__(self, interfaces: list[StubInterface]) -> None:
        self._interfaces = interfaces

    def __iter__(self):
        return iter(self._interfaces)

    def __getitem__(self, index: tuple[int, int]) -> StubInterface:
        number, _ = index
        return self._interfaces[number]


class StubDevice:
    def __init__(
        self,
        configuration: StubConfiguration | None = None,
        *,
        configured: bool = True,
    ) -> None:
        self.bus = 1
        self.address = 7
        self.idVendor = 0x18D1
        self.idProduct = 0x4EE1
        self.bDeviceClass = 0
        self.configuration = configuration or StubConfiguration([])
        self.configured = configured
        self.transfers: list[tuple[Any, ...]] = []
        self.transfer_result: Any = b""
        self.reset_count = 0
        self.descriptor_error: usb.core.USBError | None = None

    def __iter__(self):
        if self.descriptor_error is not None:
            raise self.descriptor_error
        return iter([self.configuration])

    def ctrl_transfer(self, *args: Any, timeout: int) -> Any:
        self.transfers.append((*args, timeout))
        return self.transfer_result

    def get_active_configuration(self) -> StubConfiguration:
        if not self.configured:
            raise usb.core.USBError("Configuration not set")
        return self.configuration

    def set_configuration(self) -> None:
        self.configured = True

    def reset(self) -> None:
        self.reset_count += 1


@pytest.fixture
def usb_util_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        aoa_pyusb.usb.util,
        "claim_interface",
        lambda device, interface: calls.append(("claim", interface)),
    )
    monkeypatch.setattr(
        aoa_pyusb.usb.util,
        "dispose_resources",
        lambda device: calls.append(("dispose", device)),
    )
    return calls


def accessory_device(*endpoints: StubEndpoint) -> StubDevice:
    interface = StubInterface(0, 0xFF, list(endpoints))
    return StubDevice(StubConfiguration([interface]))


def test_pyusb_classes_follow_the_aoa_protocols():
    device: UsbDevice = PyUsbDevice(StubDevice())
    port: AccessoryPort = PyUsbAccessoryPort(
        StubDevice(), StubEndpoint(0x81), StubEndpoint(0x01)
    )
    bus: UsbBus = PyUsbBus()

    assert device.key == (1, 7)
    assert port is not None
    assert bus is not None


def test_device_reports_ids_class_and_interface_classes():
    configuration = StubConfiguration(
        [StubInterface(0, 0x06, []), StubInterface(1, 0xFF, [])]
    )
    device = PyUsbDevice(StubDevice(configuration))

    assert (device.vendor_id, device.product_id, device.device_class) == (
        0x18D1,
        0x4EE1,
        0,
    )
    assert device.interface_classes == frozenset({0x06, 0xFF})
    assert "18d1:4ee1" in device.name


def test_device_without_readable_descriptors_has_no_interface_classes():
    stub = StubDevice()
    stub.descriptor_error = usb.core.USBError("Input/Output Error")

    assert PyUsbDevice(stub).interface_classes == frozenset()


def test_switching_sends_vendor_requests_to_the_device():
    stub = StubDevice()
    stub.transfer_result = bytes([2, 0])

    assert switch_to_accessory(PyUsbDevice(stub), AccessoryIdentity(serial="s"))

    assert stub.transfers[0] == (0xC0, 51, 0, 0, 2, CONTROL_TIMEOUT_MS)
    assert stub.transfers[1] == (0x40, 52, 0, 0, b"pivr180\0", CONTROL_TIMEOUT_MS)
    assert stub.transfers[6] == (0x40, 52, 0, 5, b"s\0", CONTROL_TIMEOUT_MS)
    assert stub.transfers[7] == (0x40, 53, 0, 0, b"", CONTROL_TIMEOUT_MS)


def test_opens_the_bulk_endpoints_of_the_accessory_interface(usb_util_calls):
    endpoint_in = StubEndpoint(0x81)
    endpoint_out = StubEndpoint(0x02)
    interrupt = StubEndpoint(0x83, INTERRUPT)
    stub = accessory_device(interrupt, endpoint_in, endpoint_out)

    port = PyUsbDevice(stub).open_accessory()
    endpoint_in.reads.append(b"data")
    port.write(b"abc")

    assert port.read() == b"data"
    assert endpoint_out.writes == [(b"abc", WRITE_TIMEOUT_MS)]
    assert usb_util_calls == [("claim", stub.configuration[(0, 0)])]


def test_sets_the_configuration_when_none_is_active(usb_util_calls):
    stub = accessory_device(StubEndpoint(0x81), StubEndpoint(0x02))
    stub.configured = False

    PyUsbDevice(stub).open_accessory()

    assert stub.configured


def test_refuses_an_accessory_without_bulk_endpoints_and_releases_it(
    usb_util_calls,
):
    stub = accessory_device(StubEndpoint(0x81))

    with pytest.raises(OSError):
        PyUsbDevice(stub).open_accessory()
    assert usb_util_calls[-1] == ("dispose", stub)


def test_read_returns_what_arrived_within_the_timeout():
    endpoint_in = StubEndpoint(0x81)
    endpoint_in.reads.append(b"\x00\x00")
    port = PyUsbAccessoryPort(StubDevice(), endpoint_in, StubEndpoint(0x02))

    assert port.read() == b"\x00\x00"
    assert endpoint_in.read_calls == [(READ_SIZE, READ_TIMEOUT_MS)]


def test_read_returns_nothing_on_a_timeout():
    endpoint_in = StubEndpoint(0x81)
    endpoint_in.reads.append(usb.core.USBTimeoutError("Operation timed out"))
    port = PyUsbAccessoryPort(StubDevice(), endpoint_in, StubEndpoint(0x02))

    assert port.read() == b""


def test_read_raises_os_error_when_the_device_is_gone():
    endpoint_in = StubEndpoint(0x81)
    endpoint_in.reads.append(
        usb.core.USBError("No such device", errno=errno.ENODEV)  # type: ignore[call-arg]
    )
    port = PyUsbAccessoryPort(StubDevice(), endpoint_in, StubEndpoint(0x02))

    with pytest.raises(OSError):
        port.read()


def test_write_ends_a_multiple_of_the_packet_size_with_a_zero_length_packet():
    endpoint_out = StubEndpoint(0x02, max_packet_size=512)
    port = PyUsbAccessoryPort(StubDevice(), StubEndpoint(0x81), endpoint_out)

    port.write(b"x" * 1024)
    port.write(b"y" * 1000)

    assert [len(data) for data, _ in endpoint_out.writes] == [1024, 0, 1000]


def test_a_short_write_is_an_error():
    endpoint_out = StubEndpoint(0x02)
    endpoint_out.short_by = 1
    port = PyUsbAccessoryPort(StubDevice(), StubEndpoint(0x81), endpoint_out)

    with pytest.raises(OSError):
        port.write(b"abc")


def test_reset_and_close_release_the_device(usb_util_calls):
    stub = StubDevice()
    port = PyUsbAccessoryPort(stub, StubEndpoint(0x81), StubEndpoint(0x02))

    port.reset()
    port.close()

    assert stub.reset_count == 1
    assert usb_util_calls == [("dispose", stub)]


def test_device_reset_releases_the_device(usb_util_calls):
    stub = StubDevice()

    PyUsbDevice(stub).reset()

    assert stub.reset_count == 1
    assert usb_util_calls == [("dispose", stub)]


def test_bus_wraps_every_device_found(monkeypatch: pytest.MonkeyPatch):
    stubs = [StubDevice(), StubDevice()]
    stubs[1].address = 8
    monkeypatch.setattr(
        aoa_pyusb.usb.core, "find", lambda find_all: iter(stubs) if find_all else None
    )

    assert [device.key for device in PyUsbBus().devices()] == [(1, 7), (1, 8)]


def test_bus_without_libusb_raises_os_error(monkeypatch: pytest.MonkeyPatch):
    def no_backend(find_all: bool) -> None:
        raise usb.core.NoBackendError("No backend available")

    monkeypatch.setattr(aoa_pyusb.usb.core, "find", no_backend)

    with pytest.raises(OSError, match="libusb is not available"):
        PyUsbBus().devices()
