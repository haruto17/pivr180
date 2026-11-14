import argparse
import logging
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, ExitStack
from pathlib import Path
from typing import TextIO

from fastapi import FastAPI

from pivr180_device.atoms3.base import SerialLink
from pivr180_device.atoms3.pyserial import DEFAULT_PORT, open_serial_link
from pivr180_device.button import ButtonShutter, Status
from pivr180_device.camera.base import CameraPair
from pivr180_device.camera.picamera2 import open_camera_pair
from pivr180_device.exposure import ExposurePreview, ExposureSettings, ExposureSync
from pivr180_device.power import power_off
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
) -> None:
    pair.start()
    try:
        # Not left to the first preview frame or shot: waiting for SyncReady on
        # both cameras here makes a sync timeout fail at startup, and "ready" is
        # logged only once a shot no longer has to wait for it.
        pair.left.capture_metadata()
        pair.right.capture_metadata()
        exposure = ExposureSync(pair)
        with ExposurePreview(exposure, on_error=lambda: show(Status.ERROR)) as preview:
            logger.info("ready to shoot")
            show(Status.IDLE)
            # Not trusting idle alone: the preview may have died before it was
            # shown, and its error is recorded before on_error shows it.
            if preview.error is not None:
                show(Status.ERROR)
            for _ in triggers:
                # Not shooting on: the preview thread dies only on a camera error,
                # and leaving the block makes stop() raise it instead of hiding it.
                if not preview.running:
                    break
                show(Status.CAPTURING)
                try:
                    directory, synced = shoot(pair, exposure, storage)
                except Exception:
                    # Not continuing while still locked: a failed resume leaves
                    # sync_once a no-op, so left AE/AWB and the copy would not run.
                    if exposure.locked_settings is not None:
                        raise
                    logger.exception("capture failed; back to preview")
                    show(Status.ERROR)
                    continue
                show(Status.IDLE)
                # Not trusting idle alone: the preview may have died during the
                # shot, and its error is recorded before on_error shows it.
                if preview.error is not None:
                    show(Status.ERROR)
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
) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    storage = CaptureStorage(args.captures_dir)
    shutter: ButtonShutter | None = None
    code = EXIT_OK
    try:
        with ExitStack() as stack:
            try:
                stack.enter_context(serve_web(create_app(), WEB_HOST, args.web_port))
            except Exception:
                # Not exiting: shooting with the button must keep working
                # without the phone, e.g. when port 80 cannot be bound.
                logger.exception("web UI is unavailable; shooting continues")
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
                    run(pair, storage, triggers, show)
            except Exception:
                show(Status.ERROR)
                raise
    except KeyboardInterrupt:
        logger.info("interrupted; cameras released")
        return EXIT_INTERRUPTED
    except Exception:
        logger.exception("capture stopped on error; cameras released")
        code = EXIT_ERROR
    # Not skipped after an error: the hold was the user's request, and by now the
    # capture under way has ended and the cameras and the button are released.
    if shutter is not None and shutter.shutdown_requested:
        logger.info("powering off")
        try:
            shutdown()
        except Exception:
            logger.exception("failed to power off")
            return EXIT_ERROR
    return code
