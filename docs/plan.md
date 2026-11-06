# pivr180 実装プラン

## 目的・スコープ

### 目的

Raspberry Pi 5 に HQ Camera（IMX477, M12）×2 と Entaniya RP-L190HQ（190°）×2 を載せ、Meta Quest 3 で立体視できる VR180 写真を撮る、持ち歩き可能なカメラを作る。使用部品は [device_specs.md](./device_specs.md) を参照。

### MVP

- **写真のみ**を対象とする。
- 以下は後続マイルストーンで扱う（[後続マイルストーン候補](#後続マイルストーン候補) を参照）。
  - 動画
  - 音声（USB マイク）
  - チェッカーボードキャリブレーション
  - 色合わせ強化
  - ハードウェア同期

## システム構成

```
[device: Pi 5]  --rsync(SSH)-->  [editor: Mac / Tauri]  --HTTPS(LAN)-->  [viewer: Quest 3 Browser / WebXR]
 撮影・記録のみ                   取り込み・補正・変換・配信              ギャラリー・VR180 立体表示
```

| コンポーネント | 実行環境 | 役割 |
|---|---|---|
| device | Raspberry Pi 5 | 撮影・記録のみ |
| editor | Mac（Tauri） | 取り込み・補正・変換・viewer 配信 |
| viewer | Quest 3 Browser（WebXR） | ギャラリー・VR180 立体表示 |

## ディレクトリ構成

| ディレクトリ | 内容 |
|---|---|
| `device/` | Pi 側（Python, uv） |
| `editor/` | Mac 側エディタ（Tauri: Rust ＋ Svelte/TS/Vite, pnpm） |
| `viewer/` | Quest 3 用 WebXR ビューア（Svelte/TS/Vite ＋ Three.js, pnpm） |
| `schema/` | 共通 JSON Schema（meta.json 等） |
| `hardware/` | bpy スクリプト、STL/3MF、BOM、配線図 |

空ディレクトリは git 管理外のため、各モジュールの初期セットアップ時にファイルを置いて追跡させる。

## device

実行環境: Raspberry Pi 5, Raspberry Pi OS Lite 64bit

### 言語・環境

- Python ＋ uv。
- Picamera2 は apt（`python3-picamera2`）で導入するため、venv は `--system-site-packages` で作成する。

### カメラ制御

- 2 台を Picamera2 で制御する。
- **ソフトウェア同期**: libcamera のカメラ同期機能 ＋ センサータイムスタンプ照合。左右差を meta.json に記録する。
- 露出/WB: 左カメラで AE/AWB を行い、ExposureTime / AnalogueGain / ColourGains を右へコピーして固定する。

### 撮影・保存

- 解像度 4056×3040、**JPEG 品質 100** のみ。
- 保存先: NVMe `/data/captures/<YYYYMMDD-HHMMSS-NNN>/{left.jpg,right.jpg,meta.json}`
- meta.json（`schema/` の JSON Schema 準拠）に含める項目:
  - 左右のセンサー時刻・差分
  - 露出
  - ゲイン
  - 色補正値
  - カメラ識別子
  - ソフトバージョン

### 物理 UI

- GPIO シャッターボタン（長押し 3 秒で安全シャットダウン）。
- 状態 LED（待機 / 撮影中 / エラー）。
- gpiozero を使用。
- モード切替スイッチは設けない。

### スマホ Web UI

- FastAPI ＋ 素の HTML/TS（ビルド成果物を同梱）。
- 機能:
  - 左右並びの低解像度 MJPEG ライブプレビュー
  - 設定
  - シャットダウンボタン
  - 撮影一覧

### ネットワーク

- 既知の Wi-Fi に接続し、見つからなければ Pi がアクセスポイント化する（自動切替）。
- ホスト名は `pivr180.local`。

### 運用

- systemd で自動起動し、準備完了を LED で通知する。
- 取り込み後も Pi 側のデータは既定で削除しない。

## editor

実行環境: Mac（Tauri）

### 技術構成

- 変換処理は **Rust**（image ＋ rayon、LUT による remap）。後続のキャリブレーションは opencv-rust を使う。
- UI は Svelte ＋ TS ＋ Vite。

### MVP 機能

1. **取り込み**: システムの `rsync` を SSH 鍵認証で実行する（既定の接続先は `pivr180.local`）。
2. **一覧**: 撮影単位で左右のサムネイルを表示する。
3. **補正**: レンズ仕様値（等距離射影, EFL 1.45mm, 1.55µm/px）を初期値とし、左右それぞれのイメージサークル中心・半径・回転を手動で調整する。プレビューは画面側で縮小画像を WebGL で変換し、本書き出しは Rust で行う。
4. **書き出し**: SBS 正距円筒 180°（片目約 2880×2880、設定可）の JPEG。ファイル名末尾は `_180_LR`。

### 補正値の保存

- 補正値は撮影ごと／デバイス既定として JSON で保存する（形式は `schema/` で定義）。

### viewer 配信

- editor 内蔵の HTTPS サーバーで、viewer の静的ファイルと写真一覧 API を同一オリジンで配信する。
- 証明書は mkcert で Mac の LAN IP と `.local` 名に対して発行し、再生成しない。
- Quest 側は初回に警告を承認するか、ADB で mkcert のルート CA を導入する。
- 開発時は ADB ポート転送（localhost）も併用する。

## viewer

実行環境: Quest 3 Browser

### 技術構成

- Svelte ＋ TS ＋ Vite ＋ Three.js、WebXR（immersive-vr）。

### MVP 機能

- ギャラリー → 1 枚選択で VR180 立体表示（左右の目へ半球メッシュ／レイヤを出し分け）。
- コントローラで前後送り・一覧に戻る。
- 左右入替（デバッグ用）。

### 後回し

- ズーム
- 明るさ調整
- 動画

## hardware

### BOM

[device_specs.md](./device_specs.md) の部品に加えて以下を使用する。

- 15pin→22pin カメラケーブル ×2
- NVMe 用 HAT
- USB-C PD モバイルバッテリー（5V/5A 非対応時の USB 給電制限は検証項目。NVMe は PCIe のため影響なし）
- タクトスイッチ
- LED ＋ 抵抗
- 1/4" 三脚ナット
- M2.5 ネジ類

### 光学要件

- レンズ間隔 64mm。
- 光軸は平行。
- レンズ面より前に筐体を出さない（190° の視野に入らないように）。
- 1/4" 三脚穴を設ける。

### 筐体

- Blender で設計する。
  - 寸法が重要な内部構造（カメラ・Pi・NVMe・バッテリーの固定、レンズ間隔）は bpy スクリプトでパラメトリック生成し、STL/3MF を出力する。
  - 外観は手作業モデリングで仕上げる。
- Bambu Lab A1（FDM, 256mm 角）で印刷する。
- バッテリーは筐体に固定し、交換可能にする。

### 配線図

- ボタン・LED の GPIO 割当を記載する。

## テスト方針

| 対象 | 方針 |
|---|---|
| device | カメラを抽象化し、Fake を用いて Mac 上で pytest |
| editor | Rust 単体テスト（合成魚眼画像で変換精度を検証）、フロントは Vitest |
| viewer | Vitest |

実機での確認は、PR の確認項目に手順として記載する。

## 後続マイルストーン候補

参考情報であり、マイルストーンの定義は [milestone.md](./milestone.md) で行う。

- 動画（2028×1520 ビニング。H.264 ソフトエンコードか非圧縮 YUV かはベンチマークで決定）
- 音声
- チェッカーボードキャリブレーション ＋ 左右回転補正
- 色合わせ強化
- ハードウェア同期（XVS）
- VR180 メタデータ付与

## 関連 ADR

- [0001. Pi は記録のみを担い、変換・合成は Mac で行う](./adr/0001-record-on-pi-process-on-mac.md)
- [0002. MVP は写真のみとし、JPEG 品質 100 で記録する](./adr/0002-photo-only-mvp-jpeg-quality-100.md)
- [0003. 左右カメラはソフトウェア同期とし、露出/WB は左カメラの値を右へコピーして固定する](./adr/0003-software-sync-and-copy-exposure-wb.md)
- [0004. editor は Tauri で構築し、変換は Rust、UI は Svelte で実装する](./adr/0004-tauri-editor-with-rust-conversion.md)
- [0005. viewer は WebXR で実装し、editor 内蔵の mkcert HTTPS サーバーから同一オリジンで配信する](./adr/0005-webxr-viewer-served-over-mkcert-https.md)
- [0006. 電源は USB-C PD モバイルバッテリーとする](./adr/0006-usb-c-pd-power-bank.md)
- [0007. 筐体は Blender で設計し、Bambu Lab A1 で FDM 印刷する](./adr/0007-blender-enclosure-fdm-printing.md)
