import threading

import pytest

from pivr180_device.camera import CameraPair
from pivr180_device.camera.fake import FakeCamera
from pivr180_device.exposure import ExposureSync
from pivr180_device.slot import CameraSlot, LiveCameras

WAIT_S = 5.0


def make_cameras() -> LiveCameras:
    pair = CameraPair(left=FakeCamera("left"), right=FakeCamera("right"))
    return LiveCameras(pair=pair, exposure=ExposureSync(pair))


def test_lends_nothing_before_cameras_are_attached():
    slot = CameraSlot()

    with slot.borrow() as cameras:
        assert cameras is None
    assert not slot.ready


def test_lends_the_attached_cameras_until_they_are_detached():
    slot = CameraSlot()
    live = make_cameras()

    with slot.attach(live):
        with slot.borrow() as cameras:
            assert cameras is live
        assert slot.ready

    with slot.borrow() as cameras:
        assert cameras is None
    assert not slot.ready


def test_refuses_to_attach_cameras_twice():
    slot = CameraSlot()

    with (
        slot.attach(make_cameras()),
        pytest.raises(RuntimeError, match="already"),
        slot.attach(make_cameras()),
    ):
        pass


def test_can_attach_again_after_detaching():
    slot = CameraSlot()
    with slot.attach(make_cameras()):
        pass
    live = make_cameras()

    with slot.attach(live), slot.borrow() as cameras:
        assert cameras is live


def test_detaching_waits_for_borrowers_to_return_the_cameras():
    slot = CameraSlot()
    borrowed = threading.Event()
    give_back = threading.Event()
    detached = threading.Event()
    returned_before_detached: list[bool] = []

    def borrower() -> None:
        with slot.borrow():
            borrowed.set()
            give_back.wait(WAIT_S)
            returned_before_detached.append(not detached.is_set())

    def owner() -> None:
        with slot.attach(make_cameras()):
            thread = threading.Thread(target=borrower)
            thread.start()
            borrowed.wait(WAIT_S)
        detached.set()
        thread.join(WAIT_S)

    owner_thread = threading.Thread(target=owner)
    owner_thread.start()
    borrowed.wait(WAIT_S)

    assert not detached.wait(0.05)
    with slot.borrow() as cameras:
        assert cameras is None
    give_back.set()
    owner_thread.join(WAIT_S)
    assert detached.is_set()
    assert returned_before_detached == [True]
