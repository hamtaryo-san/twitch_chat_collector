"""
チャットコレクター - Twitchライブチャットの収集メインロジック

公式ドキュメント準拠:
- 起動時にトークン検証（必須要件）
- TokenManager統合でトークン自動更新
- IRC接続失敗時の自動リトライ
"""
import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from config import Config
from twitch_client import TwitchAPIClient
from twitch_irc import TwitchIRCClient
from database import DatabaseManager
from config_loader import ChannelConfig
from token_manager import TokenManager

logger = logging.getLogger(__name__)


class TwitchChatCollector:
    """Twitchライブチャット収集システム（複数チャンネル対応）"""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        database_url: Optional[str] = None
    ):
        """
        コレクターの初期化

        Args:
            client_id: Twitch Client ID
            client_secret: Twitch Client Secret
            access_token: ユーザーアクセストークン（IRC用、chat:readスコープ）
            database_url: データベースURL
        """
        # Helix APIクライアント（App Access Token用）
        self.twitch_client = TwitchAPIClient(
            client_id=client_id,
            client_secret=client_secret
        )

        # TokenManager初期化（IRC用トークン管理）
        self.token_manager = TokenManager(
            client_id=client_id or Config.TWITCH_CLIENT_ID,
            client_secret=client_secret or Config.TWITCH_CLIENT_SECRET
        )

        self.access_token = access_token or Config.TWITCH_ACCESS_TOKEN
        if not self.access_token and not Config.TWITCH_REFRESH_TOKEN:
            raise ValueError(
                "IRCにはユーザーアクセストークンまたはリフレッシュトークンが必要です。\n"
                "初回認証を実行してください: python oauth_authenticator.py"
            )

        self.db_manager = DatabaseManager(database_url or Config.DATABASE_URL)
        self.irc_client: Optional[TwitchIRCClient] = None

        # チャンネルごとの配信ID管理
        self.channel_streams: Dict[str, Optional[str]] = {}  # user_id -> stream_id

        logger.info("TwitchChatCollectorを初期化しました")
        logger.info("TokenManager統合: トークン自動更新が有効です")

    async def collect_from_channels(self, channels: List[ChannelConfig]):
        """
        複数チャンネルから同時にチャットを収集

        Args:
            channels: 監視対象チャンネルのリスト
        """
        if not channels:
            logger.warning("監視対象チャンネルが指定されていません")
            return

        logger.info(f"{len(channels)}チャンネルからチャット収集を開始")

        # ⚠️ 起動時トークン検証（公式推奨: 必須要件）
        logger.info("起動時トークン検証を実行中...")
        try:
            validation = await self.token_manager.validate_token(self.access_token)
            if validation:
                logger.info(
                    f"トークン検証成功: {validation['login']} "
                    f"(残り {validation['expires_in']}秒)"
                )
            else:
                # トークン無効 → リフレッシュ試行
                logger.warning("トークン無効を検出、リフレッシュを試行...")
                new_tokens = await self.token_manager.refresh_access_token(
                    Config.TWITCH_REFRESH_TOKEN
                )
                self.access_token = new_tokens['access_token']
                logger.info("トークンリフレッシュ成功")
        except Exception as e:
            logger.error(f"起動時トークン検証/リフレッシュ失敗: {e}")
            raise

        # チャンネル情報を取得
        channel_map = await self._get_channel_info(channels)

        if not channel_map:
            logger.error("有効なチャンネルが見つかりません")
            return

        # IRCクライアントの初期化（⚠️ TokenManager渡す）
        self.irc_client = TwitchIRCClient(
            access_token=self.access_token,
            token_manager=self.token_manager,  # ⚠️ TokenManager統合
            on_message=self._handle_message,
            on_delete=self._handle_delete,
            on_ban=self._handle_ban
        )

        try:
            # IRC WebSocket接続（リトライロジック）
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logger.info(f"IRC WebSocket接続試行 ({attempt + 1}/{max_retries})...")
                    await self.irc_client.connect()
                    break
                except ConnectionError as e:
                    # トークン更新後の再接続要求
                    if "再接続" in str(e) and attempt < max_retries - 1:
                        logger.info(f"トークン更新後の再接続（試行 {attempt + 1}/{max_retries}）")
                        await asyncio.sleep(2)
                        # 新しいトークンを取得
                        self.access_token = await self.token_manager.get_valid_access_token(
                            Config.TWITCH_ACCESS_TOKEN,
                            Config.TWITCH_REFRESH_TOKEN
                        )
                        # IRCクライアントを再作成
                        self.irc_client = TwitchIRCClient(
                            access_token=self.access_token,
                            token_manager=self.token_manager,
                            on_message=self._handle_message,
                            on_delete=self._handle_delete,
                            on_ban=self._handle_ban
                        )
                        continue
                    raise
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"IRC接続失敗、リトライします: {e}")
                        await asyncio.sleep(2)
                        continue
                    raise

            # 全チャンネルに参加
            await self._join_all_channels(channel_map)

            # IRCメッセージをリッスン
            await self.irc_client.listen()

        except KeyboardInterrupt:
            logger.info("ユーザーによる中断")
        except Exception as e:
            logger.error(f"予期しないエラー: {e}", exc_info=True)
        finally:
            # IRC WebSocket接続を閉じる
            if self.irc_client:
                await self.irc_client.close()

        logger.info("チャット収集を終了")

    async def _get_channel_info(
        self,
        channels: List[ChannelConfig]
    ) -> Dict[str, Dict[str, Any]]:
        """
        チャンネル情報を取得

        Args:
            channels: チャンネル設定のリスト

        Returns:
            user_id -> チャンネル情報のマッピング
        """
        # user_loginとuser_idのリストを作成
        user_logins = [ch.user_login for ch in channels if ch.user_login]
        user_ids = [ch.user_id for ch in channels if ch.user_id and not ch.user_login]

        # ユーザー情報を取得
        users = self.twitch_client.get_users(
            user_ids=user_ids if user_ids else None,
            user_logins=user_logins if user_logins else None
        )

        channel_map = {}
        for user in users:
            user_id = user['id']
            channel_map[user_id] = {
                'user_id': user_id,
                'user_login': user['login'],
                'user_name': user['display_name']
            }
            logger.info(f"チャンネル情報を取得: {user['display_name']} ({user_id})")

        return channel_map

    async def _join_all_channels(self, channel_map: Dict[str, Dict[str, Any]]):
        """
        全チャンネルにIRC JOIN

        Args:
            channel_map: user_id -> チャンネル情報のマッピング
        """
        logger.info(f"{len(channel_map)}チャンネルに参加中...")

        # IRCチャンネルリスト（user_login）を作成
        channel_logins = []

        for user_id, channel_info in channel_map.items():
            try:
                # 配信中かチェック
                streams = self.twitch_client.get_streams(user_id=user_id)

                if streams:
                    stream_info = streams[0]
                    logger.info(f"{channel_info['user_name']} は配信中: {stream_info['title']}")

                    # データベースに配信情報を保存
                    session = self.db_manager.get_session()
                    try:
                        self.db_manager.save_stream(session, stream_info)
                        self.channel_streams[user_id] = stream_info['stream_id']
                    finally:
                        session.close()
                else:
                    logger.info(f"{channel_info['user_name']} は現在配信していません")
                    self.channel_streams[user_id] = None

                # IRCチャンネルリストに追加
                channel_logins.append(channel_info['user_login'])

            except Exception as e:
                logger.error(
                    f"チャンネル {channel_info['user_name']} の処理失敗: {e}",
                    exc_info=True
                )
                continue

        # IRCチャンネルに一括参加
        await self.irc_client.join_channels(channel_logins)

        logger.info(f"IRC参加完了: {len(channel_logins)}チャンネル")

    async def update_stream_status(self, user_id: str):
        """
        特定チャンネルの配信状態を更新

        Args:
            user_id: ユーザーID
        """
        streams = self.twitch_client.get_streams(user_id=user_id)

        if streams:
            stream_info = streams[0]
            session = self.db_manager.get_session()
            try:
                self.db_manager.save_stream(session, stream_info)
                self.channel_streams[user_id] = stream_info['stream_id']
                logger.info(f"配信開始を検出: {stream_info['user_name']}")
            finally:
                session.close()
        else:
            # 配信終了
            if self.channel_streams.get(user_id):
                logger.info(f"配信終了を検出: user_id={user_id}")
                self.channel_streams[user_id] = None

    async def _handle_message(self, event: Dict[str, Any]):
        """チャットメッセージを処理"""
        session = self.db_manager.get_session()
        try:
            broadcaster_user_id = event['broadcaster_user_id']

            # stream_idを追加
            stream_id = self.channel_streams.get(broadcaster_user_id)
            if stream_id:
                event['stream_id'] = stream_id
            else:
                # 配信IDが不明な場合は取得を試みる
                await self.update_stream_status(broadcaster_user_id)
                stream_id = self.channel_streams.get(broadcaster_user_id)
                if stream_id:
                    event['stream_id'] = stream_id
                else:
                    # stream_idが取得できない場合はスキップ（配信終了後のメッセージ）
                    logger.warning(
                        f"[{event['broadcaster_user_name']}] 配信IDが取得できないため"
                        f"メッセージをスキップ: {event['chatter_user_name']}: "
                        f"{event['message_text'][:30]}..."
                    )
                    return

            self.db_manager.save_chat_message(session, event)

            # ログ出力
            logger.info(
                f"[{event['broadcaster_user_name']}] {event['chatter_user_name']}: "
                f"{event['message_text'][:50]}{'...' if len(event['message_text']) > 50 else ''}"
            )
        except Exception as e:
            logger.error(f"メッセージ保存エラー: {e}", exc_info=True)
        finally:
            session.close()

    async def _handle_delete(self, event: Dict[str, Any]):
        """メッセージ削除イベントを処理"""
        session = self.db_manager.get_session()
        try:
            broadcaster_user_id = event['broadcaster_user_id']

            # stream_idを追加
            stream_id = self.channel_streams.get(broadcaster_user_id)
            if stream_id:
                event['stream_id'] = stream_id
            else:
                # stream_idが取得できない場合はスキップ（配信終了後のイベント）
                logger.warning(
                    f"[{event['broadcaster_user_name']}] 配信IDが取得できないため"
                    f"削除イベントをスキップ: {event['target_user_name']} (message_id: {event['message_id']})"
                )
                return

            self.db_manager.save_deleted_event(session, event)

            logger.warning(
                f"[{event['broadcaster_user_name']}] "
                f"{event['target_user_name']}のメッセージが削除されました: {event['message_id']}"
            )
        except Exception as e:
            logger.error(f"削除イベント保存エラー: {e}", exc_info=True)
        finally:
            session.close()

    async def _handle_ban(self, event: Dict[str, Any]):
        """ユーザーBan/タイムアウトイベントを処理"""
        session = self.db_manager.get_session()
        try:
            broadcaster_user_id = event['broadcaster_user_id']

            # stream_idを追加
            stream_id = self.channel_streams.get(broadcaster_user_id)
            if stream_id:
                event['stream_id'] = stream_id
            else:
                # stream_idが取得できない場合はスキップ（配信終了後のイベント）
                ban_type = "永久Ban" if event['is_permanent'] else "タイムアウト"
                logger.warning(
                    f"[{event['broadcaster_user_name']}] 配信IDが取得できないため"
                    f"Banイベントをスキップ: [{ban_type}] {event['user_name']}"
                )
                return

            self.db_manager.save_banned_event(session, event)

            ban_type = "永久Ban" if event['is_permanent'] else "タイムアウト"
            logger.warning(
                f"[{event['broadcaster_user_name']}] [{ban_type}] "
                f"{event['user_name']} by {event['moderator_user_name']}"
            )
        except Exception as e:
            logger.error(f"Banイベント保存エラー: {e}", exc_info=True)
        finally:
            session.close()

    async def _handle_unban(self, event: Dict[str, Any]):
        """ユーザーUnbanイベントを処理"""
        session = self.db_manager.get_session()
        try:
            broadcaster_user_id = event['broadcaster_user_id']

            # stream_idを追加
            stream_id = self.channel_streams.get(broadcaster_user_id)
            if stream_id:
                event['stream_id'] = stream_id
            else:
                # stream_idが取得できない場合はスキップ（配信終了後のイベント）
                logger.warning(
                    f"[{event['broadcaster_user_name']}] 配信IDが取得できないため"
                    f"Unbanイベントをスキップ: {event['user_name']}"
                )
                return

            self.db_manager.save_unbanned_event(session, event)

            logger.info(
                f"[{event['broadcaster_user_name']}] [Unban] "
                f"{event['user_name']} by {event['moderator_user_name']}"
            )
        except Exception as e:
            logger.error(f"Unbanイベント保存エラー: {e}", exc_info=True)
        finally:
            session.close()

    def get_statistics(self, stream_id: str) -> Dict[str, Any]:
        """
        収集統計を取得

        Args:
            stream_id: 配信ID

        Returns:
            統計情報の辞書
        """
        session = self.db_manager.get_session()
        try:
            stats = self.db_manager.get_statistics(session, stream_id)
            logger.info(f"統計情報: {stats}")
            return stats
        finally:
            session.close()


