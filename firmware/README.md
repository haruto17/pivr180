# firmware

M5Stack AtomS3 Lite で動くファームウェア。PlatformIO ＋ Arduino（C++）で作る。詳細は [docs/plan.md](../docs/plan.md) の firmware 節と [ADR 0008](../docs/adr/0008-atoms3-lite-usb-shutter-and-status.md) を参照。

## 準備

PlatformIO Core（`pio` コマンド）をインストールする。

```sh
brew install platformio
```

以降のコマンドは `firmware/` で実行する。初回はプラットフォームやツールチェーンがダウンロードされる。

## 環境

| 環境 | 内容 |
|---|---|
| `atoms3` | AtomS3 Lite 向けのビルド。`pio run` の既定 |
| `native` | Mac 上で動かす単体テスト（Unity） |

ハードウェアに依存しないロジックは `lib/` に置き、`native` 環境の単体テストで検証する。テストは `test/` に置く。

## ビルド

```sh
pio run -e atoms3
```

## テスト

```sh
pio test -e native
```

## 書き込み

1. AtomS3 Lite を USB で Mac につなぐ。
2. 書き込む。

   ```sh
   pio run -e atoms3 -t upload
   ```

   ポートが自動で見つからない場合は、`pio device list` でポートを確認し、`--upload-port` で指定する。

   ```sh
   pio run -e atoms3 -t upload --upload-port /dev/cu.usbmodem<番号>
   ```

   書き込みに失敗する場合は、本体側面のリセットボタンを緑色の LED が点くまで（約 2 秒）長押しして書き込みモードにしてから、もう一度書き込む。書き込み後はリセットボタンを押して再起動する。

USB シリアル（CDC）の出力は次のコマンドで確認できる。

```sh
pio device monitor
```
