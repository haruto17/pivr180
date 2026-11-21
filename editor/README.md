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

画面の「撮影一覧」欄に `captures/` 内の撮影を新しい順に並べ、撮影ごとに左右のサムネイルを表示する。`left.jpg` と `right.jpg` が揃っていないフォルダは表示しない。「取り込み」が成功すると一覧を自動で取り直す。それ以外で撮影を追加・削除したら「再読み込み」で一覧を取り直す。

サムネイルは長辺 320px に縮小して、アプリのキャッシュディレクトリ（macOS では `~/Library/Caches/com.haruto17.pivr180.editor/`）の `thumbnails/<撮影 ID>/{left,right}.jpg` に保存し、元画像が更新されるまで再利用する。`captures/` 内には書き込まない。キャッシュは削除しても次回表示時に作り直される。

## 取り込み

画面の「取り込み」欄の「取り込む」で、Pi の `/data/captures/` にある撮影データを rsync（SSH 経由）で保存先の `captures/` に取り込む。

- 既定の接続先は `pivr180.local`。Pi のユーザー名が Mac と違う場合は `user@pivr180.local` のように入力するか、`~/.ssh/config` に `User` を設定する。接続先は `settings.json` に保存される。
- 取り込み済みのファイルは再取得しない（`rsync -a` で同じファイルは転送されない）。画面には今回取り込んだ撮影データの件数を表示する。
- 既定では Pi 側のデータは取り込み後も削除しない。「取り込み後に Pi から削除する」をオンにすると、今回の取り込みで転送した撮影のうち、次をすべて満たすものだけを Pi の `/data/captures/` から削除する（設定は「取り込む」を押したときに `settings.json` に保存される）。
  - Mac 側に `left.jpg`・`right.jpg`・`meta.json` が揃い、`meta.json` が最後まで書かれている（JSON として読め、末尾が改行で終わる）。撮影中で途中までしか取り込めなかったものは残す。
  - 取り込みの直後にもう一度 rsync を dry-run（`-n`）で実行して、差分が出ない（取り込み中に Pi 側で書き換わったものは残す）。
- 以前の取り込みですでに Mac にある撮影は、オプションをオンにしても削除しない。rsync が失敗したとき、確認の dry-run が失敗したときは何も削除しない。削除は 100 件ずつ ssh で行い、途中で失敗したときは、それまでに削除した件数とエラーを画面に表示する。
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
