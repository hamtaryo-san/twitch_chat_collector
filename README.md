# Twitch Chat Collector

Twitchライブ配信のチャットメッセージ、モデレーションイベント（メッセージ削除、Ban/タイムアウト）をリアルタイムで収集し、データベースに保存するPythonアプリケーションです。

## 機能

- **リアルタイムチャット収集**: Twitch IRC WebSocketを使用したリアルタイムメッセージ収集
- **モデレーションイベント追跡**: メッセージ削除、ユーザーBan/タイムアウトイベントの記録
- **複数チャンネル同時監視**: 任意のチャンネルを同時監視（承認不要）
- **配信自動検出**: 定期的に配信開始・終了を検出
- **バックグラウンド実行**: デーモン化によるバックグラウンド実行
- **配信情報管理**: Twitch Helix APIを使用した配信情報の取得と保存
- **データベース保存**: SQLAlchemyによる柔軟なデータベース管理（SQLite、PostgreSQL、MySQL対応）
- **🆕 トークン自動更新**: Refresh Tokenによる4時間ごとの自動更新（手動介入不要）
- **🆕 長期運用対応**: 毎時トークン検証、401エラー自動リカバリ

## アーキテクチャ

### コアコンポーネント

1. **twitch_client.py** - Twitch Helix API クライアント
   - ストリーム情報の取得
   - ユーザー情報の取得
   - OAuth認証トークンの管理

2. **twitch_irc.py** - IRC WebSocketクライアント
   - IRC WebSocket接続の管理
   - チャットメッセージのリアルタイム受信（PRIVMSG）
   - メッセージ削除イベントの受信（CLEARMSG）
   - Ban/タイムアウトイベントの受信（CLEARCHAT）
   - IRCv3 Message Tagsのパース

3. **database.py** - データベース管理
   - SQLAlchemyを使用したCRUD操作
   - 配信情報、チャットメッセージ、イベントの保存

4. **models.py** - データモデル定義
   - Stream（配信情報）
   - ChatMessage（チャットメッセージ）
   - MessageDeletedEvent（メッセージ削除イベント）
   - UserBannedEvent（Ban/タイムアウトイベント）
   - UserUnbannedEvent（Unbanイベント - ※IRCでは取得不可）

5. **collector.py** - メインコレクター
   - 各コンポーネントの統合
   - イベントハンドラーの実装
   - 複数チャンネル対応

### 追加コンポーネント

6. **config_loader.py** - 設定ファイル読み込み
   - channels.yamlの読み込み
   - 設定のバリデーション

7. **scheduler.py** - 配信スケジューラー
   - 定期的な配信状態チェック
   - 配信開始・終了の検出
   - データベースへの配信情報保存

8. **daemon.py** - デーモン管理
   - スケジューラーとコレクターの統合実行
   - PIDファイル管理
   - シグナルハンドリング
   - 🆕 毎時トークン検証（公式必須要件）

9. **🆕 token_manager.py** - OAuth Token Manager
   - Refresh Tokenによるトークン自動更新
   - 起動時 + 毎時のトークン検証（Twitch公式推奨）
   - 401エラー時の即座なリフレッシュ
   - .envファイルへの自動保存

10. **🆕 oauth_authenticator.py** - 初回OAuth認証
    - ブラウザでの認証フロー
    - Access Token + Refresh Token の自動取得
    - .envファイルへの自動保存

## セットアップ

### 1. 依存関係のインストール

```bash
# 仮想環境の作成（推奨）
python -m venv twitch
source twitch/bin/activate  # Windows: venv\Scripts\activate

# パッケージのインストール
pip install -r requirements.txt
```

### 2. Twitchアプリケーションの作成

