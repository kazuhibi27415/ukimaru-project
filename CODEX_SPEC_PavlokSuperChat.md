# PavlokSuperChat — Codex 引き継ぎ仕様書

- 対象バージョン: **v0.3.0**
- 対象OS: **Windows 10 / 11 64-bit**
- 配布形態: **PyInstallerで生成した単体EXE + 外部 `config.ini` + `README.txt`**
- UI: **コンソールアプリ（GUI化は現時点では不要）**

## 追加仕様: 4金額グループ別出力（2026-09-12）

ユーザーの明示依頼による、本文の「金額別出力にしない」制約への例外。
v0.3.0の従来設定との互換性は維持する。

- `[SuperChat1]`～`[SuperChat4]`をすべて指定すると4グループ方式になる。
- 各グループに`amounts`（正の整数円CSV、完全一致）と`output_mode`を指定する。
- fixed時は`fixed_output`、random時は`random_min`・`random_max`が必須。出力は1～100。
- 各グループの`enabled=false`で無効化する（省略時true）。無効グループの金額・出力は読み込みも検証もしない。
- 有効グループ間の金額重複、空金額、4セクション不足、逆転した範囲は起動時エラー。全グループ無効も起動時エラー。
- グループ指定時は旧`[SuperChat] amounts`に代えて4グループの金額の和集合を対象とする。
- グループ方式では旧`[Pavlok]`出力設定の読み込み・検証を行わない。
- 設定例は全グループにfixed/random両方の欄を用意する。選択はoutput_modeで行う。
- グループ指定がなければ旧設定のまま動作する。既存config.iniの自動移行はしない。
- 設定解釈はapp_config、最終金額判定はmain、予約にグループを保持するのはWorkerの責務。
- delay/cooldownは共通。全予約は1本のFIFOキューで処理し、ランダム抽選は送信直前。
- JPY・Super Chat限定、zap固定、再送禁止、終了時キュー破棄など他の制約は維持。
- 設定例はconfig.ini.example末尾を参照。実機でのグループ別出力確認は未実施。

- 目的: **YouTube LiveのSuper Chatを常時監視し、指定金額に完全一致した場合、設定された待機・クールダウン・出力条件に従ってPavlokへZapを送信する。**

---

## 1. Codexへの重要指示

このプロジェクトはすでにWindows環境で一連の実動作確認が取れている。
今後の修正では、明示的な仕様変更依頼がない限り、以下を維持すること。

1. **YouTube監視は `liveChatMessages.streamList` のgRPC方式を維持する。**
2. **対象はSuper Chatのみ。Super Stickerは対象外。**
3. **通貨はJPY固定。**
4. **対象金額は `config.ini` の複数指定値との完全一致。**
5. **Pavlok刺激種別は `zap` 固定。**
6. **対象Super ChatはすべてFIFOキューへ予約し、原則として捨てない。**
7. **クールダウン中の予約は破棄せず、後で順番に実行する。**
8. **Pavlok送信失敗時、そのZapは自動再送しない。**
9. **401 / 403時も失敗したZap自体は再送せず、runtime tokenだけ更新し、次の予約から使う。**
10. **アプリ終了時の未処理キューは永続化しない。** 再起動後に過去のSuper ChatでZapしないため。
11. **APIキー・トークン・金額・出力設定はEXEへ埋め込まず、外部 `config.ini` に置く。**
12. **GUI追加は現時点では不要。コンソール版を維持する。**
13. `.bat` は **ASCII英語のみ + CRLF** を維持する。日本語をBATへ入れるとWindows `cmd.exe` の文字コード問題で壊れる可能性がある。
14. 設定値は、コピー時の全角空白・半角空白・タブ・改行の混入を可能な範囲で正規化する。
15. 既存の安全上限としてPavlok出力値は **1〜100** の範囲外を受け付けない。

---

## 2. 現在の配布物

最終利用者へ渡す基本ファイルは以下の3つ。

```text
PavlokSuperChat/
├─ PavlokSuperChat.exe
├─ config.ini
└─ README.txt
```

開発用ソース一式には以下がある。

