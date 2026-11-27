import argparse
import logging
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, ExitStack
from functools import partial
from pathlib import Path
from typing import TextIO

from fastapi import FastAPI

from pivr180_device.aoa.base import UsbBus
from pivr180_device.aoa.link import AoaLink
from pivr180_device.aoa.pyusb import PyUsbBus
from pivr180_device.aoa.session import AoaServices, AoaSession
from pivr180_device.atoms3.base import SerialLink
from pivr180_device.atoms3.pyserial import DEFAULT_PORT, open_serial_link
from pivr180_device.button import ButtonShutter, Status
from pivr180_device.camera.base import CameraPair
from pivr180_device.camera.picamera2 import open_camera_pair
from pivr180_device.camera_settings import CameraSettingsControl, settings_router
from pivr180_device.captures_api import captures_router
from pivr180_device.exposure import ExposurePreview, ExposureSettings, ExposureSync
from pivr180_device.power import power_off
from pivr180_device.preview import PreviewFrames, preview_router
from pivr180_device.shutdown import ShutdownRequest, shutdown_router
from pivr180_device.slot import CameraSlot, LiveCameras
from pivr180_device.status import StatusBoard
from pivr180_device.storage import DEFAULT_CAPTURE_ROOT, CaptureStorage
from pivr180_device.sync import SyncedPair, capture_synced_pair
from pivr180_device.web import create_app, serve

logger = logging.getLogger(__name__)

QUIT_COMMANDS = frozenset({"q", "quit"})
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130
SHUTTER_BUTTON = "button"
SHUTTER_STDIN = "stdin"
WEB_HOST = "0.0.0.0"
DEFAULT_WEB_PORT = 80
APP_SHUTTER = "app"

OpenPair = Callable[[int, int], AbstractContextManager[CameraPair]]
OpenLink = Callable[[str], SerialLink]
ShowStatus = Callable[[Status], None]
ServeWeb = Callable[[FastAPI, str, int], AbstractContextManager[object]]


def _ignore_status(status: Status) -> None:
    pass


def stdin_triggers(stream: TextIO) -> Iterator[None]:
    for line in stream:
        if line.strip().lower() in QUIT_COMMANDS:
            return
        yield


def shoot(
    pair: CameraPair, exposure: ExposureSync, storage: CaptureStorage
) -> tuple[Path, SyncedPair]:
    def capture(settings: ExposureSettings) -> tuple[Path, SyncedPair]:
        synced = capture_synced_pair(pair)
        return storage.save_capture(pair, synced), synced

    return exposure.shoot(capture)


def run(
    pair: CameraPair,
    storage: CaptureStorage,
    triggers: Iterable[object],
    show: ShowStatus = _ignore_status,
    slot: CameraSlot | None = None,
    board: StatusBoard | None = None,
) -> None:
    if slot is None:
        slot = CameraSlot()

    def report(status: Status, error_message: str | None = None) -> None:
        show(status)
        if board is not None:
            board.show(status, error_message)

    def preview_failed() -> None:
        report(Status.ERROR, f"camera preview stopped: {_describe(preview.error)}")

    pair.start()
    try:
        # Not left to the first preview frame or shot: waiting for SyncReady on
        # both cameras here makes a sync timeout fail at startup, and "ready" is
        # logged only once a shot no longer has to wait for it.
        pair.left.capture_metadata()
        pair.right.capture_metadata()
        exposure = ExposureSync(pair)
        preview = ExposurePreview(exposure, on_error=preview_failed)
        with preview, slot.attach(LiveCameras(pair=pair, exposure=exposure)):
            logger.info("ready to shoot")
            report(Status.IDLE)
            # Not trusting idle alone: the preview may have died before it was
            # shown, and its error is recorded before on_error shows it.
            if preview.error is not None:
                preview_failed()
            for _ in triggers:
                # Not shooting on: the preview thread dies only on a camera error,
                # and leaving the block makes stop() raise it instead of hiding it.
                if not preview.running:
                    break
                report(Status.CAPTURING)
                try:
                    directory, synced = shoot(pair, exposure, storage)
                except Exception as error:
                    # Not continuing while still locked: a failed resume leaves
                    # sync_once a no-op, so left AE/AWB and the copy would not run.
                    if exposure.locked_settings is not None:
                        raise
                    logger.exception("capture failed; back to preview")
                    report(Status.ERROR, f"capture failed: {_describe(error)}")
                    continue
                if board is not None:
                    board.saved(directory.name, synced.warning)
                report(Status.IDLE)
                # Not trusting idle alone: the preview may have died during the
                # shot, and its error is recorded before on_error shows it.
                if preview.error is not None:
                    preview_failed()
                if synced.warning:
                    logger.warning(
                        "saved %s with sync warning: timestamp diff %d ns "
                        "after %d attempts",
                        directory,
                        synced.timestamp_diff_ns,
                        synced.attempts,
                    )
                else:
                    logger.info("saved %s", directory)
    finally:
        pair.stop()


