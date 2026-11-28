# android

Pi と USB でつなぎ、Android Open Accessory（AOA）でカメラを操作する Android アプリ。Kotlin・Jetpack Compose・Gradle（Kotlin DSL）で作る。方針は [ADR 0011](../docs/adr/0011-control-camera-from-android-app-over-aoa.md)、Pi とのメッセージの形は [schema/aoa-protocol.md](../schema/aoa-protocol.md) を参照。

Play ストアには公開せず、サイドロードで配布する。対応するのは Android 12（API 31）以降。

## 準備

- JDK 17 以降（Android Studio に同梱の JDK でよい）
- Android SDK（Android Studio の SDK Manager で入れる）

Android Studio を使わずにコマンドラインでビルドするときは、次の環境変数を設定する。

```sh
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
export ANDROID_HOME="$HOME/Library/Android/sdk"
```

以降のコマンドは `android/` で実行する。初回は Gradle と依存がダウンロードされる。

## ビルド

```sh
./gradlew assembleDebug
```

APK は `app/build/outputs/apk/debug/app-debug.apk` にできる。

## テスト

```sh
./gradlew testDebugUnitTest
```

JUnit の単体テストは `app/src/test/` に置く。`schema/examples/aoa/` の例をリポジトリのルートから読み込み、Kotlin のメッセージの型と食い違っていないかを確かめる。

## lint

```sh
./gradlew ktlintCheck
```

`./gradlew ktlintFormat` で直せるものは直せる。

## サイドロードでインストールする

1. スマホで「設定」→「デバイス情報」→「ビルド番号」を 7 回タップし、開発者向けオプションを有効にする。
2. 「設定」→「システム」→「開発者向けオプション」で「USB デバッグ」を有効にする。
3. スマホを Mac に USB でつなぎ、スマホに出る「USB デバッグを許可しますか？」を許可する。
4. `adb devices` でスマホが `device` と表示されることを確かめる（`adb` は `$ANDROID_HOME/platform-tools/` にある）。
5. インストールする。

   ```sh
   ./gradlew installDebug
   ```

   ビルド済みの APK を入れるときは `adb install -r app/build/outputs/apk/debug/app-debug.apk` でもよい。

6. スマホを Mac から外す。

## Pi とつなぐ

1. Pi で撮影ソフトが動いている状態で、スマホを Pi の USB-A に USB ケーブルでつなぐ。
2. スマホに pivr180 を開くかを尋ねるダイアログが出るので、このアクセサリには常に pivr180 を使うようにチェックを入れて「OK」を押す。次からは、ケーブルを挿すとアプリが起動する。
3. ハンドシェイクが済むと撮影の画面に切り替わり、プレビュー・シャッター・状態・直前の撮影の左右のサムネイルが表示される。ケーブルを抜くと「Pi とつながっていません」に戻り、挿し直すと再びつながる。アプリが裏に回っている間は、Pi にプレビューを止めてもらう。
4. 撮影の画面の「シャットダウン」で、確認の後に Pi をシャットダウンできる。

アプリは `app/src/main/res/xml/accessory_filter.xml` の manufacturer（`pivr180`）と model（`pivr180`）のアクセサリにだけ反応する。Pi 側がアクセサリモードに切り替えるときに送る値と同じにする。
