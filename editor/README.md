# pivr180 editor

Mac 側エディタ（Tauri ＋ Svelte/TS/Vite）。

## 開発

```sh
pnpm install
pnpm tauri dev
```

## 保存先

既定の保存先は `~/Pictures/pivr180/` で、その下を次のように使い分ける。

- `captures/`: Pi から取り込んだ撮影データ
- `exports/`: 書き出した VR180 データ

保存先は画面の「保存先」欄に絶対パスを入力して「保存」で変更できる。変更時に `captures/` と `exports/` を作成し、設定はアプリ設定ディレクトリの `settings.json` に保存する。

## テスト・lint

```sh
pnpm test
pnpm lint
cd src-tauri && cargo test && cargo fmt --check && cargo clippy -- -D warnings
```
