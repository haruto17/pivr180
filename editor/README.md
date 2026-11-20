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

## 取り込み

画面の「取り込み」欄の「取り込む」で、Pi の `/data/captures/` にある撮影データを rsync（SSH 経由）で保存先の `captures/` に取り込む。

- 既定の接続先は `pivr180.local`。Pi のユーザー名が Mac と違う場合は `user@pivr180.local` のように入力するか、`~/.ssh/config` に `User` を設定する。接続先は `settings.json` に保存される。
- 取り込み済みのファイルは再取得しない（`rsync -a` で同じファイルは転送されない）。画面には今回取り込んだ撮影データの件数を表示する。
- Pi 側のデータは取り込み後も削除しない。
- パスワード入力は求めない（`BatchMode=yes`）ので、事前に SSH 鍵認証を設定しておく。初回はホスト鍵の登録も兼ねて次を実行する。

```sh
ssh-copy-id <user>@pivr180.local
ssh <user>@pivr180.local true  # パスワードなしで通ることを確認
```

## テスト・lint

```sh
pnpm test
pnpm lint
cd src-tauri && cargo test && cargo fmt --check && cargo clippy -- -D warnings
```