def _describe(error: BaseException | None) -> str:
    if error is None:
        return "unknown error"
    return str(error) or type(error).__name__


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pivr180-capture",
        description=(
            "Preview with left exposure/WB copied to the right camera, and shoot "
            "a left/right pair on each shutter press. Holding the AtomS3 Lite "
            "button for 3 s powers off."
        ),
    )
    parser.add_argument("--left", type=int, default=0, help="left camera index")
    parser.add_argument("--right", type=int, default=1, help="right camera index")
    parser.add_argument(
        "--captures-dir",
        type=Path,
        default=DEFAULT_CAPTURE_ROOT,
        help=f"directory to save captures in (default: {DEFAULT_CAPTURE_ROOT})",
    )
    parser.add_argument(
        "--shutter",
        choices=(SHUTTER_BUTTON, SHUTTER_STDIN),
        default=SHUTTER_BUTTON,
        help=(
            "button: the AtomS3 Lite button; stdin: Enter to shoot, "
            "q + Enter to quit (default: button)"
        ),
    )
    parser.add_argument(
        "--button-port",
        default=DEFAULT_PORT,
        help=f"AtomS3 Lite serial device path or glob (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=DEFAULT_WEB_PORT,
        help=f"port to serve the phone web UI on (default: {DEFAULT_WEB_PORT})",
    )
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    open_pair: OpenPair = open_camera_pair,
    stdin: TextIO | None = None,
    open_link: OpenLink = open_serial_link,
    shutdown: Callable[[], None] = power_off,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    serve_web: ServeWeb = serve,
    open_usb_bus: Callable[[], UsbBus] = PyUsbBus,
) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    storage = CaptureStorage(args.captures_dir)
    slot = CameraSlot()
    camera_settings = CameraSettingsControl(slot)
    shutter: ButtonShutter | None = None
    shutdown_request = ShutdownRequest()
    board = StatusBoard(storage)
    aoa_services = AoaServices(
        slot=slot,
        storage=storage,
        settings=camera_settings,
        board=board,
        preview=PreviewFrames(slot).latest,
        shutter=lambda: shutdown_request.trigger(APP_SHUTTER),
        request_shutdown=shutdown_request.request,
    )
    code = EXIT_OK
    try:
        with ExitStack() as stack:
            try:
                app = create_app(
                    [
                        preview_router(slot),
                        settings_router(camera_settings),
                        shutdown_router(shutdown_request.request),
                        captures_router(storage),
                    ]
                )
                stack.enter_context(serve_web(app, WEB_HOST, args.web_port))
            except Exception:
                # Not exiting: shooting with the button must keep working
                # without the phone, e.g. when port 80 cannot be bound.
                logger.exception("web UI is unavailable; shooting continues")
            stack.enter_context(
                AoaLink(open_usb_bus(), partial(AoaSession, services=aoa_services))
            )
            triggers: Iterable[object]
            show: ShowStatus = _ignore_status
            if args.shutter == SHUTTER_BUTTON:
                shutter = stack.enter_context(
                    ButtonShutter(
                        lambda: open_link(args.button_port), clock=clock, sleep=sleep
                    )
                )
                triggers = shutter
                show = shutter.show
            else:
                triggers = stdin_triggers(sys.stdin if stdin is None else stdin)
            try:
                with open_pair(args.left, args.right) as pair:
                    run(
                        pair,
                        storage,
                        shutdown_request.until_requested(triggers),
                        show,
                        slot,
                        board,
                    )
            except Exception:
                show(Status.ERROR)
                raise
    except KeyboardInterrupt:
        logger.info("interrupted; cameras released")
        return EXIT_INTERRUPTED
    except Exception:
        logger.exception("capture stopped on error; cameras released")
        code = EXIT_ERROR
    # Not skipped after an error: the hold or the phone was the user's request, and
    # by now the capture under way has ended and the cameras and the button are
    # released.
    if shutdown_request.requested or (
        shutter is not None and shutter.shutdown_requested
    ):
        logger.info("powering off")
        try:
            shutdown()
        except Exception:
            logger.exception("failed to power off")
            return EXIT_ERROR
    return code
