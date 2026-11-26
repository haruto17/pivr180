import logging
from typing import Any

import usb.core
import usb.util

logger = logging.getLogger(__name__)

ACCESSORY_INTERFACE = 0
READ_SIZE = 16384
READ_TIMEOUT_MS = 100
WRITE_TIMEOUT_MS = 2000
CONTROL_TIMEOUT_MS = 1000
VENDOR_IN = (
    usb.util.CTRL_IN | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE
)
VENDOR_OUT = (
    usb.util.CTRL_OUT | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE
)


class PyUsbAccessoryPort:
    def __init__(self, device: Any, endpoint_in: Any, endpoint_out: Any) -> None:
        self._device = device
        self._in = endpoint_in
        self._out = endpoint_out

    def read(self) -> bytes:
        try:
            return bytes(self._in.read(READ_SIZE, timeout=READ_TIMEOUT_MS))
        except usb.core.USBTimeoutError:
            return b""

    def write(self, data: bytes) -> None:
        written = self._out.write(data, timeout=WRITE_TIMEOUT_MS)
        if written != len(data):
            raise OSError(f"wrote {written} of {len(data)} bytes")
        if data and len(data) % self._out.wMaxPacketSize == 0:
            # Not ended by the last full packet: the phone's accessory read waits
            # for a short packet, so the frame would sit there until the next one.
            self._out.write(b"", timeout=WRITE_TIMEOUT_MS)

    def reset(self) -> None:
        self._device.reset()

    def close(self) -> None:
        usb.util.dispose_resources(self._device)


class PyUsbDevice:
    def __init__(self, device: Any) -> None:
        self._device = device

    @property
    def key(self) -> tuple[int, int]:
        return (self._device.bus, self._device.address)

    @property
    def name(self) -> str:
        return (
            f"USB {self.vendor_id:04x}:{self.product_id:04x} "
            f"(bus {self._device.bus} address {self._device.address})"
        )

    @property
    def vendor_id(self) -> int:
        return self._device.idVendor

    @property
    def product_id(self) -> int:
        return self._device.idProduct

    @property
    def device_class(self) -> int:
        return self._device.bDeviceClass

    @property
    def interface_classes(self) -> frozenset[int]:
        try:
            return frozenset(
                interface.bInterfaceClass
                for configuration in self._device
                for interface in configuration
            )
        except usb.core.USBError as error:
            logger.debug("could not read the descriptors of %s (%s)", self.name, error)
            return frozenset()

    def control_in(self, request: int, length: int) -> bytes:
        return bytes(
            self._device.ctrl_transfer(
                VENDOR_IN, request, 0, 0, length, timeout=CONTROL_TIMEOUT_MS
            )
        )

    def control_out(self, request: int, index: int, data: bytes) -> None:
        self._device.ctrl_transfer(
            VENDOR_OUT, request, 0, index, data, timeout=CONTROL_TIMEOUT_MS
        )

    def reset(self) -> None:
        try:
            self._device.reset()
        finally:
            usb.util.dispose_resources(self._device)

    def open_accessory(self) -> PyUsbAccessoryPort:
        try:
            try:
                configuration = self._device.get_active_configuration()
            except usb.core.USBError:
                self._device.set_configuration()
                configuration = self._device.get_active_configuration()
            interface = configuration[(ACCESSORY_INTERFACE, 0)]
            usb.util.claim_interface(self._device, interface)
            endpoint_in = _bulk_endpoint(interface, usb.util.ENDPOINT_IN)
            endpoint_out = _bulk_endpoint(interface, usb.util.ENDPOINT_OUT)
            if endpoint_in is None or endpoint_out is None:
                raise OSError(f"{self.name} has no bulk endpoints for the accessory")
        except BaseException:
            usb.util.dispose_resources(self._device)
            raise
        return PyUsbAccessoryPort(self._device, endpoint_in, endpoint_out)


class PyUsbBus:
    def devices(self) -> list[PyUsbDevice]:
        try:
            found = usb.core.find(find_all=True)
            return [PyUsbDevice(device) for device in found]
        except usb.core.NoBackendError as error:
            raise OSError(f"libusb is not available ({error})") from error


def _bulk_endpoint(interface: Any, direction: int) -> Any:
    return usb.util.find_descriptor(
        interface,
        custom_match=lambda endpoint: (
            usb.util.endpoint_direction(endpoint.bEndpointAddress) == direction
            and usb.util.endpoint_type(endpoint.bmAttributes)
            == usb.util.ENDPOINT_TYPE_BULK
        ),
    )
