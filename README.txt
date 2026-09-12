PavlokSuperChat v0.3.0
========================

YouTube Live の Super Chat を検出し、指定した金額と一致したときに
PavlokへZapを送信するWindows用コンソールアプリです。


============================================================
  まずこれだけやれば使えます
============================================================

1. PavlokSuperChat.exe と config.ini を同じフォルダに置く

2. config.ini をメモ帳で開く

3. 次の3か所を設定する

   [YouTube]
   api_key=あなたのYouTube APIキー

   [SuperChat]
   amounts=200,500,1000,3000,5000

   [Pavlok]
   initial_token=あなたのPavlok初期トークン

4. 最初は必ず

   enabled=false

   のまま起動して、スパチャ検出だけ確認する

5. 問題なければ

   enabled=true

   に変更するとPavlokへ実際にZapを送信する

6. PavlokSuperChat.exe をダブルクリックして起動する

7. 表示された

   YouTube Live URL / Video ID:

   に監視したい配信URLを貼り付けて Enter

以上です。


============================================================
  config.ini のかんたん説明
============================================================

■ YouTube APIキー

[YouTube]
api_key=AIzaSy...

Google Cloudで作成した「YouTube Data API v3」のAPIキーを貼ります。
Bearer は付けません。


■ Zapするスパチャ金額

[SuperChat]
amounts=200,500,1000,3000,5000

半角カンマで複数指定できます。
金額は「完全一致」です。

上の例なら:

  200円   -> 対象
  500円   -> 対象
  1000円  -> 対象
  800円   -> 対象外
  1001円  -> 対象外

対象は「日本円（JPY）のSuper Chat」のみです。
Super Stickerは対象外です。


■ Pavlok初期トークン

[Pavlok]
initial_token=Bearer eyJ...

Pavlok APIのGetting Startedで取得した初期トークンを貼ります。

Bearer付き:
  initial_token=Bearer eyJ...

Bearerなし:
  initial_token=eyJ...

どちらでも使用できます。

起動時にこの初期トークンを使ってPavlokへ接続し、
/user/ のレスポンスに含まれる user.token を実行用トークンとして使用します。


■ テスト / 実送信の切り替え

[Pavlok]
enabled=false

  false = テストモード
  true  = Pavlokへ実際にZapを送信

初回は false 推奨です。

falseでも以下は確認できます。

  ・Super Chat検出
  ・対象金額判定
  ・発火予約
  ・delay
  ・cooldown
  ・fixed / random の出力決定

Zapだけ送信しません。


■ スパチャからZapまでの待ち時間

[Pavlok]
delay_seconds=5

例:

  0   -> すぐ実行
  5   -> 5秒後
  10  -> 10秒後

すべての対象Super Chatに共通です。


■ クールダウン

[Pavlok]
cooldown_seconds=10

前回のZapから次のZapまで、最低何秒あけるかを指定します。

クールダウン中に対象スパチャが来ても消えません。
予約キューに入り、順番に後から処理されます。

例:

  #1 Zap
     ↓ 10秒待機
  #2 Zap
     ↓ 10秒待機
  #3 Zap

0 にするとクールダウンなしです。


■ 出力を固定する

[Pavlok]
output_mode=fixed
fixed_output=30

この場合、毎回 output=30 で送信します。


■ 出力をランダムにする

[Pavlok]
output_mode=random
random_min=20
random_max=40

毎回Zapを送る直前に、20～40の範囲からランダムに決定します。

出力値は1～100で指定してください。


============================================================
  起動したときの表示
============================================================

正常に監視が始まると、だいたい次のように表示されます。

  設定読み込み OK
  対象金額: ¥200, ¥500, ¥1,000, ...
  Pavlok: OFF (DRY-RUN)
  [STREAM] 監視開始

対象のSuper Chatが来ると:

  [SUPERCHAT] UserA ￥1,000 / JPY
  [MATCH] ￥1,000 発火対象
  [QUEUE] #1 ￥1,000 / UserA 予約

テストモードなら:

  [DRY-RUN] #1 zap output=27

実送信が成功すると:

  [PAVLOK] #1 OK (HTTP 200)

と表示されます。


============================================================
  Pavlokの認証について
============================================================

アプリ起動時:

  config.ini の initial_token
            ↓
  GET https://api.pavlok.com/api/v5/user/
            ↓
  user.token を取得
            ↓
  実行用トークンとしてメモリ上で使用

Zap送信:

  POST https://api.pavlok.com/api/v5/stimulus/send

刺激タイプは zap 固定です。

Pavlok APIでエラーになった場合、同じZapは自動再送しません。
タイムアウト時に実際には届いていた場合の二重送信を避けるためです。

401 / 403 の場合も、そのZap自体は再送せず、
実行用トークンだけ更新して次の予約から使用します。


============================================================
  アプリを終了するとどうなる？
============================================================

Ctrl+C、またはウィンドウを閉じると終了します。

まだ実行されていない予約は保存されません。
次回起動時に古いSuper Chatから突然Zapが発生しないための仕様です。


============================================================
  よくあるトラブル
============================================================

■ API key not valid と表示される

config.ini の api_key を確認してください。

  ・前後に余計な文字がないか
  ・YouTube Data API v3 用のAPIキーか
  ・Google CloudでYouTube Data API v3を有効化したか

空白文字はアプリ側でも除去しますが、
APIキー本体だけを貼るのが確実です。


■ Pavlok認証に失敗する

initial_token を確認してください。

Bearer付きでも無しでも構いません。

  initial_token=Bearer eyJ...

または

  initial_token=eyJ...

全角スペースなどは自動的に正規化します。


■ 配信URLを入れても監視できない

以下を確認してください。

  ・現在ライブ配信中か
  ・ライブチャットが有効か
  ・URL / Video ID が正しいか

対応例:

  https://www.youtube.com/watch?v=XXXXXXXXXXX
  https://www.youtube.com/live/XXXXXXXXXXX
  XXXXXXXXXXX


■ スパチャが来ても反応しない

確認する項目:

  ・通貨がJPYか
  ・Super Chatか（Super Stickerではないか）
  ・amountsにその金額が完全一致で登録されているか


============================================================
  セキュリティ上の注意
============================================================

config.ini には次の認証情報が平文で保存されます。

  ・YouTube APIキー
  ・Pavlok初期トークン

config.ini を他人へ送ったり、SNS、配信画面、GitHubなどへ公開しないでください。

Pavlokの出力値は装着者側で事前に設定し、無理のない範囲で使用してください。


============================================================
  配布時に必要なファイル
============================================================

基本的には次の3ファイルだけで使用できます。

  PavlokSuperChat.exe
  config.ini
  README.txt

Pythonのインストールは不要です。