```text
pavlok_superchat.py       # メインエントリポイント
app_config.py             # config.ini 読み込み・検証・正規化
pavlok_api.py             # Pavlok認証・Zap API
trigger_worker.py         # FIFO予約キュー、delay、cooldown、出力決定
youtube_stream.py         # YouTube動画ID解析、Live Chat ID取得、gRPC監視
stream_list_pb2.py        # gRPC生成コード
stream_list_pb2_grpc.py   # gRPC生成コード
test_pavlok_auth.py       # Pavlok認証単体テスト
test_queue.py             # キュー動作テスト
PavlokSuperChat.spec      # PyInstaller設定
requirements.txt          # 実行依存
requirements-dev.txt      # ビルド依存
01_setup_windows.bat
02_test_pavlok_auth.bat
03_run.bat
04_build_exe.bat
05_run_exe.bat
06_test_queue.bat
config.ini.example
README.txt
BUILD_README.txt
VERSION.txt
```

---

## 3. 全体処理フロー

```text
PavlokSuperChat.exe 起動
        │
        ▼
config.ini 読み込み・検証
        │
        ├─ YouTube APIキー
        ├─ 対象Super Chat金額
        ├─ Pavlok初期トークン
        ├─ delay
        ├─ cooldown
        └─ fixed / random 出力設定
        │
        ▼
Pavlok enabled=true ?
        │
        ├─ NO → DRY-RUN
        │
        └─ YES
             │
             ▼
GET https://api.pavlok.com/api/v5/user/
Authorization: Bearer <initial_token>
             │
             ▼
レスポンス user.token を runtime_token としてメモリ保持
        │
        ▼
ユーザーが YouTube Live URL / Video ID を入力
        │
        ▼
YouTube videos.list
        │
        ▼
activeLiveChatId 取得
        │
        ▼
gRPC liveChatMessages.streamList 監視開始
        │
        ▼
Super Chat受信
        │
        ├─ Super Chat以外 → 無視
        ├─ JPY以外 → 無視
        ├─ 対象金額と不一致 → 無視
        │
        └─ 完全一致
             │
             ▼
FIFOキューへ予約
             │
             ▼
delay_seconds 待機
             │
             ▼
前回Zap試行から cooldown_seconds 経過確認
             │
             ├─ 未経過 → キューを捨てず待機
             │
             ▼
出力値決定
   fixed  → fixed_output
   random → random_min〜random_maxから送信直前に抽選
             │
             ▼
POST https://api.pavlok.com/api/v5/stimulus/send
stimulusType = zap
stimulusValue = 1〜100
             │
             ├─ 2xx → 成功ログ
             ├─ 401/403 → そのZapは失敗扱い・再送なし
             │             runtime tokenのみ更新
             └─ その他エラー / timeout → 再送なし、次の予約へ
```

---

## 4. YouTube側仕様

### 4.1 API

YouTube Data API v3を使用する。

起動時のLive Chat ID取得:

```text
GET https://www.googleapis.com/youtube/v3/videos
part=liveStreamingDetails
id=<video_id>
key=<youtube_api_key>
```

取得する値:

```text
items[0].liveStreamingDetails.activeLiveChatId
```

### 4.2 常時監視

YouTube Live Chatの監視はHTTPポーリングではなく、**gRPC `liveChatMessages.streamList`** を使用する。

APIキーはgRPC metadataの以下へ渡す。

```text
x-goog-api-key: <youtube_api_key>
```

`next_page_token` を保持し、RPCが正常EOFした場合は同じgRPC channel上で次の `StreamList` RPCを開始する。
正常EOFはエラーとして扱わない。

### 4.3 初回履歴

`ignore_initial_history=true` の場合、起動直後に取得した最初のメッセージ群は既読扱いとし、Zap判定を行わない。

目的:

- 起動前のSuper Chatで突然Zapすることを防止
- 再起動時の過去イベント再処理を防止

### 4.4 重複防止

YouTube message IDをメモリ上に保持し、同一IDを再処理しない。
現在は最大5000件程度の保持を前提とする。

### 4.5 対象イベント

対象:

```text
Super Chat
```

対象外:

```text
通常チャット
Super Sticker
Membership等のその他イベント
```

通貨:

```text
JPY固定
```

金額:

```text
amountMicros / 1,000,000
```

整数円であり、`config.ini` の `amounts` に完全一致した場合のみキューへ入れる。

---

## 5. Pavlok側仕様

### 5.1 初期トークン

利用者はPavlok API Getting Startedで取得した初期トークンを `config.ini` に記載する。

以下どちらも許容する。

