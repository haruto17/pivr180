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

`pivr180-capture`（`python -m pivr180_device` でも同じ）で撮影する。シャッターは USB でつないだ AtomS3 Lite のボタンを使う（[AtomS3 Lite のボタン](#atoms3-lite-のボタン)）。開発用に、標準入力をシャッターにすることもできる。

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
   | `--shutter` | `button` | `button`: AtomS3 Lite のボタン、`stdin`: 標準入力 |
   | `--button-port` | `/dev/serial/by-id/usb-Espressif*` | AtomS3 Lite のシリアルデバイスのパス（glob も可） |

3. 左右の同期（約 7 秒）を待ち、`ready` のログが出たら撮影できる。
   - `--shutter button`（既定）
     - ボタンを押して 3 秒以内に離す: 撮影する。保存先がログに出る。
     - ボタンを 3 秒押し続ける: カメラとシリアルを解放してから、Pi をシャットダウンする。
     - Ctrl+C: 終了する。
   - `--shutter stdin`
     - Enter: 撮影する。保存先がログに出る。
     - `q` + Enter、Ctrl+D、Ctrl+C: 終了する。

動作は次のとおり。

- プレビュー中は、左カメラの ExposureTime / AnalogueGain / ColourGains を右カメラへ随時コピーする。
- シャッターを押すと、その時点の左カメラの値で左右とも固定し、左右のフレームを組にして `<captures-dir>/<YYYYMMDD-HHMMSS-NNN>/{left.jpg,right.jpg,meta.json}` に保存する。保存後はプレビューへ戻る。
  - 左右の時刻差が 3 回とも 1ms を超えた場合は、保存したうえで警告をログに出す。
- 撮影や保存に失敗した場合は、エラーをログに出してプレビューへ戻り、次のシャッターを待つ。
  - 撮影後にプレビューへ戻せなかった場合（左の AE/AWB の再開や右の設定に失敗した場合）は、エラーを表示して終了する（終了コード 1）。
- 起動時に左右の同期が取れない場合は、エラーを表示して終了する（終了コード 1）。
- プレビュー中の露出/WB のコピーが失敗した場合は、その場でエラーをログに出し、次のシャッター（標準入力では `q` なども）で撮影せずに終了する（終了コード 1）。
- 終了時（Ctrl+C を含む）は、プレビュー中のコピーを止めてからカメラを停止し、解放する。

## AtomS3 Lite のボタン

AtomS3 Lite とは USB シリアルで通信する。メッセージの書式は [firmware/PROTOCOL.md](../firmware/PROTOCOL.md) を参照。

- `press` を受け取った時刻から押している時間を測る。
  - 3 秒経つ前に `release` を受け取ったら、1 回撮影する。押した時点で撮影しないのは、シャットダウンのための長押しで撮影しないため。
  - 押したまま 3 秒経ったら、離すのを待たずにシャットダウンする。
- ボタンのメッセージは撮影とは別のスレッドで受け取り、受け取った時刻で判定する。撮影・保存中に押した場合も、押している時間は正しく測る。
  - 撮影中の短押しは、その撮影が終わってから撮影する。
  - 撮影中に 3 秒の長押しが成立した場合は、その撮影の保存が終わってからシャットダウンする。その撮影やプレビューへの復帰に失敗した場合も、エラーをログに出し、カメラとシリアルを解放してからシャットダウンする。この場合、シャットダウンできたかどうかにかかわらず終了コードは 1 になる。シャットダウン自体に失敗した場合も終了コードは 1 になる。
- 行末の `\r`、知らないメッセージ、`press` のない `release` は無視する。
- AtomS3 Lite が見つからない場合や抜けた場合は、1 秒ごとに開き直す。抜ける前に押していた分は捨てる。

### デバイスの名前

`/dev/ttyACM0` などの番号は接続の順番で変わるため、`/dev/serial/by-id/` の名前で開く。名前には個体ごとのシリアル番号が入るため、既定値は `/dev/serial/by-id/usb-Espressif*` の glob にしている。一致するデバイスが 1 つのときだけ開き、0 個や 2 個以上のときは開かずに待つ。

Pi に AtomS3 Lite をつないで、実際の名前を確認する。

```sh
ls -l /dev/serial/by-id/
# 例: usb-Espressif_USB_JTAG_serial_debug_unit_XX:XX:XX:XX:XX:XX-if00 -> ../../ttyACM0
```

他の Espressif 製のデバイスもつなぐ場合は、`--button-port` に確認した名前をそのまま指定する。

シリアルデバイスを開くには、実行するユーザーが `dialout` グループに入っている必要がある（Raspberry Pi OS の初期ユーザーは入っている）。

```sh
groups  # dialout が含まれるか確認する
sudo usermod -aG dialout "$USER"  # 含まれない場合。再ログイン後に有効になる
```

### シャットダウンの権限

シャットダウンは `systemctl --no-ask-password poweroff` で行う。Pi の画面でログインしている場合はそのまま実行できるが、SSH や systemd から起動した場合は polkit の許可が必要になる。許可がない場合は、パスワードを尋ねずに失敗し、エラーをログに出して終了する（終了コード 1）。

撮影ソフトを実行するユーザーに許可するため、`/etc/polkit-1/rules.d/50-pivr180-poweroff.rules` を作る。`<ユーザー名>` は、撮影ソフトを実行するユーザーの名前（`whoami` で確認できる）に置き換える。現在の Raspberry Pi OS には既定の `pi` ユーザーはなく、OS の書き込み時に設定したユーザーになる。

```js
polkit.addRule(function (action, subject) {
  if (
    (action.id == "org.freedesktop.login1.power-off" ||
      action.id == "org.freedesktop.login1.power-off-multiple-sessions") &&
    subject.user == "<ユーザー名>"
  ) {
    return polkit.Result.YES;
  }
});
```

- `/etc/polkit-1/rules.d/` は root と polkitd しか読めないため、作成や確認には sudo が必要になる（例: `sudo nano /etc/polkit-1/rules.d/50-pivr180-poweroff.rules`、`sudo ls -l /etc/polkit-1/rules.d/`）。
- polkitd はルールの変更を自動で読み込む。反映されない場合は `sudo systemctl restart polkit` を実行する。
- ルールの読み込みエラーは `sudo journalctl -u polkit` で確認できる。

次のコマンドで、パスワードを尋ねられずにシャットダウンできれば設定できている。

```sh
systemctl --no-ask-password poweroff
```

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
