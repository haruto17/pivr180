import fnmatch
import re
from pathlib import Path

import pytest

from pivr180_device.aoa.accessory import (
    ACCESSORY_PRODUCT_IDS,
    ANDROID_INTERFACE_CLASSES,
    ESPRESSIF_VENDOR_ID,
    GOOGLE_VENDOR_ID,
    HUB_CLASS,
)

RULES = Path(__file__).resolve().parents[1] / "udev" / "70-pivr180-aoa.rules"
KEY = re.compile(r'(\w+(?:\{\w+\})?)\s*(==|!=|=)\s*"([^"]*)"')


def rules() -> list[dict[str, tuple[str, str]]]:
    parsed = []
    for line in RULES.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parsed.append(
            {key: (operator, value) for key, operator, value in KEY.findall(line)}
        )
    return parsed


def matches(rule: dict[str, tuple[str, str]], device: dict[str, str]) -> bool:
    for key, (operator, pattern) in rule.items():
        if operator == "=":
            continue
        matched = fnmatch.fnmatchcase(device.get(key, ""), pattern)
        if matched != (operator == "=="):
            return False
    return True


def granted(device: dict[str, str]) -> bool:
    return any(matches(rule, device) for rule in rules())


def usb_device(vendor_id: int, product_id: int, *interfaces: str) -> dict[str, str]:
    return {
        "SUBSYSTEM": "usb",
        "ENV{DEVTYPE}": "usb_device",
        "ATTR{idVendor}": f"{vendor_id:04x}",
        "ATTR{idProduct}": f"{product_id:04x}",
        "ENV{ID_USB_INTERFACES}": ":" + "".join(f"{i}:" for i in interfaces),
    }


def test_every_rule_gives_the_plugdev_group_read_and_write_access():
    for rule in rules():
        assert rule["MODE"] == ("=", "0660")
        assert rule["GROUP"] == ("=", "plugdev")
        assert rule["ENV{DEVTYPE}"] == ("==", "usb_device")


@pytest.mark.parametrize("product_id", sorted(ACCESSORY_PRODUCT_IDS))
def test_grants_access_to_accessory_mode(product_id: int):
    assert granted(usb_device(GOOGLE_VENDOR_ID, product_id, "ff0000"))


@pytest.mark.parametrize("cls", sorted(ANDROID_INTERFACE_CLASSES))
def test_grants_access_to_phones_the_link_tries_to_switch(cls: int):
    assert granted(usb_device(0x04E8, 0x6860, f"{cls:02x}0101"))
    assert granted(usb_device(0x18D1, 0x4EE1, "0a0000", f"{cls:02x}ff00"))


@pytest.mark.parametrize(
    "device",
    [
        usb_device(ESPRESSIF_VENDOR_ID, 0x1001, "020200", "0a0000", "ffff01"),
        usb_device(0x2109, 0x3431, f"{HUB_CLASS:02x}0000"),
        usb_device(0x046D, 0xC31C, "030101"),
        usb_device(0x0781, 0x5581, "080650"),
        usb_device(GOOGLE_VENDOR_ID, 0x2D02, "010100"),
    ],
)
def test_does_not_grant_access_to_devices_the_link_leaves_alone(
    device: dict[str, str],
):
    assert not granted(device)
