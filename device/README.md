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

スマホ Web UI の画面（`web/`）は Node.js 24 と pnpm 10 で開発する（[スマホ Web UI](#スマホ-web-ui)）。

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
- プレビュー用に、低解像度の `lores` ストリーム（640×480、RGB888）も出力する。`capture_preview()` は、次のフレームの `lores` を Picamera2 の `post_callback` で受け取って返す。`capture_request` を使わないため、撮影や露出のコピーとフレームを取り合わない。
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
   | `--web-port` | `80` | スマホ Web UI のポート（[スマホ Web UI](#スマホ-web-ui)） |

3. 左右の同期（約 7 秒）を待ち、`ready` のログが出たら撮影できる。`--shutter button` では、AtomS3 Lite の LED が緑の点灯になる（[状態の表示](#状態の表示)）。
   - `--shutter button`（既定）
     - ボタンを押して 3 秒以内に離す: 撮影する。保存先がログに出る。
     - ボタンを 3 秒押し続ける: カメラとシリアルを解放してから、Pi をシャットダウンする。
     - Ctrl+C: 終了する。
   - `--shutter stdin`
     - Enter: 撮影する。保存先がログに出る。
     - `q` + Enter、Ctrl+D、Ctrl+C: 終了する。
   - どちらのシャッターでも、スマホ Web UI の「シャットダウン」で、カメラとシリアルを解放してから Pi をシャットダウンする（[Web UI からのシャットダウン](#web-ui-からのシャットダウン)）。

動作は次のとおり。

- プレビュー中は、左カメラの ExposureTime / AnalogueGain / ColourGains を右カメラへ随時コピーする。
- シャッターを押すと、その時点の左カメラの値で左右とも固定し、左右のフレームを組にして `<captures-dir>/<YYYYMMDD-HHMMSS-NNN>/{left.jpg,right.jpg,meta.json}` に保存する。保存後はプレビューへ戻る。
  - 左右の時刻差が 3 回とも 1ms を超えた場合は、保存したうえで警告をログに出す。
- 撮影や保存に失敗した場合は、エラーをログに出してプレビューへ戻り、次のシャッターを待つ。
  - 撮影後にプレビューへ戻せなかった場合（左の AE/AWB の再開や右の設定に失敗した場合）は、エラーを表示して終了する（終了コード 1）。
- 起動時に左右の同期が取れない場合は、エラーを表示して終了する（終了コード 1）。
- プレビュー中の露出/WB のコピーが失敗した場合は、その場でエラーをログに出し、次のシャッター（標準入力では `q` なども）で撮影せずに終了する（終了コード 1）。
- 終了時（Ctrl+C を含む）は、プレビュー中のコピーを止めてからカメラを停止し、解放する。

## 自動起動

撮影ソフトを systemd のサービス（`pivr180-capture.service`）にして、Pi の起動時にログインなしで起動する。

1. 次のことを済ませておく。
   - `./scripts/setup_pi_venv.sh` で venv を作る（[Raspberry Pi での venv の作成](#raspberry-pi-での-venv-の作成)）。
   - 保存先の `/data/captures` を作り、実行するユーザーを所有者にする（[撮影](#撮影)）。
   - 実行するユーザーを `dialout` グループに入れる（[デバイスの名前](#デバイスの名前)）。
   - polkit のルールを作る（[シャットダウンの権限](#シャットダウンの権限)）。systemd から起動した撮影ソフトは、ルールがないと長押しや Web UI からシャットダウンできない。

2. `device/` で次のスクリプトを実行する。

   ```sh
   ./scripts/install_service.sh
   ```

   スクリプトは、`systemd/pivr180-capture.service.in` の実行ユーザーと `device/` のパスを、スクリプトを実行したユーザーと現在の `device/` の絶対パスに置き換えて `/etc/systemd/system/pivr180-capture.service` に置き、有効にしてから（再）起動する。リポジトリを移動した場合や、実行するユーザーを変える場合は、スクリプトを再実行すればサービスが更新される。

サービスは次のように動く。

- 起動する前に、root で次のコマンドを実行し、左右のカメラの同期のマルチキャスト（`239.255.255.250`）をループバック（`lo`）へ流すルートを用意する。`replace` なので、起動し直すたびに実行しても同じ状態になる。
  - `ip link set lo multicast on`
  - `ip route replace 239.255.255.250/32 dev lo`

  libcamera の `rpi.sync` は、同じ Pi の中の左右のカメラの間でも、タイミングをマルチキャスト（`239.255.255.250:10000`）で送り合う。このマルチキャストのルートがないと、デフォルトルートのない状態（どのネットワークにもつながっていないときなど）で `ERROR RPiSync sync.cpp:96 Unable to set socket options` が出て同期が取れず、撮影ソフトが終了する。ルートは `lo` に張るので、どのネットワークにつながっているかに関係なく、同期のパケットは Pi の外に出ない。
- `.venv/bin/pivr180-capture` を既定のオプション（`--shutter button`）で起動する。撮影できる状態になると、AtomS3 Lite の LED が緑の点灯になる（[状態の表示](#状態の表示)）。
- `AmbientCapabilities=CAP_NET_BIND_SERVICE` により、root ではなく実行ユーザーのまま、スマホ Web UI を 80 番ポートで配信する（[スマホ Web UI](#スマホ-web-ui)）。
- 異常終了した場合（起動時に左右の同期が取れない、カメラがまだ使えない、撮影後にプレビューへ戻せない、SIGKILL で終了したなど）は、5 秒後に起動し直す。起動し直している間、LED は起動中の表示になり、撮影できる状態になると緑に戻る。
- `sudo systemctl stop pivr180-capture` で止めると、Ctrl+C と同じくカメラとシリアルを解放してから終了する。この場合は起動し直さない。

ログは次のコマンドで確認できる。

```sh
journalctl -u pivr180-capture -f
```

カメラとシリアルは同時に 1 つのプロセスしか使えないため、`uv run pivr180-capture` で手動で起動する場合は、先にサービスを止める。サービスを止めても同期のルートは残るが、再起動した後にサービスを一度も起動していない場合は、上の 2 つのコマンドを `sudo` で実行してから起動する。

```sh
sudo systemctl stop pivr180-capture
```

自動起動をやめる場合は、次のコマンドで無効にして止める。

```sh
sudo systemctl disable --now pivr180-capture
```

## ネットワーク

登録済みの Wi-Fi が見つかればそこへ接続し、見つからなければ Pi 自身がアクセスポイント（SSID `pivr180`）になる。どちらの場合も `pivr180.local` で Pi にアクセスできる。

切り替えには Raspberry Pi OS（Bookworm 以降）標準の NetworkManager を使う。NetworkManager は、利用できる接続のうち自動接続の優先度（`connection.autoconnect-priority`）が最も高いものへ自動で接続する。Wi-Fi のクライアントの接続はその SSID がスキャンで見つかったときだけ利用できるが、アクセスポイントの接続は常に利用できる。そこでアクセスポイントの接続を、登録済みの Wi-Fi（既定の 0）より低い優先度（-100）で用意している。

1. 次のことを済ませておく。
   - Wi-Fi の国（WLAN country）を設定する。Raspberry Pi Imager の OS カスタマイズで設定していればよい。未設定の場合は `sudo raspi-config` の Localisation Options → WLAN Country で設定する。
   - 自宅などの Wi-Fi を登録する。Raspberry Pi Imager の OS カスタマイズで設定していればよい。追加する場合は次のコマンドを使う。

     ```sh
     sudo nmcli device wifi connect "<SSID>" password "<パスフレーズ>"
     ```

2. `device/` で次のスクリプトを実行する。`<パスフレーズ>` は、アクセスポイントに接続するときのパスフレーズ（8〜63 文字）に置き換える。パスフレーズはリポジトリには置かない。

   ```sh
   PIVR180_AP_PASSPHRASE='<パスフレーズ>' ./scripts/setup_network.sh
   ```

   スクリプトは次のことを行う。

   - `raspi-config nonint do_hostname pivr180` でホスト名を `pivr180` にする。Raspberry Pi OS 標準の avahi-daemon が、`pivr180.local` の名前を mDNS で応答する。
   - NetworkManager に、アクセスポイントの接続 `pivr180-ap` を追加する。既にある場合は、削除せずに設定を書き換える。パスフレーズを変える場合はスクリプトを再実行し、再起動すると反映される（アクセスポイントに接続して実行していても、その場では切れない）。
     - SSID `pivr180`、WPA2（AES）、2.4GHz
     - `ipv4.method shared`。Pi のアドレスは `10.42.0.1` になり、接続したスマホには DHCP でアドレスが配られる。
     - 自動接続の優先度は -100
   - 実行中の SSH が切れないよう、その場ではアクセスポイントにしない。

3. `sudo reboot` で再起動する。

切り替えは次のように動く。

- 起動時や、接続していた Wi-Fi が切れたときに、登録済みの Wi-Fi が見つかればそこへ接続し、見つからなければアクセスポイントになる。
- アクセスポイントになっている間は Wi-Fi をスキャンしないため、登録済みの Wi-Fi が届く場所へ戻っても自動では接続し直さない。再起動するか、次のコマンドで接続する。

  ```sh
  sudo nmcli connection up "<登録済みの Wi-Fi の接続名>"
  ```

現在の接続は次のコマンドで確認できる。

```sh
nmcli connection show --active
```

アクセスポイントへの切り替えをやめる場合は、接続を削除する。

```sh
sudo nmcli connection delete pivr180-ap
```

## スマホ Web UI

撮影ソフトは、スマホから操作するための Web UI も同じプロセスで配信する。設計の経緯は [ADR 0009](../docs/adr/0009-web-ui-in-capture-process-on-port-80.md) を参照。現在はライブプレビュー、撮影設定（[撮影設定](#撮影設定)）、撮影一覧と削除（[撮影一覧と削除](#撮影一覧と削除)）、シャットダウン（[Web UI からのシャットダウン](#web-ui-からのシャットダウン)）まで。

- 撮影ソフトを起動すると、カメラを開く前に Web サーバー（FastAPI + uvicorn）を別スレッドで起動する。左右の同期を待っている間も画面は開ける。終了時は、カメラとシリアルを解放した後に止める。
- すべてのネットワークインターフェースの 80 番ポートで待ち受ける。スマホと Pi を同じネットワークにつなぎ、`http://pivr180.local` を開く。Pi が登録済みの Wi-Fi に接続している場合はスマホも同じ Wi-Fi に、アクセスポイントになっている場合はスマホを SSID `pivr180` につなぐ。ホスト名を `pivr180` にする設定は [ネットワーク](#ネットワーク) を参照。設定する前は、Pi のホスト名（`hostname` で確認できる）で `http://<ホスト名>.local` を開く。
- 80 番ポートは、root でないユーザーでは通常使えない。systemd のサービスでは権限を与えている（[自動起動](#自動起動)）が、`uv run pivr180-capture` で手動で起動する場合は使えないため、`--web-port 8080` などを指定して `http://<ホスト名>.local:8080` を開く。
- 待ち受けに失敗した場合（ポートを使えない、使用中など）は、エラーをログに出し、Web UI なしで撮影を続ける。ボタンでの撮影とシャットダウンはそのまま使える。
- 終了時、応答が終わらない接続（ライブプレビューや、ネットワークから外れたスマホなど）は 2 秒待って打ち切る。

### ライブプレビュー

画面を開くと、左右のカメラの映像を横に並べた 1280×480 の映像を表示する。

- `GET /api/preview.mjpg` で、左右の `lores` を横に並べた JPEG（品質 70）を MJPEG（`multipart/x-mixed-replace`）で配信する。
- 1 つの接続で送るのは最大 5fps。複数のスマホで開いた場合は、同じ JPEG を共有し、撮影ソフトのエンコードは 1 回で済ませる。
- 左右の同期を待っている間や、カメラを解放した後は 503 を返す。画面はメッセージを出し、3 秒ごとに再接続する。
- 撮影ソフトが終了するとき（カメラを止める前）に配信を終える。

### 撮影設定

画面の「撮影設定」で、露出補正、ホワイトバランス、コントラストを変更できる。スライダーを離したり選び直したりすると、すぐに左右のカメラへ反映する。

| 項目 | 値 | 初期値 | libcamera のコントロール |
| --- | --- | --- | --- |
| 露出補正 | -2.0〜2.0（0.1 刻み） | 0.0 | `ExposureValue` |
| ホワイトバランス | 自動、白熱灯、タングステン、蛍光灯、室内、晴天、曇天 | 自動 | `AwbMode`（`auto`=0 〜 `cloudy`=6） |
| コントラスト | 0.0〜2.0（0.1 刻み） | 1.0 | `Contrast` |

- `GET /api/settings` で現在の設定を、`PUT /api/settings` で変更する。本文は `{"exposure_value": 0.0, "white_balance": "auto", "contrast": 1.0}` の形の JSON で、3 つとも必要。範囲外や不明な値は 422 を返し、何も変えない。
- 左右のカメラ両方に同じ値を設定する。露出補正とホワイトバランスは左の AE/AWB に効き、その結果がプレビュー中のコピーで右に移る。コントラストは左右それぞれに効く。
- 撮影中に変更した場合は、その撮影が終わってから反映する。1 回の撮影の左右で設定が食い違うことはない。
- 左右の同期を待っている間や、カメラを解放した後は 503 を返し、設定は変えない。画面にはメッセージを出し、反映済みの値に戻す。
- 設定は撮影ソフトのメモリにだけ持つ。撮影ソフトを起動し直すと初期値に戻る。`meta.json` には記録しない。

### 撮影一覧と削除

画面を開くと、`--captures-dir` の撮影データが新しい順に並ぶ。

- 撮影日時（ディレクトリ名の UTC をスマホの時刻で表示）、ディレクトリ名、左右の縮小画像を表示する。縮小画像は、原寸（4056×3040）の JPEG を Pillow で長辺 480px に縮めて返す。撮影データのディレクトリには保存しない。
- `meta.json` の `sync.warning` が `true` のものに「同期警告」を付ける。`meta.json` か左右の画像が欠けているもの（保存中の電源断などで残ったもの）に「不完全」を付ける。
- 「削除」を押し、確認で OK するとディレクトリごと削除する。元に戻せない。
- 保存中の撮影は一覧に出さず、保存が終わるまで一覧の取得と削除を待たせる。

API は次のとおり。`<id>` は `YYYYMMDD-HHMMSS-NNN` 形式のディレクトリ名で、それ以外は 404 を返す。

| メソッド | パス | 内容 |
| --- | --- | --- |
| `GET` | `/api/captures` | 撮影データの一覧（新しい順）。`id`、`complete`（`meta.json` と左右の画像がそろっているか）、`sync_warning`（`meta.json` から読めなければ `null`） |
| `GET` | `/api/captures/<id>/thumbnails/<left\|right>` | 縮小した JPEG |
| `DELETE` | `/api/captures/<id>` | 撮影データを削除する（204） |

### 画面の開発

画面のソースは `web/` にある。素の HTML と TypeScript で書き、Vite でビルドする。ビルドした成果物は `src/pivr180_device/static/` に出力され、Python パッケージに同梱される。成果物はリポジトリにコミットするため、Pi に Node.js は不要。

```sh
cd web
pnpm install
pnpm test   # Vitest
pnpm build  # 型チェックの後、src/pivr180_device/static/ にビルドする
```

- `web/` を変更したら `pnpm build` を実行し、`src/pivr180_device/static/` の変更も一緒にコミットする。CI はビルドし直した結果がコミット済みの成果物と一致するか確認し、一致しない場合は失敗する。
- 画面の機能を足すときは、Python 側で `fastapi.APIRouter` を作り、`pivr180_device.web.create_app()` の `routers` に渡す。ルーターは静的ファイルより優先される。
- カメラや露出のコピーを使う場合は、`main()` で作る `pivr180_device.slot.CameraSlot` をルーターに渡す。Web サーバーはカメラを開く前に起動するため、`run()` が準備できた時点で `CameraPair` と `ExposureSync`（`LiveCameras`）を入れ、カメラを止める前に外す。`with slot.borrow() as cameras:` で借り、`cameras` が `None` なら未準備として 503 などを返す。外すときは貸し出し中の処理が終わるまで待つため、借りている間は止めたカメラに触ることはない。長く借り続けると終了が遅れるので、1 回の操作ごとに借りる。

### Web UI からのシャットダウン

- 画面の「シャットダウン」を押すと確認のダイアログが出る。OK を選んだときだけ、`POST /api/shutdown` で撮影ソフトに要求を送る。
- 撮影ソフトは要求を受け付けるとすぐ `202 Accepted` を返し、電源はその後に切る。AtomS3 Lite のボタンの 3 秒長押しと同じく、撮影の待ち受けを終え、カメラとシリアルを解放してからシャットダウンする。
  - 撮影中に要求された場合は、その撮影の保存が終わってからシャットダウンする。それまでに押されていたシャッターでは撮影しない。その撮影やプレビューへの復帰に失敗した場合も、カメラとシリアルを解放してからシャットダウンする（終了コード 1）。
  - `--shutter stdin` で入力を待っている間でも、Enter を待たずにシャットダウンする。
- 送信中と受け付けた後はボタンを押せなくなる。要求を送れなかった場合（接続できない、エラーが返ったなど）は画面にその旨を出し、もう一度押せるようにする。
- 権限がなくシャットダウン自体に失敗した場合は、長押しと同じくエラーをログに出して終了する（[シャットダウンの権限](#シャットダウンの権限)）。画面には出ない。

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

### 状態の表示

`--shutter button` では、ボタンと同じシリアルで撮影ソフトの状態を AtomS3 Lite へ送り、LED で表示する。色と点滅は [firmware/PROTOCOL.md](../firmware/PROTOCOL.md#led-の表示) のとおり。

| 撮影ソフトの状態 | 送るメッセージ | LED |
|---|---|---|
| 撮影できる状態になるまで（左右の同期を待っている間など） | なし | 白のゆっくり点滅（起動中） |
| 撮影できる状態になった（`ready` のログ）。撮影・保存が終わった | `idle` | 緑の点灯 |
| 撮影・保存している | `capturing` | 青の点灯 |
| 撮影や保存に失敗してプレビューへ戻った | `error` | 赤の速い点滅。次のシャッターで撮影を始めると青に戻る |
| プレビュー中の露出/WB のコピーが失敗した | `error` | 赤の速い点滅。次のシャッターで終了する |
| エラーで終了する（起動時に同期が取れない、カメラを開けない、撮影後にプレビューへ戻せないなど） | `error` を 1 回送ってからシリアルを閉じる | 赤の速い点滅の後、3 秒で橙（切断） |
| 3 秒の長押しでシャットダウンする | 長押しが成立した時点で送るのをやめる | 3 秒で橙（切断） |
| Web UI からシャットダウンする | カメラを解放してシリアルを閉じるまで送り続ける | 3 秒で橙（切断） |
| Ctrl+C で終了する | 送るのをやめる | 3 秒で橙（切断） |

- 状態が変わったら、すぐ（ボタンを読む間隔の 0.1 秒以内に）送る。変わらなくても、最後に送ってから 1 秒ごとに送り直す（ハートビート）。AtomS3 Lite は 3 秒受け取らないと切断の表示にする。
- つなぎ直したときは、すぐに現在の状態を送る。
- 書き込みが 0.5 秒で終わらない場合や失敗した場合は、抜けた場合と同じく開き直す。
- シリアルの読み書きと開き直しは、ボタンを読むスレッドだけが行う。撮影の処理は状態を書き換えるだけなので、撮影中も状態は送り続けられる。
  - ボタンを読むスレッドは撮影できる状態になってから始める。それより前にエラーで終了する場合は、終了時にシリアルを開いて `error` を 1 回だけ送り、すぐ閉じる（ボタンは読まない）。
- `--shutter stdin` ではシリアルを開かないため、状態も送らない。AtomS3 Lite は起動中（または切断）の表示のままになる。

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
