import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"
STARTUP_POLL_S = 0.01


def create_app(
    routers: Iterable[APIRouter] = (), static_dir: Path = STATIC_DIR
) -> FastAPI:
    app = FastAPI(title="pivr180")
    for router in routers:
        app.include_router(router)
    # Not mounted before the routers: a mount at "/" matches every path, so
    # routes added after it would never be reached.
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


@contextmanager
def serve(app: FastAPI, host: str, port: int) -> Iterator[uvicorn.Server]:
    # Not uvicorn's own log config: it would add handlers that bypass the
    # capture software's logging format.
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_config=None))

    def run() -> None:
        # Not left to propagate: uvicorn exits with SystemExit when it cannot
        # listen, and the error is raised below once the thread has ended.
        with suppress(SystemExit):
            server.run()

    thread = threading.Thread(target=run, name="web-server", daemon=True)
    thread.start()
    try:
        while not server.started:
            if not thread.is_alive():
                raise RuntimeError(f"web server failed to listen on {host}:{port}")
            time.sleep(STARTUP_POLL_S)
        yield server
    finally:
        server.should_exit = True
        thread.join()
