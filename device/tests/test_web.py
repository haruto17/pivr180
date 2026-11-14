import socket
import threading
from pathlib import Path

import httpx2
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from pivr180_device.web import STATIC_DIR, create_app, serve

PAGE = "<!doctype html><title>pivr180</title>"


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text(PAGE, encoding="utf-8")
    (static_dir / "assets" / "main.js").write_text("export {}", encoding="utf-8")
    return static_dir


def web_server_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "web-server" and thread.is_alive()
    ]


def test_root_serves_index_html(static_dir: Path):
    client = TestClient(create_app(static_dir=static_dir))

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == PAGE


def test_serves_built_assets(static_dir: Path):
    client = TestClient(create_app(static_dir=static_dir))

    response = client.get("/assets/main.js")

    assert response.status_code == 200
    assert response.text == "export {}"


def test_unknown_path_is_not_found(static_dir: Path):
    client = TestClient(create_app(static_dir=static_dir))

    assert client.get("/missing.js").status_code == 404


def test_serves_the_page_bundled_in_the_package():
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert '<main id="app">' in response.text
    [script] = [
        path for path in (STATIC_DIR / "assets").iterdir() if path.suffix == ".js"
    ]
    assert f'src="/assets/{script.name}"' in response.text
    assert client.get(f"/assets/{script.name}").status_code == 200


def test_routers_are_reachable_alongside_the_page(static_dir: Path):
    router = APIRouter(prefix="/api")

    @router.get("/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(create_app([router], static_dir=static_dir))

    assert client.get("/api/ping").json() == {"status": "ok"}
    assert client.get("/").text == PAGE


def test_serve_listens_until_the_block_ends(static_dir: Path):
    with serve(create_app(static_dir=static_dir), "127.0.0.1", 0) as server:
        [listener] = server.servers[0].sockets
        port = listener.getsockname()[1]
        response = httpx2.get(f"http://127.0.0.1:{port}/")
        running = web_server_threads()

    assert response.status_code == 200
    assert response.text == PAGE
    assert len(running) == 1
    assert web_server_threads() == []
    with pytest.raises(httpx2.ConnectError):
        httpx2.get(f"http://127.0.0.1:{port}/")


def test_serve_fails_when_the_port_is_taken(static_dir: Path):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]

        server = serve(create_app(static_dir=static_dir), "127.0.0.1", port)

        with pytest.raises(RuntimeError, match=f"127.0.0.1:{port}"), server:
            pass

    assert web_server_threads() == []
