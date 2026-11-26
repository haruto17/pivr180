from dataclasses import dataclass

from pivr180_device.aoa.base import UsbDevice
from pivr180_device.aoa.frame import PROTOCOL_VERSION

GOOGLE_VENDOR_ID = 0x18D1
ACCESSORY_PRODUCT_IDS = frozenset({0x2D00, 0x2D01, 0x2D04, 0x2D05})
ESPRESSIF_VENDOR_ID = 0x303A
HUB_CLASS = 0x09
STILL_IMAGE_CLASS = 0x06
VENDOR_SPECIFIC_CLASS = 0xFF
ANDROID_INTERFACE_CLASSES = frozenset({STILL_IMAGE_CLASS, VENDOR_SPECIFIC_CLASS})

GET_PROTOCOL = 51
SEND_STRING = 52
START = 53
MIN_AOA_VERSION = 1


@dataclass(frozen=True)
class AccessoryIdentity:
    manufacturer: str = "pivr180"
    model: str = "pivr180"
    description: str = "pivr180 stereo camera"
    version: str = str(PROTOCOL_VERSION)
    uri: str = "https://github.com/haruto17/pivr180"
    serial: str = ""

    def strings(self) -> tuple[str, ...]:
        return (
            self.manufacturer,
            self.model,
            self.description,
            self.version,
            self.uri,
            self.serial,
        )


def is_accessory(device: UsbDevice) -> bool:
    return (
        device.vendor_id == GOOGLE_VENDOR_ID
        and device.product_id in ACCESSORY_PRODUCT_IDS
    )


def looks_like_android(device: UsbDevice) -> bool:
    # Not every vendor-specific device: the AtomS3 Lite has a vendor-specific
    # JTAG interface, and must not receive AOA requests.
    if device.vendor_id == ESPRESSIF_VENDOR_ID or device.device_class == HUB_CLASS:
        return False
    return not device.interface_classes.isdisjoint(ANDROID_INTERFACE_CLASSES)


def switch_to_accessory(device: UsbDevice, identity: AccessoryIdentity) -> bool:
    version = int.from_bytes(device.control_in(GET_PROTOCOL, 2), "little")
    if version < MIN_AOA_VERSION:
        return False
    for index, value in enumerate(identity.strings()):
        device.control_out(SEND_STRING, index, value.encode("utf-8") + b"\0")
    device.control_out(START, 0, b"")
    return True