```ini
initial_token=Bearer eyJ...
```

```ini
initial_token=eyJ...
```

プログラム側で `Bearer` を除去し、余分な空白等も正規化する。

### 5.2 runtime token取得

起動時、`enabled=true` の場合:

```http
GET https://api.pavlok.com/api/v5/user/
Authorization: Bearer <initial_token>
Accept: application/json
```

実機確認済みレスポンス形式:

```json
{
  "user": {
    "token": "<runtime_token>"
  },
  "volts": 1000
}
```

使用する値:

```text
response["user"]["token"]
```

この値をメモリ上のruntime tokenとして保持する。
`config.ini` へ自動書き戻しはしない。

### 5.3 Zap送信

```http
POST https://api.pavlok.com/api/v5/stimulus/send
Authorization: Bearer <runtime_token>
Content-Type: application/json
Accept: application/json
```

payload:

```json
{
  "stimulus": {
    "stimulusType": "zap",
    "stimulusValue": 30
  }
}
```

`stimulusType` は **zap固定**。

`stimulusValue` は **1〜100**。

### 5.4 エラー時

#### 通常HTTPエラー / 通信エラー / timeout

- エラー内容をコンソールに表示
- そのZapは失敗扱い
- **自動再送しない**
- YouTube監視と後続キュー処理は継続

理由:
通信timeoutでもPavlok側には届いている可能性があり、再送すると二重Zapになる可能性があるため。

#### 401 / 403

- 失敗したZapは再送しない
- `initial_token` を使って `/api/v5/user/` を再度呼ぶ
- 新しい `user.token` をruntime tokenとして更新
- 次の予約から新しいruntime tokenを使用

---

## 6. 発火予約キュー仕様

### 6.1 基本

対象Super Chatは **FIFOキュー**へ追加する。

例:

```text
#1 ¥500
#2 ¥1000
#3 ¥3000
```

実行順序も原則:

```text
#1 → #2 → #3
```

### 6.2 delay

`delay_seconds` はSuper Chatを検出してキューへ登録した時刻から数える。

例:

```ini
delay_seconds=5
```

なら最低5秒経過後に実行可能。

YouTube監視スレッドを `sleep()` で止めてはならない。
キュー専用Workerで待機する。

### 6.3 cooldown

`cooldown_seconds` は前回のPavlok送信試行から、次のZap送信試行までの最低間隔。

クールダウン中に予約が来ても破棄しない。

```text
#1 Zap
 ↓ cooldown
#2 Zap
 ↓ cooldown
#3 Zap
```

Pavlokへの送信がtimeout等になった場合も、「実際には届いた可能性」があるため送信試行時刻を基準にcooldownを適用する。

### 6.4 アプリ終了

未処理キューはファイル・DBへ保存しない。
アプリ終了とともに破棄する。

---

## 7. 出力値仕様

設定モードは2種類。

### fixed

```ini
output_mode=fixed
fixed_output=30
```

毎回同じ値を送る。

### random

```ini
output_mode=random
random_min=20
random_max=40
```

**Pavlokへ送信する直前**に `random_min` 〜 `random_max` の整数から1つ選ぶ。
両端を含む。

設定検証:

```text
1 <= fixed_output <= 100
1 <= random_min <= 100
1 <= random_max <= 100
random_min <= random_max
```

Super Chat金額から自動的に出力値を変更する仕様にはしない。

---

## 8. config.ini 仕様

現行例:

```ini
[YouTube]
api_key=PASTE_YOUTUBE_API_KEY_HERE

[SuperChat]
amounts=200,500,1000,3000,5000

[Pavlok]
initial_token=PASTE_PAVLOK_INITIAL_TOKEN_HERE
enabled=false
delay_seconds=5
cooldown_seconds=10
output_mode=random
fixed_output=30
random_min=20
random_max=40

[System]
ignore_initial_history=true
```

### 各キー