async def main():
    """メイン関数 - CLIエントリーポイント"""
    import argparse

    parser = argparse.ArgumentParser(description='Twitch Live Chat Collector')
    parser.add_argument('--user-login', help='収集するユーザーのログイン名')
    parser.add_argument('--user-id', help='収集するユーザーID')
    parser.add_argument('--config', default='channels.yaml', help='設定ファイルのパス')
    parser.add_argument('--stats', help='統計情報を表示する配信ID')

    args = parser.parse_args()

    # ロギング設定
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(Config.LOG_FILE) if Config.LOG_FILE else logging.NullHandler(),
            logging.StreamHandler()
        ]
    )

    # 設定のバリデーション
    Config.validate()

    # コレクター初期化
    collector = TwitchChatCollector()

    if args.stats:
        # 統計情報を表示
        stats = collector.get_statistics(args.stats)
        print("\n=== 収集統計 ===")
        print(f"配信ID: {stats['stream_id']}")
        print(f"総メッセージ数: {stats['total_messages']}")
        print(f"削除されたメッセージ数: {stats['deleted_messages']}")
        print(f"Banされたユーザー数: {stats['banned_users']}")

    elif args.user_login or args.user_id:
        # 1チャンネルのみを監視（後方互換性）
        from config_loader import ChannelConfig
        channel = ChannelConfig(
            user_login=args.user_login,
            user_id=args.user_id,
            enabled=True
        )
        await collector.collect_from_channels([channel])

    elif args.config:
        # 設定ファイルから複数チャンネルを監視
        from config_loader import load_config

        try:
            config = load_config(args.config)
            enabled_channels = config.get_enabled_channels()

            if not enabled_channels:
                print("有効なチャンネルが設定されていません")
                return

            print(f"\n{len(enabled_channels)}チャンネルを監視します:")
            for ch in enabled_channels:
                print(f"  - {ch.display_name or ch.get_identifier()}")

            await collector.collect_from_channels(enabled_channels)

        except FileNotFoundError:
            print(f"設定ファイルが見つかりません: {args.config}")
            print("channels.yaml.exampleを参考に設定ファイルを作成してください")
        except Exception as e:
            print(f"エラー: {e}")

    else:
        parser.print_help()


if __name__ == '__main__':
    asyncio.run(main())
