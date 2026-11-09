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
   - `uv sync --python /usr/bin/python3` で依存関係をインストールする。
   - venv から `picamera2` と `libcamera` を import できることを確認する。

`device/.python-version` は Pi の OS の Python に合わせて 3.13 を指定している。Mac の開発も同じ 3.13 で行う。

OS の Python が 3.13 でなくなると、`uv run` や `uv sync` が venv を `.python-version` のバージョンで作り直す。すると `--system-site-packages` が外れて picamera2 を import できなくなる。その場合は `device/.python-version` を OS の Python のバージョン（`/usr/bin/python3 --version`）に変更してから、スクリプトを再実行する。

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

## 撮影

`pivr180-capture`（`python -m pivr180_device` でも同じ）で撮影する。GPIO のシャッターボタンは M3 で追加するため、M2 では標準入力をシャッターにする。

1. 保存先を用意する。保存先の親ディレクトリは自動では作らない。

   ```sh
   sudo mkdir -p /data/captures
   sudo chown "$USER" /data/captures
   ```

2. `device/` で起動する。

   ```sh
   uv run pivr180-capture
   ```

   | オプション | 既定値 | 内容 |
   |---|---|---|
   | `--left` | `0` | 左カメラの番号 |
   | `--right` | `1` | 右カメラの番号 |
   | `--captures-dir` | `/data/captures` | 保存先 |

3. 左右の同期（約 7 秒）を待ち、`ready` のログが出たら撮影できる。
   - Enter: 撮影する。保存先がログに出る。
   - `q` + Enter、Ctrl+D、Ctrl+C: 終了する。

動作は次のとおり。

- プレビュー中は、左カメラの ExposureTime / AnalogueGain / ColourGains を右カメラへ随時コピーする。
- Enter を押すと、その時点の左カメラの値で左右とも固定し、左右のフレームを組にして `<captures-dir>/<YYYYMMDD-HHMMSS-NNN>/{left.jpg,right.jpg,meta.json}` に保存する。保存後はプレビューへ戻る。
  - 左右の時刻差が 3 回とも 1ms を超えた場合は、保存したうえで警告をログに出す。
- 撮影や保存に失敗した場合は、エラーをログに出してプレビューへ戻り、次の Enter を待つ。
  - 撮影後にプレビューへ戻せなかった場合（左の AE/AWB の再開や右の設定に失敗した場合）は、エラーを表示して終了する（終了コード 1）。
- 起動時に左右の同期が取れない場合は、エラーを表示して終了する（終了コード 1）。
- プレビュー中の露出/WB のコピーが失敗した場合は、その場でエラーをログに出し、次の入力（Enter・`q` など）で撮影せずに終了する（終了コード 1）。
- 終了時（Ctrl+C を含む）は、プレビュー中のコピーを止めてからカメラを停止し、解放する。

保存した meta.json は、次のコマンドで schema に適合するか確認できる。

```sh
uv run python -c '
import json, sys
from jsonschema import Draft202012Validator
schema = json.load(open("../schema/meta.schema.json"))
Draft202012Validator(schema).validate(json.load(open(sys.argv[1])))
print("ok")
' /data/captures/<YYYYMMDD-HHMMSS-NNN>/meta.json
```
