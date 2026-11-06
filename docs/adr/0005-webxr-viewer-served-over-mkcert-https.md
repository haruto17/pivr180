---
title: viewer は WebXR で実装し、editor 内蔵の mkcert HTTPS サーバーから同一オリジンで配信する
createdAt: 2026-11-07
---

# 0005. viewer は WebXR で実装し、editor 内蔵の mkcert HTTPS サーバーから同一オリジンで配信する

## ステータス

承認

## コンテキスト

editor で書き出した SBS 正距円筒 180° の写真を、Meta Quest 3 で立体表示したい（[plan.md](../plan.md)）。viewer にはギャラリー、VR180 立体表示（左右の目への出し分け）、コントローラでの前後送り・一覧に戻る操作が求められる。

Quest Browser の WebXR は secure context が必須であり、LAN 上の `http://` では利用できない。そのため、viewer と写真をどのように Quest に届けるかを決める必要がある。

## 決定

- viewer は **Svelte ＋ TS ＋ Vite ＋ Three.js** による WebXR（immersive-vr）アプリとする。
- editor 内蔵の HTTPS サーバーから、viewer の静的ファイルと写真一覧 API を**同一オリジン**で配信する。
- 証明書は mkcert で Mac の LAN IP と `.local` 名に対して発行し、**再生成しない**。
- Quest 側は初回に証明書警告を承認するか、ADB で mkcert のルート CA を導入する。
- 開発時は ADB ポート転送（localhost）も併用する。

## 検討した選択肢

### GitHub Pages ＋ Quest へ手動コピー

- 利点: viewer を HTTPS で簡単に公開でき、証明書の管理が不要。
- 欠点: 写真を Quest へ手動でコピーする必要があり、editor から直接見られない。

### ADB ポート転送のみ

- 利点: localhost は secure context として扱われるため、証明書なしで WebXR を使える。
- 欠点: 常に USB 接続と ADB が必要で、ワイヤレスで気軽に見られない。

### chrome://flags の unsafely-treat-insecure-origin-as-secure

- 利点: LAN の `http://` のまま WebXR を使える。
- 欠点: ブラウザのセキュリティ設定を緩める必要があり、フラグの存続や挙動が保証されない。

### editor 内蔵 HTTPS サーバー（mkcert）から同一オリジン配信（採用）

- 利点: LAN 越しにワイヤレスで viewer と写真を配信できる。同一オリジンのため CORS の考慮が不要。証明書を再生成しないため、Quest 側の承認・CA 導入は一度で済む。
- 欠点: 証明書の発行と Quest 側での初回承認または CA 導入の手間がある。Mac の LAN IP が変わると証明書と一致しなくなりうる。

## 結果 / 影響

- editor で書き出した写真を、Quest 3 から LAN 越しに直接閲覧できる。
- viewer は editor から配信されるため、editor の起動が閲覧の前提となる。
- 証明書と Mac の LAN IP の不一致がリスクとなる。`.local` 名にも発行することで緩和し、開発時は ADB ポート転送を併用する。