| セクション | キー | 型 | 意味 |
|---|---|---:|---|
| YouTube | `api_key` | string | YouTube Data API v3 APIキー |
| SuperChat | `amounts` | int CSV | 対象金額。完全一致 |
| Pavlok | `initial_token` | string | Pavlok初期トークン |
| Pavlok | `enabled` | bool | true=実送信 / false=DRY-RUN |
| Pavlok | `delay_seconds` | float | Super Chat検出から発火可能までの最低秒数 |
| Pavlok | `cooldown_seconds` | float | Zap試行間の最低秒数 |
| Pavlok | `output_mode` | enum | `fixed` / `random` |
| Pavlok | `fixed_output` | int | fixed時の1〜100 |
| Pavlok | `random_min` | int | random時の最小1〜100 |
| Pavlok | `random_max` | int | random時の最大1〜100 |
| System | `ignore_initial_history` | bool | 起動時履歴を無視するか |

### 正規化

YouTube APIキー:

- Unicode NFKC
- 半角/全角空白、タブ、改行を除去
- ASCII以外が残る場合はエラー

Pavlok token:

- Unicode NFKC
- 先頭の `Bearer` を大文字小文字無視で除去
- 空白・タブ・改行除去
- ASCII以外が残る場合はエラー

これは実際に、コピーした認証情報へ全角スペースが混入してHTTPヘッダーの `latin-1` encode errorになった問題への対策である。

---

## 9. DRY-RUN仕様

```ini
enabled=false
```

の場合:

- YouTube監視を行う
- Super Chat検出を行う
- JPY / 金額判定を行う
- キューへ予約する
- delayを適用する
- cooldownを適用する
- fixed/random出力値を決定する
- **Pavlok APIへの送信だけ行わない**

ログにはDRY-RUNであることを明示する。

初回設定・テスト時はDRY-RUN推奨。

---

## 10. ログ仕様

現在はPython `logging` によるコンソール出力。
基本フォーマット:

```text
[HH:MM:SS] message
```

代表例:

```text
[STREAM] 監視開始
[SUPERCHAT] UserA ￥1,000 / JPY
[MATCH] ￥1,000 発火対象
[QUEUE] #1 ￥1,000 / UserA 予約
[COOLDOWN] #2 あと 8.0s 待機
[OUTPUT] #1 random 20-40 => 27
[PAVLOK] #1 OK (HTTP 200)
```

現時点ではログファイル永続化は必須ではない。
GUIも不要。

---

## 11. EXE / ビルド仕様

PyInstallerを使用。

現在の開発ビルド依存:

```text
pyinstaller==6.22.2
```

実行依存:

```text
grpcio>=1.70,<2
protobuf>=5.29,<7
requests>=2.32,<3
```

`PavlokSuperChat.spec` では以下をhidden importへ含める。

```python
collect_submodules("grpc")
collect_submodules("google.protobuf")
```

EXE:

```text
console=True
name="PavlokSuperChat"
```

`04_build_exe.bat` の成果物:

```text
dist/
├─ PavlokSuperChat.exe
├─ config.ini
└─ README.txt
```

配布先PCにPythonは不要。

### BAT文字コード注意

BATは **ASCII英語のみ** とする。
日本語UTF-8のBATで `cmd.exe` 実行時に文字化けし、文字化けした一部がコマンドとして解釈された不具合を経験済み。

---

## 12. 現在確認済みの実動作

以下はWindows実機で確認済み。

- Python未導入PCから開発環境セットアップ
- YouTube Data API v3 APIキーによる認証
- `videos.list` からLive Chat ID取得
- gRPC `streamList` によるライブチャット監視
- 起動時履歴の既読化
- Super Chat取得
- Pavlok `/api/v5/user/` への初期トークン認証
- レスポンス `user.token` の取得
- Pavlok `/api/v5/stimulus/send` へのZap送信
- **HTTP 200 OK確認済み**
- PyInstallerによるWindows EXEビルド
- EXE単体起動テスト
- 外部 `config.ini` 読み込み
- APIキーへの空白混入対策
- Pavlokトークンへの全角空白混入対策

連続した実Super Chatを複数投げての実地キューテストはコスト上実施していない。
そのためキューはテストコードによる確認を前提とする。

---

## 13. エラー処理方針

### config.ini

設定値不正は起動時に明確なエラーを出して終了。
例:

- APIキー未設定
- Pavlok enabled=trueなのにtoken未設定
- output値が1〜100外
- `random_min > random_max`
- amountsが整数CSVでない

### YouTube

- APIキー不正 → 明示的にエラー終了
- Live Chat IDなし → 配信中でない / チャット無効の可能性を示す
- gRPC `RESOURCE_EXHAUSTED` → 待機後再試行
- その他一時的gRPCエラー → 数秒後再試行
- 正常EOF → エラー扱いせず `next_page_token` で次RPC

