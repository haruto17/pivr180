import json
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pivr180_device.captures_api import captures_router
from pivr180_device.storage import CaptureStorage
from pivr180_device.web import create_app

STILL_SIZE = (4056, 3040)


def jpeg(size: tuple[int, int], color: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="JPEG")
    return buffer.getvalue()


def add_capture(
    root: Path,
    name: str,
    meta: object = None,
    images: tuple[str, ...] = ("left.jpg", "right.jpg"),
) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    for image, color in zip(images, ("red", "blue"), strict=False):
        (directory / image).write_bytes(jpeg(STILL_SIZE, color))
    if meta is not None:
        (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return directory


def meta_with_warning(warning: bool) -> dict[str, object]:
    return {"sync": {"timestamp_diff_ns": 250_000, "attempts": 1, "warning": warning}}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "captures"


@pytest.fixture
def client(root: Path, tmp_path: Path) -> TestClient:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    router = captures_router(CaptureStorage(root))
    return TestClient(create_app([router], static_dir=static_dir))


def test_lists_captures_newest_first_with_their_sync_warning(
    root: Path, client: TestClient
):
    add_capture(root, "20261107-123456-000", meta_with_warning(False))
    add_capture(root, "20261108-090000-000", meta_with_warning(True))

    response = client.get("/api/captures")

    assert response.status_code == 200
    assert response.json() == [
        {"id": "20261108-090000-000", "complete": True, "sync_warning": True},
        {"id": "20261107-123456-000", "complete": True, "sync_warning": False},
    ]


def test_lists_nothing_before_the_first_capture(client: TestClient):
    assert client.get("/api/captures").json() == []


@pytest.mark.parametrize(
    ("meta", "images"),
    [
        (None, ("left.jpg", "right.jpg")),
        (meta_with_warning(False), ("left.jpg",)),
        (meta_with_warning(False), ()),
    ],
    ids=["no-meta", "no-right-image", "no-images"],
)
def test_marks_captures_left_unfinished_as_incomplete(
    root: Path, client: TestClient, meta: object, images: tuple[str, ...]
):
    add_capture(root, "20261107-123456-000", meta, images)

    [capture] = client.get("/api/captures").json()

    assert capture["id"] == "20261107-123456-000"
    assert capture["complete"] is False


@pytest.mark.parametrize(
    "meta_text",
    ["{", "[]", '{"sync": {}}', '{"sync": {"warning": "yes"}}'],
    ids=["truncated", "not-an-object", "no-warning", "not-a-bool"],
)
def test_sync_warning_is_unknown_when_meta_does_not_say(
    root: Path, client: TestClient, meta_text: str
):
    directory = add_capture(root, "20261107-123456-000")
    (directory / "meta.json").write_text(meta_text, encoding="utf-8")

    [capture] = client.get("/api/captures").json()

    assert capture["sync_warning"] is None


@pytest.mark.parametrize(("side", "color"), [("left", "red"), ("right", "blue")])
def test_thumbnail_is_a_small_jpeg_of_the_side(
    root: Path, client: TestClient, side: str, color: str
):
    add_capture(root, "20261107-123456-000", meta_with_warning(False))

    response = client.get(f"/api/captures/20261107-123456-000/thumbnails/{side}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert "max-age" in response.headers["cache-control"]
    with Image.open(BytesIO(response.content)) as image:
        assert image.format == "JPEG"
        assert image.size == (480, 360)
        red, _, blue = image.getpixel((240, 180))
    assert (red > blue) == (color == "red")


@pytest.mark.parametrize(
    "path",
    [
        "/api/captures/20261107-123456-001/thumbnails/left",
        "/api/captures/20261107-123456-002/thumbnails/right",
        "/api/captures/20261107-123456-003/thumbnails/left",
        "/api/captures/..%2F..%2Fetc/thumbnails/left",
        "/api/captures/notes/thumbnails/left",
    ],
    ids=["missing-capture", "missing-image", "broken-image", "traversal", "bad-id"],
)
def test_thumbnail_is_not_found_unless_the_capture_has_the_image(
    root: Path, client: TestClient, path: str
):
    add_capture(root, "20261107-123456-002", images=("left.jpg",))
    broken = add_capture(root, "20261107-123456-003", images=())
    (broken / "left.jpg").write_bytes(b"not a jpeg")
    (root / "notes").mkdir()
    (root / "notes" / "left.jpg").write_bytes(jpeg((8, 8), "red"))

    assert client.get(path).status_code == 404


def test_thumbnail_rejects_an_unknown_side(root: Path, client: TestClient):
    add_capture(root, "20261107-123456-000")

    response = client.get("/api/captures/20261107-123456-000/thumbnails/center")

    assert response.status_code == 422


def test_deletes_the_capture(root: Path, client: TestClient):
    kept = add_capture(root, "20261107-123456-000", meta_with_warning(False))
    deleted = add_capture(root, "20261107-123456-001", meta_with_warning(False))

    response = client.delete(f"/api/captures/{deleted.name}")

    assert response.status_code == 204
    assert list(root.iterdir()) == [kept]
    assert [c["id"] for c in client.get("/api/captures").json()] == [kept.name]


@pytest.mark.parametrize(
    "capture_id",
    ["20261107-123456-001", "%2E%2E", "notes", "20261107-123456"],
)
def test_delete_is_not_found_unless_the_id_names_a_capture(
    root: Path, client: TestClient, capture_id: str
):
    kept = add_capture(root, "20261107-123456-000")
    (root / "notes").mkdir()

    response = client.delete(f"/api/captures/{capture_id}")

    assert response.status_code == 404
    assert sorted(path.name for path in root.iterdir()) == [kept.name, "notes"]


def test_delete_cannot_reach_outside_the_capture_root(
    root: Path, tmp_path: Path, client: TestClient
):
    add_capture(root, "20261107-123456-000")
    outside = tmp_path / "keep"
    outside.mkdir()

    response = client.delete("/api/captures/..%2F..%2Fkeep")

    assert response.is_client_error
    assert outside.is_dir()
    assert root.is_dir()
