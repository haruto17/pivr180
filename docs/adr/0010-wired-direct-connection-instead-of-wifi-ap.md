---
title: 外出先では Pi の Wi-Fi アクセスポイントではなく、有線の直結でスマホとつなぐ
createdAt: 2026-11-24
---

# 0010. 外出先では Pi の Wi-Fi アクセスポイントではなく、有線の直結でスマホとつなぐ

## ステータス

承認

## コンテキスト

外出先でスマホからスマホ Web UI（[ADR 0009](./0009-web-ui-in-capture-process-on-port-80.md)）を開くために、Pi とスマホをつなぐ方法が必要になる。[plan.md](../plan.md) のネットワークでは、登録済みの Wi-Fi が見つからなければ Pi 自身が Wi-Fi のアクセスポイントになると決め、#27 で NetworkManager のアクセスポイントの接続 `pivr180-ap`（`ipv4.method shared`）を作るスクリプト `device/scripts/setup_network.sh` を用意した。この決定は ADR にはなく、plan.md にだけ書かれていた。

実機（Pi 5、Raspberry Pi OS、NetworkManager）で試したところ、アクセスポイントには次の問題があった（#116）。

- **カメラの同期が失敗する**: libcamera の `rpi.sync` は、左右のカメラのタイミングをマルチキャスト（`239.255.255.250:10000`）で送り合う。クライアント側は `IP_ADD_MEMBERSHIP` でインターフェースを `INADDR_ANY` にして参加するため、参加先はルーティングテーブルで決まる。アクセスポイントでは上流がなくデフォルトルートもないため、参加に失敗する。`ERROR RPiSync sync.cpp:96 Unable to set socket options` がフレームごとに出て、同期が取れないまま撮影ソフトが終了する。`ip route add 224.0.0.0/4 dev wlan0` を足すと直った。
- **Android から接続できない**: SSID は見えているが、接続は Pi まで届かない（`iw dev wlan0 station dump` が空で、ログにも何も出ない）。PMF の有無を変えても直らず、原因は分からなかった。

一方、Android に USB-C の LAN アダプタを挿し、LAN ケーブルで Pi 5 の `eth0` に直結して、Pi 側で `ipv4.method shared`（`10.42.1.1/24`）の接続を有効にし、手でマルチキャストのルートを足したところ、モバイルデータと Wi-Fi を切った Android から `http://10.42.1.1` でライブプレビューを表示できた。

自宅では、`eth0` は netplan から生成された接続 `netplan-eth0`（DHCP）で自宅の LAN につないでいる。外出先用の接続を足しても、自宅ではこれまでどおり DHCP でアドレスを受け取る必要がある。

## 決定

- 外出先では、Android と Pi 5 の `eth0` を、USB-C の LAN アダプタと LAN ケーブルで直結してつなぐ。Pi の Wi-Fi アクセスポイントはやめ、`setup_network.sh` で既存の `pivr180-ap` を削除する。ホスト名を `pivr180` にする設定は残す。
- `eth0` に直結用の接続 `pivr180-eth-direct` を作る。
  - `ipv4.method shared`、`ipv4.addresses 10.42.1.1/24`。Pi は `10.42.1.1` になり、スマホには DHCP でアドレスを配る。
  - `ipv4.routes 224.0.0.0/4`。デフォルトルートがなくても、`rpi.sync` がマルチキャストに参加できるようにする。
  - `connection.autoconnect yes`、`connection.autoconnect-priority -100`。`netplan-eth0`（既定の 0）より低くする。