### Pavlok

- 起動時runtime token取得失敗 → enabled=trueなら起動失敗
- Zap失敗 → ログを出し再送しない
- 401/403 → token refreshのみ実行、失敗Zapは再送しない

---

## 14. セキュリティ / 運用要件

- `config.ini` にはAPIキーとPavlokトークンが入るため、GitHub等へ公開しない。
- APIキー / tokenをコードへハードコードしない。
- 認証情報をログへ全文出力しない。
- Pavlok runtime tokenはメモリのみで保持し、原則ファイル保存しない。
- `enabled=false` を安全な初期値とする。
- 出力値1〜100の入力検証を維持する。
- timeout時の自動再送は禁止。
- Super Chat金額をPavlok出力値へ直接マッピングしない。

---

## 15. Codexで修正するときの推奨責務分離

### `pavlok_superchat.py`

- アプリ起動
- 設定ロード
- 各コンポーネント生成
- Super Chatイベントの最終フィルタ
- graceful shutdown

### `app_config.py`

- `config.ini` のみ担当
- 正規化
- validation
- `Settings` dataclass

### `youtube_stream.py`

- URL / Video ID解析
- `activeLiveChatId` 取得
- gRPC streamList
- message ID重複防止
- Super ChatイベントのDTO化

Pavlok処理や金額設定をここへ入れない。

### `trigger_worker.py`

- FIFO queue
- delay
- cooldown
- fixed/random selection
- PavlokClient呼び出し

YouTube API処理をここへ入れない。

### `pavlok_api.py`

- initial token → runtime token
- `/user/`
- `/stimulus/send`
- 401/403時のtoken refresh
- HTTPエラー処理

YouTube処理をここへ入れない。

---

## 16. 今後追加する場合の候補

現時点で必須ではない。明示的な依頼があった場合のみ検討する。

- ログファイルへの保存
- 自動アップデート
- config編集補助
- GUI
- Windows通知領域常駐
- YouTube URLの自動保存
- 設定ファイル暗号化 / Windows Credential Manager
- バージョンチェック
- キュー状態表示の強化

**未処理キューの永続化は、再起動後の意図しないZapにつながるため、追加する場合は仕様を再確認すること。**

---

## 17. 受け入れテスト

修正後、最低限以下を確認すること。

### 設定

- [ ] `config.ini` がEXEと同じフォルダから読める
- [ ] YouTube APIキー前後の空白を除去できる
- [ ] `Bearer　JWT` のような全角スペース混入tokenも正規化できる
- [ ] 不正output値を起動時に拒否する

### YouTube

- [ ] URLからVideo IDを抽出できる
- [ ] `activeLiveChatId` を取得できる
- [ ] gRPC監視開始できる
- [ ] 初回履歴を無視できる
- [ ] Super ChatのみDTO化される
- [ ] 同一message IDを二重処理しない

### 判定

- [ ] JPY以外を無視する
- [ ] 完全一致しない金額を無視する
- [ ] 一致金額だけキューへ入る

### キュー

- [ ] FIFO順を維持する
- [ ] delayを適用する
- [ ] cooldown中の予約を捨てない
- [ ] random値は送信直前に決定する
- [ ] 終了時に未処理キューを永続化しない

### Pavlok

- [ ] initial tokenから `/user/` を呼べる
- [ ] `user.token` をruntime tokenとして使う
- [ ] `zap` 固定で送信する
- [ ] HTTP 200を成功として扱う
- [ ] timeout / 5xxで同一Zapを再送しない
- [ ] 401/403でtokenだけ更新し、失敗Zapを再送しない

### EXE

- [ ] PyInstallerビルド成功
- [ ] Python未導入PCでも起動可能
- [ ] `PavlokSuperChat.exe + config.ini + README.txt` だけで利用できる

---

## 18. 実装変更時の基本方針

変更は小さく、既存の責務分離を維持する。

特に以下を勝手に変更しないこと。

```text
Super Chatのみ
JPY固定
金額完全一致
zap固定
全予約
FIFO
クールダウン中も後で実行
送信失敗時の再送なし
終了時キュー破棄
外部config.ini
コンソールUI
```

仕様変更が必要になった場合は、コード修正より先に、この仕様書との差分を明示すること。
