# pivr180 実装プラン

## 目的・スコープ

### 目的

Meta Quest 3 で立体視できる VR180 写真を撮る、持ち歩き可能なカメラを作る。Raspberry Pi 5 に HQ Camera（IMX477, M12 マウント）と魚眼レンズ Entaniya RP-L190HQ（190°）を 2 組載せ、左右の目の画像を同時に撮る。使用部品は [device_specs.md](./device_specs.md) を参照。

### MVP

- MVP では**写真のみ**を扱う。
- 次の機能は後続マイルストーンで扱う（[後続マイルストーン候補](#後続マイルストーン候補) を参照）。
  - 動画
  - 音声（USB マイク）
  - チェッカーボードを使ったレンズキャリブレーション
  - 左右の色合わせの強化
  - ハードウェア同期

## システム構成

```
[device: Pi 5]  --rsync(SSH)-->  [editor: Mac / Tauri]  --HTTPS(LAN)-->  [viewer: Quest 3 Browser / WebXR]
 撮影・記録のみ                   取り込み・補正・変換・配信              ギャラリー・VR180 立体表示
       ^
       | USB シリアル
       v
[firmware: AtomS3 Lite]
 シャッターボタン・状態 LED
```

| コンポーネント | 実行環境 | 役割 |
|---|---|---|
| device | Raspberry Pi 5 | 左右の画像を撮影して保存する。変換処理は行わない |
| firmware | AtomS3 Lite（USB で Pi 5 に接続） | シャッターボタンの押下・解放を device に送り、device から受け取った状態を RGB LED で表示する |
| editor | Mac（Tauri） | Pi から撮影データを取り込み、レンズの補正と VR180 形式への変換を行う。viewer の配信も担う |
| viewer | Quest 3 Browser（WebXR） | 変換済みの写真を一覧表示し、VR180 として立体表示する |

## ディレクトリ構成

| ディレクトリ | 内容 |
|---|---|
| `device/` | Pi 側のソフトウェア（Python, uv） |
| `firmware/` | AtomS3 Lite のファームウェア（PlatformIO ＋ Arduino, C++） |
| `editor/` | Mac 側のエディタ（Tauri: Rust ＋ Svelte/TS/Vite, pnpm） |
| `viewer/` | Quest 3 用の WebXR ビューア（Svelte/TS/Vite ＋ Three.js, pnpm） |
| `schema/` | device と editor が共有する JSON Schema（meta.json、補正値など） |
| `hardware/` | 筐体の bpy スクリプト、STL/3MF、BOM、配線図 |

git は空のディレクトリを記録しないため、各ディレクトリの初期セットアップ時にファイルを 1 つ以上置く。

## device

実行環境: Raspberry Pi 5, Raspberry Pi OS Lite 64bit

### 言語・環境

- Python を使い、依存関係は uv で管理する。
- Picamera2 は apt（`python3-picamera2`）で入れる OS のパッケージなので、venv は `--system-site-packages` で作成し、OS 側のパッケージを参照できるようにする。

### カメラ制御

- 2 台のカメラを Picamera2 で制御する。
- **左右の同期**はソフトウェアで行う。libcamera のカメラ同期機能で左右のフレームのタイミングを揃え、シャッター時はセンサーのタイムスタンプが最も近い左右のフレームを組にする。
  - 左右の時刻差が 1ms を超えた場合は撮り直す（最大 3 回）。
  - 3 回とも 1ms を超えた場合は、そのまま保存し、meta.json に警告として記録する。
- **露出とホワイトバランス**は左カメラの値に右カメラを合わせる。左右で明るさや色が違うと、立体視したときに見づらくなるため。
  - プレビュー中は、左カメラの自動露出・自動ホワイトバランスの結果（ExposureTime / AnalogueGain / ColourGains）を右カメラへ随時コピーする。
  - シャッターを押した時点の値で左右とも固定して撮影する。

### 撮影・保存

- 解像度は 4056×3040、形式は **JPEG（品質 100）** のみ。
- 撮影 1 回ごとに NVMe 上へフォルダを作って保存する: `/data/captures/<YYYYMMDD-HHMMSS-NNN>/{left.jpg,right.jpg,meta.json}`
- meta.json には次の項目を記録する（形式は `schema/` の JSON Schema で定義）。
  - 左右のセンサー時刻とその差
  - 同期の警告（時刻差が許容値を超えた場合）
  - 露出時間
  - ゲイン
  - 色補正値
  - カメラの識別子
  - ソフトウェアのバージョン

### 物理 UI

- USB でつないだ AtomS3 Lite のボタンをシャッターボタンにする。押すと撮影し、3 秒長押しすると安全にシャットダウンする。
- AtomS3 Lite の RGB LED で、待機中・撮影中・エラーを知らせる。
- AtomS3 Lite とは USB シリアルで通信する（[firmware](#firmware) を参照）。デバイスは `/dev/serial/by-id/` などの名前で固定して開く。
- 3 秒長押しの判定は device 側で行う。AtomS3 Lite からはボタンの押下と解放だけを受け取る。
- SPI でつないだディスプレイ Adafruit 4313 に、直前の撮影の左右の縮小画像、状態（待機中・撮影中・エラー）、エラーの内容、撮影枚数、保存先の空き容量を表示する。外出先でスマホを使わずに撮影結果を確かめるための補助の表示で、シャッターボタンと起動中・切断の表示は AtomS3 Lite が担う。ディスプレイがない、または初期化に失敗した場合も撮影は続ける。
- MVP は写真のみなので、写真／動画の切り替えスイッチは付けない。

### スマホ Web UI

- FastAPI で配信し、画面は素の HTML/TS で作る。ビルドした成果物を device に同梱する。
- 機能:
  - ライブプレビュー: 左右を並べた低解像度の映像を MJPEG で配信する
  - 撮影設定: 露出補正、ホワイトバランス、コントラストを変更する
  - 撮影一覧: 撮影データを確認し、不要なものを手動で削除する
  - シャットダウン

### ネットワーク

- 登録済みの Wi-Fi が見つかればそこへ接続し、見つからなければ Pi 自身が Wi-Fi のアクセスポイントになる。自宅では Mac から取り込み、外出先ではスマホをアクセスポイントにつないで撮影する、という使い分けを想定している。
- ホスト名は `pivr180.local`。

### 運用

- 撮影ソフトは systemd で自動起動し、撮影できる状態になったら AtomS3 Lite の LED で知らせる。
- editor へ取り込んだ後も、Pi 側のデータは既定では消さない。削除はスマホ Web UI から手動で行うか、editor の「取り込み後に削除」オプションを使う。

## firmware

実行環境: M5Stack AtomS3 Lite（仕様は [device_specs.md](./device_specs.md) を参照）

### 言語・環境

- PlatformIO ＋ Arduino（C++）で作る。

### Pi との通信

- USB シリアル（CDC）で、1 行 1 メッセージのテキストをやりとりする。メッセージの具体的な書式は `firmware/` に文書化する。
- AtomS3 Lite → Pi: ボタンの押下と解放だけを送る。長押しの判定は Pi 側で行う。
- Pi → AtomS3 Lite: 状態（待機中・撮影中・エラー）を一定の間隔で送る。これをハートビートとする。

### 表示

- 受け取った状態を、RGB LED の色と点滅に変換して表示する。
- Pi から最初のメッセージを受け取るまでは、ファームウェア単体で起動中の表示を行う。
- メッセージを受け取った後に一定時間メッセージが来なければ、切断の表示にする。シャットダウン後も USB 給電が続く場合に、古い表示を残さないため。

## editor

実行環境: Mac（Tauri）

### 技術構成

- 変換処理は **Rust** で実装する。image と rayon を使い、事前に計算した変換テーブル（LUT）で画素を並べ替える。後続のキャリブレーションには opencv-rust を使う。
- UI は Svelte ＋ TS ＋ Vite で作る。

### MVP 機能

1. **取り込み**: Mac の `rsync` コマンドを呼び出し、SSH 鍵認証で Pi から撮影データを取得する（既定の接続先は `pivr180.local`）。オプションで、取り込み後に Pi 側のデータを削除できる（既定はオフ）。
2. **一覧**: 撮影ごとに、左右の画像のサムネイルを並べて表示する。
3. **補正**: 魚眼画像を正しく変換するため、左右それぞれのイメージサークルの中心・半径・回転を手動で調整する。
   - 初期値はレンズの仕様値（等距離射影、焦点距離 1.45mm、画素ピッチ 1.55µm）から計算する。
   - 調整中のプレビューは、縮小画像を画面側の WebGL で変換して表示する。最終的な書き出しは Rust で行う。
4. **書き出し**: 左右を並べた（SBS）正距円筒 180° の JPEG を出力する。片目の解像度は既定で約 2880×2880 で、設定で変更できる。ファイル名の末尾に `_180_LR` を付ける。

### 保存場所

- 既定の保存先は `~/Pictures/pivr180/` で、設定で変更できる。
  - `captures/`: Pi から取り込んだ元データ
  - `exports/`: 書き出した VR180 の JPEG
- 補正値は JSON で保存する（形式は `schema/` で定義）。デバイスの既定値をすべての撮影に使い、撮影ごとに個別の値で上書きできる。

### viewer 配信

- Quest 3 のブラウザは、安全な接続（HTTPS または localhost）でなければ WebXR を使えない。そのため editor に HTTPS サーバーを内蔵し、viewer の画面と写真一覧 API を同じアドレスから配信する。
- 写真一覧 API が配信するのは `exports/` の写真だけ。
- 証明書は mkcert で Mac の LAN IP と `.local` 名に対して発行する。再生成すると Quest で警告が再び出るため、一度作った証明書を使い続ける。
- Quest 側では、初回に証明書の警告を承認するか、ADB で mkcert のルート証明書を入れて信頼させる。
- 開発中は、ADB のポート転送で `localhost` として開く方法も併用する。

## viewer

実行環境: Quest 3 Browser

### 技術構成

- Svelte ＋ TS ＋ Vite ＋ Three.js で作り、WebXR（immersive-vr）で表示する。

### MVP 機能

- ギャラリーから 1 枚選ぶと、VR180 として立体表示する。
  - 左目用と右目用に Three.js の半球メッシュを 2 つ作り、Three.js のレイヤ機能でそれぞれの目にだけ表示する。
  - WebXR Layers API を使った画質改善は後回しにする。
- コントローラで前後の写真に送ったり、一覧に戻ったりできる。
- デバッグ用に、左右の画像を入れ替えて表示できる。

### 後回し

- ズーム
- 明るさ調整
- 動画

## hardware

### BOM

[device_specs.md](./device_specs.md) の部品に加えて、次の部品を使う。

- 15pin→22pin カメラケーブル ×2（HQ Camera は 15pin、Pi 5 のカメラ端子は 22pin のため）
- NVMe 拡張ボード: [スイッチサイエンス製 Raspberry Pi 5 用 NVMe SSD 拡張ボード（SSCI-097864）](https://www.switch-science.com/products/9786)
  - Pi 5 の下側に取り付けるため、筐体内の部品配置はこれを前提にする。
  - M.2 M-key の 2230〜2280 に対応する。
- USB-C PD モバイルバッテリー（機種は選定中。5V/5A 出力に対応したものを優先する）
  - Pi 5 は 5V/5A を出せると確認できない電源につながると、USB 端子の出力を 600mA に制限する。MVP で USB につなぐのは AtomS3 Lite だけなので、影響は小さい見込み。NVMe は PCIe で接続するので、この制限を受けない。実機で動作を確認する。
- M5Stack AtomS3 Lite（シャッターボタン兼状態 LED）
- AtomS3 Lite と Pi 5 をつなぐ短い USB ケーブル（USB Type-C ⇔ USB Type-A）
- Adafruit 4313（1.3 インチ 240×240 の SPI ディスプレイ、ST7789。撮影結果の確認用）
- Adafruit 4313 と Pi 5 の GPIO ヘッダーをつなぐジャンパーワイヤー（SCLK・MOSI・CS・DC・RST・3V3・GND の 7 本）
- 1/4" 三脚ナット
- M2.5 ネジ類

### 光学要件

- 左右のレンズ間隔は 64mm（人の目の間隔に近い値）。
- 左右の光軸を平行にする。
- 190° のレンズの視野に写り込まないよう、筐体をレンズ面より前に出さない。
- 1/4" の三脚穴を設ける。

### 筐体

- Blender で設計する。
  - 寸法が重要な内部構造（カメラ・Pi・NVMe 拡張ボード・バッテリーの固定、レンズ間隔）は bpy スクリプトで寸法を変数にして生成し、STL/3MF を出力する。スクリプトをリポジトリで管理するため、寸法の変更を差分で追える。
  - 外観は Blender 上で手作業でモデリングして仕上げる。
- Bambu Lab A1（FDM, 造形サイズ 256mm 角）で印刷する。
- バッテリーは筐体に固定し、交換できるようにする。
- AtomS3 Lite は、ボタンを押せて LED が見える位置に、背面の M2 ネジ穴などで固定する。Pi 5 とつなぐ USB ケーブルの通り道を設ける。

### 配線図

- AtomS3 Lite の取り付け位置と、Pi 5 との USB 接続（使う USB 端子、ケーブルの長さと取り回し）を記載する。
- Adafruit 4313 の取り付け位置と、Pi 5 の GPIO ヘッダーとの配線を記載する。SPI0（SCLK: GPIO11、MOSI: GPIO10、CE0: GPIO8）、DC・RST 用の GPIO、3V3、GND を使う。

## テスト方針

| 対象 | 方針 |
|---|---|
| device | カメラ部分と AtomS3 Lite との通信を抽象化し、Fake に差し替えて Mac 上の pytest で検証する |
| firmware | ハードウェアに依存しないロジック（メッセージの解釈、状態と表示の対応、ハートビートのタイムアウト）を分離し、PlatformIO の native 環境の単体テストで Mac 上で検証する |
| editor | Rust の単体テストで、合成した魚眼画像を使って変換の精度を検証する。フロントエンドは Vitest |
| viewer | Vitest |

実機での確認は、PR の確認項目に手順として記載する。

## 後続マイルストーン候補

ここに挙げるのは候補であり、マイルストーンは [milestone.md](./milestone.md) で定義する。

- 動画: 2028×1520 の 2×2 ビニングで撮影する。Pi 5 には H.264 のハードウェアエンコーダーがないため、CPU で H.264 にエンコードするか非圧縮の YUV で記録するかを、ベンチマークで決める。[milestone.md の M10](./milestone.md#m10-device-動画) で扱い、論点と選択肢は [0012](./adr/0012-video-capture-method.md) にまとめている。
- 音声
- チェッカーボードを使ったレンズキャリブレーションと、左右カメラの向きのずれの補正
- 左右の色合わせの強化
- ハードウェア同期（HQ Camera の XVS 端子を使う）
- VR180 メタデータの付与

## 関連 ADR

- [0001. Pi は記録のみを担い、変換・合成は Mac で行う](./adr/0001-record-on-pi-process-on-mac.md)
- [0002. MVP は写真のみとし、JPEG 品質 100 で記録する](./adr/0002-photo-only-mvp-jpeg-quality-100.md)
- [0003. 左右カメラはソフトウェア同期とし、露出/WB は左カメラの値を右へコピーして固定する](./adr/0003-software-sync-and-copy-exposure-wb.md)
- [0004. editor は Tauri で構築し、変換は Rust、UI は Svelte で実装する](./adr/0004-tauri-editor-with-rust-conversion.md)
- [0005. viewer は WebXR で実装し、editor 内蔵の mkcert HTTPS サーバーから同一オリジンで配信する](./adr/0005-webxr-viewer-served-over-mkcert-https.md)
- [0006. 電源は USB-C PD モバイルバッテリーとする](./adr/0006-usb-c-pd-power-bank.md)
- [0007. 筐体は Blender で設計し、Bambu Lab A1 で FDM 印刷する](./adr/0007-blender-enclosure-fdm-printing.md)
- [0008. シャッターボタンと状態表示は USB 接続の AtomS3 Lite で行う](./adr/0008-atoms3-lite-usb-shutter-and-status.md)
- [0009. スマホ Web UI は撮影ソフトと同じプロセスで 80 番ポートから配信し、画面のビルド成果物をコミットする](./adr/0009-web-ui-in-capture-process-on-port-80.md)
- [0010. 撮影結果は SPI ディスプレイ Adafruit 4313 で本体に表示して確認する](./adr/0010-spi-display-for-last-capture-and-status.md)