1. [Twitch Developers Console](https://dev.twitch.tv/console/apps)にアクセス
2. 「アプリケーションを登録」をクリック
3. アプリケーション情報を入力：
   - 名前: 任意のアプリケーション名
   - **OAuth リダイレクト URL**: `http://localhost:3000/callback` ⚠️ 重要
   - カテゴリ: Chat Bot または Application Integration
4. 作成後、**Client ID** と **Client Secret** をコピー

### 3. 環境変数の設定

`.env.example`を`.env`にコピーして編集：

```bash
cp .env.example .env
```

`.env`ファイルを編集（Client IDとClient Secretのみ設定）：

```env
TWITCH_CLIENT_ID=your_client_id_here
TWITCH_CLIENT_SECRET=your_client_secret_here

# 以下は初回認証後に自動設定されます
# TWITCH_ACCESS_TOKEN=（自動設定）
# TWITCH_REFRESH_TOKEN=（自動設定）

DATABASE_URL=sqlite:///twitch_chats.db
LOG_LEVEL=INFO
LOG_FILE=collector.log
```

### 4. 🆕 初回OAuth認証（簡単！）

**一度だけ実行**すれば、以降はトークンが自動更新されます：

```bash
python oauth_authenticator.py
```

**実行すると：**
1. ブラウザが自動的に開きます
2. Twitchログイン画面が表示されます
3. 「承認」をクリック
4. `.env`ファイルに**Access Token**と**Refresh Token**が自動保存されます

✅ これだけでセットアップ完了！以降は手動操作不要です。

### 5. データベースの初期化

```bash
python models.py
```

### 6. チャンネル設定ファイルの作成（複数チャンネル監視用）

`channels.yaml.example`を`channels.yaml`にコピーして編集：

```bash
cp channels.yaml.example channels.yaml
```

`channels.yaml`ファイルを編集：

```yaml
channels:
  - user_login: "shroud"
    display_name: "shroud"
    enabled: true
    notes: "FPS streamer"

  - user_login: "xqc"
    display_name: "xQc"
    enabled: true
    notes: "Variety streamer"

scheduler:
  interval_minutes: 1  # 配信チェック間隔（分）
  reconnect_interval: 5
  max_reconnect_attempts: 10
```

## 使用方法

### 基本的な使用例

#### 1チャンネルのみ監視（シンプル）

```bash
# ユーザー名で指定
python collector.py --user-login twitchユーザー名

# ユーザーIDで指定
python collector.py --user-id 12345678
```

#### 複数チャンネル監視（channels.yaml使用）

```bash
# channels.yamlから設定を読み込んで複数チャンネルを監視
python collector.py --config channels.yaml
```

#### 配信状態のチェック（スケジューラー単体）

```bash
# 1回だけチェック
python scheduler.py --once

# 継続的にチェック（デフォルト1分間隔）
python scheduler.py

# チェック間隔を指定（5分間隔）
python scheduler.py --interval 5
```

### バックグラウンド実行

#### デーモンとして起動

```bash
# バックグラウンドで起動
python daemon.py

# カスタム設定ファイルを使用
python daemon.py --config my_channels.yaml

# カスタムPIDファイルを指定
python daemon.py --pid-file /var/run/twitch_collector.pid
```

#### デーモンの停止

```bash
python daemon.py --stop
```

#### systemdサービスとして起動（推奨）

1. サービスファイルを編集：

```bash
# twitch-chat-collector.serviceを編集
# User, WorkingDirectory, Environmentのパスを実際の環境に合わせて変更
```

2. サービスファイルをインストール：

```bash
sudo cp twitch-chat-collector.service /etc/systemd/system/
sudo systemctl daemon-reload
```

3. サービスを有効化・起動：

```bash
# 自動起動を有効化
sudo systemctl enable twitch-chat-collector

# サービスを起動
sudo systemctl start twitch-chat-collector

# ステータス確認
sudo systemctl status twitch-chat-collector

# ログ確認
sudo journalctl -u twitch-chat-collector -f
```

4. サービスの停止：

```bash
sudo systemctl stop twitch-chat-collector
```

### 統計情報の表示

```bash
python collector.py --stats 配信ID
```

### プログラムからの使用

```python
import asyncio
from collector import TwitchChatCollector

async def main():
    collector = TwitchChatCollector()

    # ユーザー名でチャット収集を開始
    await collector.collect_from_user(user_login='twitchユーザー名')

asyncio.run(main())
```

## データベーススキーマ

### streams
- `stream_id`: 配信ID（主キー）
- `user_id`: 配信者のユーザーID
- `user_login`: 配信者のログイン名
- `user_name`: 配信者の表示名
- `title`: 配信タイトル
- `game_name`: ゲーム名
- `viewer_count`: 視聴者数
- `started_at`: 配信開始時刻
- `ended_at`: 配信終了時刻

### chat_messages
- `id`: メッセージID（主キー）
- `stream_id`: 配信ID
- `chatter_user_id`: 投稿者のユーザーID
- `chatter_user_name`: 投稿者の表示名
- `message_text`: メッセージ本文
- `badges`: バッジ情報（JSON）
- `bits`: Bits数
- `is_subscriber`: サブスクライバーか
- `is_moderator`: モデレーターか
- `sent_at`: 送信時刻

### message_deleted_events
- `id`: イベントID（主キー）
- `message_id`: 削除されたメッセージID
- `target_user_id`: 削除対象ユーザーID
- `message_text`: 削除されたメッセージ本文
- `deleted_at`: 削除時刻

### user_banned_events
- `id`: イベントID（主キー）
- `user_id`: Ban/タイムアウト対象ユーザーID
- `moderator_user_id`: 実行したモデレーターのユーザーID
- `reason`: Ban/タイムアウトの理由
- `is_permanent`: 永久Banか
- `ends_at`: タイムアウト終了時刻
- `banned_at`: Ban/タイムアウト時刻

### user_unbanned_events
※注：IRCではUnbanイベントが取得できないため、このテーブルは使用されません

- `id`: イベントID（主キー）
- `user_id`: Unban対象ユーザーID
- `moderator_user_id`: 実行したモデレーターのユーザーID
- `unbanned_at`: Unban時刻

## Twitch API仕様

### 使用API

1. **Twitch Helix API**
   - Get Streams: ライブ配信情報の取得
   - Get Users: ユーザー情報の取得
   - Get Channels: チャンネル情報の取得

2. **Twitch IRC WebSocket**
   - WebSocket URL: `wss://irc-ws.chat.twitch.tv:443`
   - `PRIVMSG`: チャットメッセージ受信
   - `CLEARMSG`: メッセージ削除イベント
   - `CLEARCHAT`: ユーザーBan/タイムアウトイベント
   - IRCv3 Message Tags: メタデータ（user-id、display-name、badges等）

### 参考ドキュメント

- [Twitch API Documentation](https://dev.twitch.tv/docs/api/)
- [Twitch IRC](https://dev.twitch.tv/docs/irc/)
- [Twitch IRC Guide](https://dev.twitch.tv/docs/irc/guide/)
- [Twitch Chat Commands](https://dev.twitch.tv/docs/irc/commands/)
- [IRCv3 Message Tags](https://dev.twitch.tv/docs/irc/tags/)
- 🆕 [Twitch Authentication](https://dev.twitch.tv/docs/authentication/)
- 🆕 [Refreshing Access Tokens](https://dev.twitch.tv/docs/authentication/refresh-tokens/)
- 🆕 [Validating Tokens](https://dev.twitch.tv/docs/authentication/validate-tokens/)

## 🆕 トークン自動更新の仕組み

このシステムは **Twitch公式ドキュメント完全準拠** のトークン管理を実装しています：

### 自動更新フロー

```
[初回認証] oauth_authenticator.py 実行
    ↓
Access Token + Refresh Token 取得・保存
    ↓
[デーモン起動] python daemon.py
    ↓
├─ 起動時: トークン検証（公式必須）
├─ 1時間ごと: トークン検証（公式必須）
├─ 401エラー検出 → 即座にリフレッシュ（最優先）
└─ 期限10分前 → 事前リフレッシュ（補助）
```

### トークンの有効期限

- **Access Token**: 約4時間
- **Refresh Token**:
  - Confidential Client（推奨）: **無期限**
  - Public Client: 30日

### 自動更新の利点

✅ **手動操作不要**: 一度認証すれば、何ヶ月でも自動継続
✅ **401エラー自動リカバリ**: トークン期限切れを自動検出・更新
✅ **再起動しても継続**: サーバー再起動後も自動で動作継続
✅ **公式推奨準拠**: Twitchの公式ドキュメント通りの実装

## トラブルシューティング

### 🆕 トークンリフレッシュが失敗する場合

以下の原因が考えられます：

1. **Twitchアカウントのパスワード変更**
2. **Twitchでアプリ接続を解除**
3. **Refresh Tokenの期限切れ**（Public Clientの場合30日）

**解決方法**: 再認証を実行
```bash
python oauth_authenticator.py
```

### 🆕 401 Unauthorized エラー

**症状**: ログに `401 Unauthorized` が表示される

**原因**: トークンが期限切れまたは無効

**自動対応**:
- システムが自動的にRefresh Tokenでトークンを更新します
- ログに「トークンリフレッシュ成功」と表示されればOK

**手動対応が必要な場合**:
- Refresh Token自体が無効な場合は再認証が必要
```bash
python oauth_authenticator.py
```

### WebSocket接続エラー

- 初回認証が完了しているか確認: `python oauth_authenticator.py`
- `.env`ファイルに`TWITCH_ACCESS_TOKEN`と`TWITCH_REFRESH_TOKEN`が設定されているか確認
- 必要なスコープ（`chat:read`）が付与されているか確認

### IRC認証エラー

- `Login authentication failed` エラーが出る場合、自動的にトークンリフレッシュを試行します
- それでも失敗する場合は再認証が必要: `python oauth_authenticator.py`

### データベースエラー

- `DATABASE_URL`が正しく設定されているか確認
- データベースファイルへの書き込み権限があるか確認

### 🆕 リダイレクトURIエラー

**症状**: OAuth認証時に「Redirect URI mismatch」エラー

**原因**: Twitch Developer Consoleで設定したリダイレクトURIが異なる

**解決方法**:
1. [Twitch Developers Console](https://dev.twitch.tv/console/apps)でアプリを開く
2. リダイレクトURIに `http://localhost:3000/callback` を追加
3. 保存して再度 `python oauth_authenticator.py` を実行

## ライセンス

MIT License

## 開発者向け情報

### YouTube版との主な違い

| 特徴 | YouTube Chat Collector | Twitch Chat Collector |
|------|------------------------|----------------------|
| **API** | YouTube Data API v3 | Twitch Helix API + IRC |
| **リアルタイム通信** | ポーリング方式 | IRC WebSocket（プッシュ型） |
| **認証** | APIキーのみ | OAuth（Client Credentials + User Access Token） |
| **チャット取得** | `liveChatMessages.list` | IRC `PRIVMSG` |
| **削除イベント** | レスポンス内の`messageDeletedEvent` | IRC `CLEARMSG` |
| **Banイベント** | レスポンス内の`userBannedEvent` | IRC `CLEARCHAT` |
| **接続維持** | ポーリング間隔で制御 | Ping/Pongメッセージ |
| **他チャンネル監視** | API制限あり | 任意のチャンネルを承認なしで監視可能 |

### テスト

各モジュールは単体でテスト可能です：

```bash
# Twitch APIクライアントのテスト
python twitch_client.py

# IRCクライアントのテスト
python twitch_irc.py ACCESS_TOKEN CHANNEL1 [CHANNEL2] ...

# データベースのテスト
python database.py

# モデルのテスト
python models.py
```

## 今後の拡張予定

- [x] 複数チャンネルの同時監視（✅ 実装済み）
- [x] トークン自動更新機能（✅ 実装済み）
- [ ] WebUIの追加
- [ ] データ分析機能（統計、ワードクラウド等）
- [ ] 自動モデレーション機能
- [ ] エクスポート機能（CSV、JSON）
