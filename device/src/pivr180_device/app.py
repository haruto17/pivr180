import argparse
import logging
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TextIO

from pivr180_device.camera.base import CameraPair
from pivr180_device.camera.picamera2 import open_camera_pair
from pivr180_device.exposure import ExposurePreview, ExposureSettings, ExposureSync
from pivr180_device.storage import DEFAULT_CAPTURE_ROOT, CaptureStorage
from pivr180_device.sync import SyncedPair, capture_synced_pair

logger = logging.getLogger(__name__)

QUIT_COMMANDS = frozenset({"q", "quit"})
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130

OpenPair = Callable[[int, int], AbstractContextManager[CameraPair]]


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


def run(pair: CameraPair, storage: CaptureStorage, triggers: Iterable[object]) -> None:
    pair.start()
    try:
        # Not left to the first preview frame or shot: waiting for SyncReady on
        # both cameras here makes a sync timeout fail at startup, and "ready" is
        # logged only once a shot no longer has to wait for it.
        pair.left.capture_metadata()
        pair.right.capture_metadata()
        exposure = ExposureSync(pair)
        with ExposurePreview(exposure) as preview:
            logger.info("ready: press Enter to shoot, q + Enter to quit")
            for _ in triggers:
                # Not shooting on: the preview thread dies only on a camera error,
                # and leaving the block makes stop() raise it instead of hiding it.
                if not preview.running:
                    break
                try:
                    directory, synced = shoot(pair, exposure, storage)
                except Exception:
                    logger.exception("capture failed; back to preview")
                    continue
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
            "a left/right pair each time Enter is pressed."
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
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    open_pair: OpenPair = open_camera_pair,
    stdin: TextIO | None = None,
) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    storage = CaptureStorage(args.captures_dir)
    try:
        with open_pair(args.left, args.right) as pair:
            run(pair, storage, stdin_triggers(sys.stdin if stdin is None else stdin))
    except KeyboardInterrupt:
        logger.info("interrupted; cameras released")
        return EXIT_INTERRUPTED
    except Exception:
        logger.exception("capture stopped on error; cameras released")
        return EXIT_ERROR
    return EXIT_OK
