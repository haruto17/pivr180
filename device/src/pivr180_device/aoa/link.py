import errno
import logging
import threading
from collections.abc import Callable, Hashable
from typing import Protocol, Self

from pivr180_device.aoa.accessory import (
    DEFAULT_IDENTITY,
    AccessoryIdentity,
    is_accessory,
    looks_like_android,
    switch_to_accessory,
)
from pivr180_device.aoa.base import AccessoryPort, UsbBus, UsbDevice
from pivr180_device.aoa.frame import Frame, FrameDecoder, FrameError, encode_frame

logger = logging.getLogger(__name__)

SCAN_INTERVAL_S = 1.0


class ConnectionClosedError(OSError):
    pass


class Connection:
    def __init__(self, port: AccessoryPort, name: str) -> None:
        self._port = port
        self.name = name
        self._lock = threading.Lock()
        self._closed = False
        self._broken = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def broken(self) -> bool:
        with self._lock:
            return self._broken

    def send(self, frame: Frame) -> None:
        data = encode_frame(frame)
        with self._lock:
            if self._closed:
                raise ConnectionClosedError(f"AOA connection to {self.name} is closed")
            if self._broken:
                raise ConnectionClosedError(f"AOA connection to {self.name} is broken")
            try:
                self._port.write(data)
            except OSError:
                # Not left open: a partial write leaves the app mid-frame, so every
                # later frame on this stream would be misread.
                self._broken = True
                raise

    def close(self, *, reset: bool) -> None:
        with self._lock:
            self._closed = True
            if reset:
                try:
                    self._port.reset()
                except OSError as error:
                    logger.debug("could not reset %s (%s)", self.name, error)
            try:
                self._port.close()
            except OSError as error:
                logger.debug("could not close %s (%s)", self.name, error)


class Session(Protocol):
    def on_frame(self, frame: Frame) -> None: ...

    def on_close(self) -> None: ...


SessionFactory = Callable[[Connection], Session]


class LoggingSession:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def on_frame(self, frame: Frame) -> None:
        logger.info(
            "received a %s frame of %d bytes from %s; not handled yet",
            frame.kind.name,
            len(frame.payload),
            self._connection.name,
        )

    def on_close(self) -> None:
        pass


class AoaLink:
    def __init__(
        self,
        bus: UsbBus,
        session_factory: SessionFactory,
        *,
        identity: AccessoryIdentity = DEFAULT_IDENTITY,
        scan_interval_s: float = SCAN_INTERVAL_S,
    ) -> None:
        self._bus = bus
        self._session_factory = session_factory
        self._identity = identity
        self._scan_interval_s = scan_interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tried: set[Hashable] = set()
        self._warned: set[Hashable] = set()
        self._connected = threading.Event()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        if self._thread is not None:
            return
        # Not run on the capture loop: reads block between shots, and a capture
        # blocks for seconds, which would stall the app's requests.
        self._thread = threading.Thread(target=self._run, name="aoa-link", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _run(self) -> None:
        try:
            self._scan_until_stopped()
        # Not raised: shooting must go on without the phone.
        except Exception:
            logger.exception("AOA link stopped on an unexpected error")

    def _scan_until_stopped(self) -> None:
        unavailable = False
        first_scan = True
        while not self._stop.is_set():
            try:
                devices = self._bus.devices()
            except OSError as error:
                if not unavailable:
                    logger.warning(
                        "USB is unavailable (%s); retrying every %.1f s",
                        error,
                        self._scan_interval_s,
                    )
                    unavailable = True
                self._stop.wait(self._scan_interval_s)
                continue
            unavailable = False
            present = {device.key for device in devices}
            self._tried &= present
            self._warned &= present
            for device in devices:
                if self._stop.is_set() or device.key in self._tried:
                    continue
                if is_accessory(device):
                    if first_scan:
                        self._reset_stale(device)
                    else:
                        self._serve(device)
                    # Not scanning on with this list: serving ends when the device
                    # is gone or reset, and the rest of the list may be stale too.
                    break
                if looks_like_android(device):
                    self._switch(device)
            first_scan = False
            self._stop.wait(self._scan_interval_s)

    def _reset_stale(self, device: UsbDevice) -> None:
        # Not opened as is: it was switched before this process started, and the
        # app may be mid-frame on a stream this process never saw the start of.
        logger.info("resetting %s left in accessory mode", device.name)
        self._tried.add(device.key)
        try:
            device.reset()
        except OSError as error:
            logger.warning("could not reset %s (%s)", device.name, error)

    def _switch(self, device: UsbDevice) -> None:
        try:
            switched = switch_to_accessory(device, self._identity)
        except OSError as error:
            if error.errno == errno.EACCES:
                # Not marked as tried: udev may set the permissions only after the
                # device shows up, so the next scan may succeed.
                self._warn_once(device, f"no permission to switch {device.name}")
                return
            self._tried.add(device.key)
            logger.info("%s did not switch to accessory mode (%s)", device.name, error)
            return
        self._tried.add(device.key)
        if switched:
            logger.info("switched %s to accessory mode", device.name)
        else:
            logger.info("%s does not support AOA", device.name)

    def _serve(self, device: UsbDevice) -> None:
        try:
            port = device.open_accessory()
        except OSError as error:
            # Not marked as tried: udev may set the permissions only after the
            # device shows up, so the next scan may succeed.
            self._warn_once(device, f"could not open {device.name} ({error})")
            return
        self._tried.add(device.key)
        connection = Connection(port, device.name)
        logger.info("AOA connected to %s", device.name)
        reset = True
        try:
            session = self._session_factory(connection)
        except Exception:
            logger.exception("could not start an AOA session on %s", device.name)
            connection.close(reset=reset)
            return
        self._connected.set()
        try:
            reset = not self._read_until_lost(port, connection, session)
        finally:
            self._connected.clear()
            connection.close(reset=reset)
            try:
                session.on_close()
            except Exception:
                logger.exception("AOA session failed to close")
            logger.info("AOA disconnected from %s", device.name)

    def _read_until_lost(
        self, port: AccessoryPort, connection: Connection, session: Session
    ) -> bool:
        decoder = FrameDecoder()
        while not self._stop.is_set():
            if connection.broken:
                logger.warning("failed to send to %s; reconnecting", connection.name)
                return False
            try:
                frames = decoder.feed(port.read())
            except FrameError as error:
                logger.warning(
                    "corrupted stream from %s (%s); reconnecting",
                    connection.name,
                    error,
                )
                return False
            except OSError as error:
                logger.warning("lost %s (%s); reconnecting", connection.name, error)
                return False
            for frame in frames:
                try:
                    session.on_frame(frame)
                # Not dropping the connection: one bad frame must not cut off the
                # app, and the session answers errors itself.
                except Exception:
                    logger.exception(
                        "AOA session failed to handle a frame from %s",
                        connection.name,
                    )
        return True

    def _warn_once(self, device: UsbDevice, message: str) -> None:
        if device.key in self._warned:
            return
        self._warned.add(device.key)
        logger.warning("%s; retrying every %.1f s", message, self._scan_interval_s)
