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

## 撮影一覧

画面の「撮影一覧」欄に `captures/` 内の撮影を新しい順に並べ、撮影ごとに左右のサムネイルを表示する。`left.jpg` と `right.jpg` が揃っていないフォルダは表示しない。撮影を追加・削除したら「再読み込み」で一覧を取り直す。

サムネイルは長辺 320px に縮小して、アプリのキャッシュディレクトリ（macOS では `~/Library/Caches/com.haruto17.pivr180.editor/`）の `thumbnails/<撮影 ID>/{left,right}.jpg` に保存し、元画像が更新されるまで再利用する。`captures/` 内には書き込まない。キャッシュは削除しても次回表示時に作り直される。

## テスト・lint

```sh
pnpm test
pnpm lint
cd src-tauri && cargo test && cargo fmt --check && cargo clippy -- -D warnings
```
