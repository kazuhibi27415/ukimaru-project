PavlokSuperChat v0.3.0 - ビルド手順
======================================

これは開発・ビルド用パッケージです。
配布先の利用者には、distフォルダ内の次の3ファイルだけ渡せばOKです。

  PavlokSuperChat.exe
  config.ini
  README.txt


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
設定説明は config.ini と README.txt を参照してください。