- DHCP サーバーがいないときだけ直結用の接続を使うよう、NetworkManager の自動接続の仕組みで切り替える。
  - NetworkManager は、自動接続できる接続のうち優先度の高いものから試す。ケーブルをつなぐと、まず `netplan-eth0` で DHCP を試す。
  - DHCP サーバーがいなければ、`netplan-eth0` の有効化は DHCP のタイムアウトで失敗する（netplan が `dhcp4: true` だけのプロファイルに書く `ipv6.method` は `ignore` なので、IPv6 で成功することはない）。既定の再試行回数（4 回）を使い切ると、`netplan-eth0` の自動接続は止まり、次に優先度の高い `pivr180-eth-direct` が有効になる。
  - 切り替えを早めるため、`/etc/NetworkManager/conf.d/pivr180-eth0.conf` で `eth0` の `ipv4.dhcp-timeout` の既定値を 10 秒にする（既定は 45 秒）。ケーブルをつないでから直結用の接続になるまで、およそ 40 秒になる。
  - ケーブルを抜き差しすると（キャリアが戻ると）、NetworkManager は再試行の回数を戻す。自宅でケーブルをつなぎ直せば、再び `netplan-eth0` から試す。
- `netplan-eth0` は `nmcli connection modify` で書き換えない。netplan から生成された接続を NetworkManager で書き換えると、netplan の YAML に書き戻される。どのファイルに書き戻されるか（Raspberry Pi Imager の設定から cloud-init が作る YAML か、別のファイルか）や、cloud-init に上書きされないかが文書からは確認できなかった。そのため、DHCP のタイムアウトは NetworkManager の設定ファイルで `match-device=interface-name:eth0` の既定値として与える。既定値は、接続側が値を設定していない（`0`）ときだけ使われる。

## 検討した選択肢

### Pi の Wi-Fi アクセスポイント

- 利点: ケーブルやアダプタが要らない。iPhone など、LAN アダプタを挿せない端末でもつなげる。#27 で設定済み。
- 欠点: Android から接続できず、原因が分からなかった。デフォルトルートがないため、マルチキャストのルートを足さないとカメラの同期が取れない。

### スマホの Wi-Fi テザリング・USB テザリング

- 利点: Pi はスマホのネットワークに DHCP のクライアントとしてつなぐだけで済み、デフォルトルートもある。
- 欠点: テザリングを有効にするとモバイルデータを使う。オーナーの判断で採用しない。

### Bluetooth でサムネイルを送る

- 利点: ケーブルが要らない。
- 欠点: 転送が遅い。ライブプレビューができない。Pi とスマホの両方に新しいコードが多く要る。

### USB（MTP）で撮影データをコピーする

- 利点: Pi とスマホを USB ケーブルでつなぐだけで済む。
- 欠点: Pi を USB のデバイスとして動かす新しいコードが要り、動作が不安定になりやすい。ライブプレビューができない。

### 有線の直結（採用）

- 利点: 実機で、Android から `http://10.42.1.1` でライブプレビューを表示できた。モバイルデータを使わない。スマホ Web UI はそのまま使える。
- 欠点: USB-C の LAN アダプタと LAN ケーブルを持ち歩く必要がある。スマホ側でモバイルデータと Wi-Fi を切る必要がある。iPhone などでは確認していない。

## 結果 / 影響

- 外出先でも、Android からスマホ Web UI（ライブプレビュー・撮影設定・撮影一覧と削除・シャットダウン）を使える。
- 外出先では Pi に `10.42.1.1` で接続する。Android は `.local` の名前解決が安定しないため、`pivr180.local` ではなくアドレスで開く。
- BOM に USB-C の LAN アダプタと LAN ケーブルが加わる。
- ケーブルをつないでから直結用の接続になるまで、およそ 40 秒かかる。
- 自宅の LAN で DHCP サーバー（ルーター）が 40 秒以上応答しない場合（停電の後など、Pi がルーターより先に起動した場合）、Pi は直結用の接続になり、自宅の LAN で DHCP サーバーとしてアドレスを配ってしまう。ルーターが起動した後に、ケーブルを抜き差しするか再起動すれば戻る。
- ケーブルを抜いてから数秒以内に別の相手へつなぎ替えると、NetworkManager がキャリアの断を待っている間に接続が切れず、直結用の接続のまま自宅の LAN につながることがある。つなぎ替えるときは、抜いてから数秒待つ。
- 再試行回数のリセットや優先度による選択は、NetworkManager の動作に依存する。実機で、自宅の LAN、Android との直結、ケーブルの抜き差しを確認する（#116 の PR の実機での確認手順）。
