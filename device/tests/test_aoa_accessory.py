import pytest

from pivr180_device.aoa.accessory import (
    ACCESSORY_PRODUCT_IDS,
    ESPRESSIF_VENDOR_ID,
    GET_PROTOCOL,
    GOOGLE_VENDOR_ID,
    HUB_CLASS,
    SEND_STRING,
    START,
    AccessoryIdentity,
    is_accessory,
    looks_like_android,
    switch_to_accessory,
)
from pivr180_device.aoa.fake import FakeUsbDevice

CDC_COMM_CLASS = 0x02
CDC_DATA_CLASS = 0x0A
HID_CLASS = 0x03
MASS_STORAGE_CLASS = 0x08


@pytest.mark.parametrize("product_id", sorted(ACCESSORY_PRODUCT_IDS))
def test_google_accessory_product_ids_are_accessories(product_id: int):
    device = FakeUsbDevice(1, vendor_id=GOOGLE_VENDOR_ID, product_id=product_id)

    assert is_accessory(device)


@pytest.mark.parametrize(
    ("vendor_id", "product_id"),
    [
        (GOOGLE_VENDOR_ID, 0x4EE1),
        (GOOGLE_VENDOR_ID, 0x2D02),
        (GOOGLE_VENDOR_ID, 0x2D03),
        (0x04E8, 0x2D00),
    ],
)
def test_other_ids_are_not_accessories(vendor_id: int, product_id: int):
    device = FakeUsbDevice(1, vendor_id=vendor_id, product_id=product_id)

    assert not is_accessory(device)


@pytest.mark.parametrize(
    "interface_classes",
    [
        (0x06,),
        (0xFF,),
        (0x06, 0xFF),
        (0xFF, CDC_COMM_CLASS),
    ],
)
def test_phones_with_mtp_ptp_or_vendor_specific_interfaces_look_like_android(
    interface_classes: tuple[int, ...],
):
    device = FakeUsbDevice(1, vendor_id=0x04E8, interface_classes=interface_classes)

    assert looks_like_android(device)


def test_the_atoms3_lite_does_not_look_like_android():
    atoms3 = FakeUsbDevice(
        1,
        vendor_id=ESPRESSIF_VENDOR_ID,
        product_id=0x1001,
        device_class=0xEF,
        interface_classes=(CDC_COMM_CLASS, CDC_DATA_CLASS, 0xFF),
    )

    assert not looks_like_android(atoms3)


def test_hubs_do_not_look_like_android():
    hub = FakeUsbDevice(1, device_class=HUB_CLASS, interface_classes=(HUB_CLASS,))

    assert not looks_like_android(hub)


@pytest.mark.parametrize(
    "interface_classes",
    [(), (HID_CLASS,), (MASS_STORAGE_CLASS,), (CDC_COMM_CLASS, CDC_DATA_CLASS)],
)
def test_devices_without_android_interfaces_do_not_look_like_android(
    interface_classes: tuple[int, ...],
):
    device = FakeUsbDevice(1, interface_classes=interface_classes)

    assert not looks_like_android(device)


def test_switch_asks_the_protocol_then_sends_the_strings_then_starts():
    device = FakeUsbDevice(1, aoa_version=2)
    identity = AccessoryIdentity(
        manufacturer="m",
        model="mo",
        description="d",
        version="1",
        uri="https://example.invalid/",
        serial="s",
    )

    assert switch_to_accessory(device, identity)

    assert device.controls == [
        (GET_PROTOCOL, 2, b""),
        (SEND_STRING, 0, b"m\0"),
        (SEND_STRING, 1, b"mo\0"),
        (SEND_STRING, 2, b"d\0"),
        (SEND_STRING, 3, b"1\0"),
        (SEND_STRING, 4, b"https://example.invalid/\0"),
        (SEND_STRING, 5, b"s\0"),
        (START, 0, b""),
    ]


def test_switch_sends_the_default_identity():
    device = FakeUsbDevice(1)

    switch_to_accessory(device, AccessoryIdentity())

    strings = [data for request, _, data in device.controls if request == SEND_STRING]
    assert strings == [
        b"pivr180\0",
        b"pivr180\0",
        b"pivr180 stereo camera\0",
        b"1\0",
        b"https://github.com/haruto17/pivr180\0",
        b"\0",
    ]


@pytest.mark.parametrize("aoa_version", [1, 2])
def test_switch_accepts_aoa_version_1_and_later(aoa_version: int):
    device = FakeUsbDevice(1, aoa_version=aoa_version)

    assert switch_to_accessory(device, AccessoryIdentity())
    assert device.controls[-1] == (START, 0, b"")


def test_switch_stops_after_asking_when_aoa_is_unsupported():
    device = FakeUsbDevice(1, aoa_version=0)

    assert not switch_to_accessory(device, AccessoryIdentity())
    assert device.controls == [(GET_PROTOCOL, 2, b"")]


def test_switch_propagates_a_failed_request():
    device = FakeUsbDevice(1, control_error=OSError(32, "Pipe error"))

    with pytest.raises(OSError):
        switch_to_accessory(device, AccessoryIdentity())
    assert device.controls == [(GET_PROTOCOL, 2, b"")]
