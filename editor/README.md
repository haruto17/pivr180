# pivr180 editor

Mac 側エディタ（Tauri ＋ Svelte/TS/Vite）。

## 開発

```sh
pnpm install
pnpm tauri dev
```

## テスト・lint

```sh
pnpm test
pnpm lint
cd src-tauri && cargo test && cargo fmt --check && cargo clippy -- -D warnings
```
