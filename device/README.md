# device

Raspberry Pi 5 上で動く撮影ソフト。

## Mac での開発

```sh
uv sync
uv run pytest
uv run ruff check
uv run ruff format --check
```

Mac には picamera2 がないため、テストは Fake（`pivr180_device.camera.fake`）やスタブを使う。

## Raspberry Pi での venv の作成

Picamera2 と libcamera の Python バインディングは apt の OS パッケージ（`python3-picamera2`）で入れる。pip / uv ではインストールできないため、venv は `--system-site-packages` で作成し、OS 側のパッケージを参照できるようにする。

1. Picamera2 と uv をインストールする。

   ```sh
   sudo apt update
   sudo apt install -y python3-picamera2
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. `device/` で次のスクリプトを実行する。

   ```sh
   ./scripts/setup_pi_venv.sh
   ```

   スクリプトは次のことを行う。

   - `uv venv --clear --system-site-packages --python /usr/bin/python3` で venv を作り直す。`python3-picamera2` は OS の Python 向けにビルドされているため、uv が管理する Python ではなく `/usr/bin/python3` を使う。
   - `uv sync` で依存関係をインストールする。
   - venv から `picamera2` と `libcamera` を import できることを確認する。

OS の Python のバージョンが変わったときなどに `uv sync` が venv を作り直すと、`--system-site-packages` が外れて picamera2 を import できなくなる。その場合はスクリプトを再実行する。

## カメラ

`pivr180_device.camera.picamera2.open_camera_pair()` で左右のカメラを開く。

- 左カメラを libcamera のカメラ同期のサーバー、右カメラをクライアントにする（`SyncMode`）。
- 左右とも 4056×3040、10fps に固定して開始する。
- 開始後最初のフレームは、左右の同期が取れる（`SyncReady`）まで待ってから返す。
  - サーバーは 30 フレームごと（libcamera `rpi.sync` の既定）にタイミングをクライアントへ送り、クライアントはそれを受けてフレーム長を補正する。
  - `SyncReady` はサーバーの開始から 70 フレーム後（10fps で約 7 秒）とし、2 回目の通知（60 フレーム目）による補正がセンサーに反映されるまでの余裕を 10 フレーム取っている。

```python
from pivr180_device.camera.picamera2 import open_camera_pair

with open_camera_pair(left_index=0, right_index=1) as pair:
    pair.start()
    try:
        left = pair.left.capture_frame()
        right = pair.right.capture_frame()
    finally:
        pair.stop()
```

カメラの番号は `rpicam-hello --list-cameras` で確認できる。
