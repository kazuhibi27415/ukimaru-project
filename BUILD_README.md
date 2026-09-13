# PavlokSuperChat v2.0 - ビルド手順

これは開発・ビルド用パッケージです。
配布先の利用者には、releases/v<version>フォルダ内のEXEを渡せば動作します。

```text
PavlokSuperChat.exe
README.md（任意の説明書）
```

config.defaults.iniを初期設定としてEXEに同梱します。
このファイルには利用者のAPIキー・トークンを記載しないでください。
利用者設定は初回起動時に%LOCALAPPDATA%\PavlokSuperChat\config.iniへ作成します。
既存の利用者設定はEXEの更新時にも上書きしません。
ソース実行用config.iniやreleases/v<version>横のconfig.iniはEXEへ同梱しません。

1. Pythonを用意
---------------
Python 3.13.x 64-bit 推奨。

2. 初回セットアップ
-------------------
01_setup_windows.bat

3. Python版で動作確認
---------------------
03_run.bat

4. EXEをビルド
--------------
04_build_exe.bat

5. EXEをテスト
--------------
05_run_exe.bat

6. FIFOキューだけテスト
-----------------------
06_test_queue.bat

注意:
BATファイルはWindows cmd.exeでの文字化けを避けるため、表示文字列をASCII中心にしています。
設定説明は config.ini と README.md を参照してください。
