"""
Twitch IRC WebSocketクライアント - リアルタイムチャットイベント受信
IRCv3 Message Tagsをサポート

公式ドキュメント準拠:
- IRC認証: PASS oauth:<token> → NICK justinfan12345 の順序厳守
- 認証失敗時: "Login authentication failed" 検出 → トークンリフレッシュ → 再接続
- 必要スコープ: chat:read（読み取りのみ）

参考:
https://dev.twitch.tv/docs/irc/authenticate-bot/
"""
import asyncio
import logging
import re
from typing import Optional, Dict, Any, Callable, Set, TYPE_CHECKING
from datetime import datetime
import websockets

if TYPE_CHECKING:
    from token_manager import TokenManager

logger = logging.getLogger(__name__)


class TwitchIRCClient:
    """Twitch IRC WebSocketクライアント"""

    # IRC WebSocketサーバー
    IRC_WS_URL = 'wss://irc-ws.chat.twitch.tv:443'

    def __init__(
        self,
        access_token: str,
        token_manager: Optional['TokenManager'] = None,
        on_message: Optional[Callable] = None,
        on_delete: Optional[Callable] = None,
        on_ban: Optional[Callable] = None
    ):
        """
        IRCクライアントの初期化

        Args:
            access_token: Twitchアクセストークン（chat:readスコープ）
            token_manager: TokenManagerインスタンス（トークン自動更新用、推奨）
            on_message: チャットメッセージ受信時のコールバック
            on_delete: メッセージ削除時のコールバック
            on_ban: ユーザーBan/タイムアウト時のコールバック
        """
        self.access_token = access_token
        self.token_manager = token_manager
        self.websocket = None
        self.is_connected = False
        self.joined_channels: Set[str] = set()

        # イベントハンドラー
        self.on_message = on_message
        self.on_delete = on_delete
        self.on_ban = on_ban

        # IRCタグのパーサー
        self.tag_pattern = re.compile(r'@([^ ]+) ')
        self.message_pattern = re.compile(r':([^!]+)!.*?PRIVMSG #([^ ]+) :(.+)')

        logger.info("TwitchIRCクライアントを初期化しました")
        if self.token_manager:
            logger.info("TokenManager統合: トークン自動更新が有効です")

    async def connect(self):
        """IRC WebSocketサーバーに接続"""
        logger.info("Twitch IRC WebSocketに接続中...")

        try:
            self.websocket = await websockets.connect(
                self.IRC_WS_URL,
                ping_interval=60,
                ping_timeout=10
            )
            self.is_connected = True
            logger.info("Twitch IRC WebSocketに接続しました")

            # IRC認証とCapability要求
            await self._authenticate()

        except Exception as e:
            logger.error(f"WebSocket接続エラー: {e}")
            self.is_connected = False
            raise

    async def _authenticate(self):
        """
        IRC認証とCapability Negotiation

        公式準拠:
        - PASS oauth:<token> → NICK の順序厳守（oauth:接頭辞あり）
        - 認証失敗時は TokenManager でリフレッシュを試行
        """
        # 認証前にトークン有効性チェック（オプション、推奨）
        if self.token_manager:
            try:
                from config import Config
                logger.debug("認証前にトークン有効性をチェック中...")
                self.access_token = await self.token_manager.get_valid_access_token(
                    Config.TWITCH_ACCESS_TOKEN,
                    Config.TWITCH_REFRESH_TOKEN
                )
                logger.debug("トークン有効性チェック完了")
            except Exception as e:
                logger.warning(f"トークン事前チェック失敗（継続）: {e}")

        # IRCv3 Capabilityを要求
        await self.websocket.send('CAP REQ :twitch.tv/tags twitch.tv/commands')

        # ⚠️ 重要: OAuth認証（PASS → NICK の順序厳守）
        # IRC用は oauth: 接頭辞あり（validateと異なる）
        await self.websocket.send(f'PASS oauth:{self.access_token}')
        await self.websocket.send('NICK justinfan12345')  # 匿名ユーザー名

        logger.info("IRC認証を送信しました")

        # 認証完了を待機
        while True:
            response = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            logger.debug(f"認証レスポンス: {response}")

            # 認証成功メッセージを確認
            if '001' in response or 'Welcome' in response:
                logger.info("IRC認証成功")
                break

            # ⚠️ 認証失敗検出（401相当）
            if 'NOTICE' in response and 'Login authentication failed' in response:
                # TokenManagerがあればリフレッシュを試行
                if self.token_manager:
                    logger.warning("IRC認証失敗を検出、トークンリフレッシュを試行...")
                    try:
                        from config import Config
                        new_tokens = await self.token_manager.refresh_access_token(
                            Config.TWITCH_REFRESH_TOKEN
                        )
                        self.access_token = new_tokens['access_token']
                        logger.info("トークンリフレッシュ成功、再接続が必要です")
                        # 再接続が必要なことを通知
                        raise ConnectionError(
                            "トークン更新完了。IRC接続を閉じて再接続してください。"
                        )
                    except ValueError as e:
                        # Refresh Token無効（再認証が必要）
                        raise ValueError(
                            f"IRC認証失敗後のリフレッシュも失敗: {e}\n\n"
                            "再認証が必要です: python oauth_authenticator.py"
                        )
                else:
                    # TokenManagerなし
                    raise ValueError(
                        "IRC認証失敗: アクセストークンが無効です\n\n"
                        "トークンを更新してください:\n"
                        "1. TokenManagerを使用する（推奨）\n"
                        "2. python oauth_authenticator.py で再認証"
                    )

    async def join_channels(self, channels: list[str]):
        """
        複数チャンネルに参加

        Args:
            channels: チャンネル名のリスト（#なしでOK）
        """
        for channel in channels:
            await self.join_channel(channel)

    async def join_channel(self, channel: str):
        """
        チャンネルに参加

        Args:
            channel: チャンネル名（#なしでOK）
        """
        # チャンネル名を正規化（#を追加）
        if not channel.startswith('#'):
            channel = f'#{channel}'

        channel_lower = channel.lower()

        if channel_lower in self.joined_channels:
            logger.debug(f"既に参加済み: {channel_lower}")
            return

        await self.websocket.send(f'JOIN {channel_lower}')
        self.joined_channels.add(channel_lower)
        logger.info(f"チャンネルに参加: {channel_lower}")

    async def listen(self):
        """IRCメッセージをリッスン"""
        if not self.is_connected or not self.websocket:
            raise ValueError("WebSocketが接続されていません")

        logger.info("IRCメッセージのリッスンを開始...")

        try:
            async for message in self.websocket:
                await self._handle_message(message)

        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket接続が閉じられました")
            self.is_connected = False

        except Exception as e:
            logger.error(f"リッスンエラー: {e}", exc_info=True)
            self.is_connected = False
            raise

    async def _handle_message(self, message: str):
        """IRCメッセージを処理"""
        try:
            # PING/PONGハンドリング
            if message.startswith('PING'):
                pong = message.replace('PING', 'PONG')
                await self.websocket.send(pong)
                logger.debug("PONG送信")
                return

            # PRIVMSGメッセージ（チャット）
            if 'PRIVMSG' in message:
                await self._handle_privmsg(message)

            # CLEARMSGメッセージ（削除）
            elif 'CLEARMSG' in message:
                await self._handle_clearmsg(message)

            # CLEARCHATメッセージ（Ban/タイムアウト）
            elif 'CLEARCHAT' in message:
                await self._handle_clearchat(message)

            else:
                logger.debug(f"未処理メッセージ: {message[:100]}")

        except Exception as e:
            logger.error(f"メッセージ処理エラー: {e}", exc_info=True)
            logger.debug(f"問題のメッセージ: {message}")

    async def _handle_privmsg(self, message: str):
        """PRIVMSGメッセージ（チャット）を処理"""
        # タグを解析
        tags = self._parse_tags(message)

        # メッセージ本文を抽出
        match = re.search(r'PRIVMSG #([^ ]+) :(.+)', message)
        if not match:
            return

        channel = match.group(1)
        text = match.group(2).strip()

        if not self.on_message:
            return

        # イベントデータを構築
        event = {
            'id': tags.get('id'),
            'broadcaster_user_id': tags.get('room-id'),
            'broadcaster_user_login': channel,
            'broadcaster_user_name': channel,  # IRCではチャンネル名のみ
            'chatter_user_id': tags.get('user-id'),
            'chatter_user_login': tags.get('login', tags.get('display-name', '').lower()),
            'chatter_user_name': tags.get('display-name'),
            'message_text': text,
            'color': tags.get('color'),
            'badges': tags.get('badges', ''),
            'bits': self._parse_int(tags.get('bits')),
            'message_type': 'chat',
            'is_subscriber': tags.get('subscriber') == '1',
            'is_moderator': tags.get('mod') == '1',
            'is_vip': 'vip' in tags.get('badges', ''),
            'sent_at': self._parse_tmi_timestamp(tags.get('tmi-sent-ts'))
        }

        await self._safe_callback(self.on_message, event)

    async def _handle_clearmsg(self, message: str):
        """CLEARMSGメッセージ（削除）を処理"""
        # タグを解析
        tags = self._parse_tags(message)

        # チャンネル名を抽出
        match = re.search(r'CLEARMSG #([^ ]+)', message)
        if not match:
            return

        channel = match.group(1)

        if not self.on_delete:
            return

        # イベントデータを構築
        event = {
            'broadcaster_user_id': tags.get('room-id'),
            'broadcaster_user_login': channel,
            'broadcaster_user_name': channel,
            'target_user_id': tags.get('target-user-id'),
            'target_user_login': tags.get('login'),
            'target_user_name': tags.get('login'),
            'message_id': tags.get('target-msg-id'),
            'message_text': '',  # IRCでは削除されたメッセージ本文は取得できない
            'deleted_at': datetime.utcnow()
        }

        await self._safe_callback(self.on_delete, event)

    async def _handle_clearchat(self, message: str):
        """CLEARCHATメッセージ（Ban/タイムアウト）を処理"""
        # タグを解析
        tags = self._parse_tags(message)

        # チャンネル名とユーザー名を抽出
        match = re.search(r'CLEARCHAT #([^ ]+)(?: :(.+))?', message)
        if not match:
            return

        channel = match.group(1)
        target_user = match.group(2)

        # target_userがない場合は全チャットクリア（チャンネル全体）
        if not target_user:
            logger.info(f"チャンネル全体のチャットクリア: #{channel}")
            return

        if not self.on_ban:
            return

        # ban-durationの有無で永久Banかタイムアウトか判定
        ban_duration = self._parse_int(tags.get('ban-duration'))
        is_permanent = ban_duration is None

        # イベントデータを構築
        event = {
            'broadcaster_user_id': tags.get('room-id'),
            'broadcaster_user_login': channel,
            'broadcaster_user_name': channel,
            'user_id': tags.get('target-user-id'),
            'user_login': target_user.strip(),
            'user_name': target_user.strip(),
            'moderator_user_id': None,  # IRCでは取得不可
            'moderator_user_login': None,
            'moderator_user_name': None,
            'reason': '',  # IRCでは取得不可
            'is_permanent': is_permanent,
            'ends_at': None if is_permanent else datetime.utcnow(),  # 厳密な計算はDB側で
            'banned_at': self._parse_tmi_timestamp(tags.get('tmi-sent-ts'))
        }

        await self._safe_callback(self.on_ban, event)

    def _parse_tags(self, message: str) -> Dict[str, str]:
        """IRCv3タグを解析"""
        tags = {}

        # タグ部分を抽出
        match = self.tag_pattern.match(message)
        if not match:
            return tags

        tag_string = match.group(1)

        # タグをパース
        for tag in tag_string.split(';'):
            if '=' in tag:
                key, value = tag.split('=', 1)
                # エスケープ解除
                value = value.replace('\\s', ' ').replace('\\:', ';').replace('\\\\', '\\')
                tags[key] = value

        return tags

    @staticmethod
    def _parse_int(value: Optional[str]) -> Optional[int]:
        """文字列を整数に変換"""
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    @staticmethod
    def _parse_tmi_timestamp(tmi_sent_ts: Optional[str]) -> Optional[datetime]:
        """TMIタイムスタンプ（ミリ秒）をdatetimeに変換"""
        if not tmi_sent_ts:
            return datetime.utcnow()
        try:
            timestamp_ms = int(tmi_sent_ts)
            return datetime.utcfromtimestamp(timestamp_ms / 1000.0)
        except (ValueError, OSError):
            logger.warning(f"タイムスタンプの解析に失敗: {tmi_sent_ts}")
            return datetime.utcnow()

    async def _safe_callback(self, callback: Callable, event: Dict[str, Any]):
        """コールバックを安全に実行"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(event)
            else:
                callback(event)
        except Exception as e:
            logger.error(f"コールバック実行エラー: {e}", exc_info=True)

    async def close(self):
        """WebSocket接続を閉じる"""
        if self.websocket:
            await self.websocket.close()
            self.is_connected = False
            logger.info("WebSocket接続を閉じました")


if __name__ == '__main__':
    # テスト用
    import sys

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    async def on_message(event):
        print(f"\n[チャット] {event['chatter_user_name']}: {event['message_text']}")

    async def on_delete(event):
        print(f"\n[削除] {event['target_user_login']}のメッセージが削除されました: {event['message_id']}")

    async def on_ban(event):
        ban_type = "永久Ban" if event['is_permanent'] else "タイムアウト"
        print(f"\n[{ban_type}] {event['user_login']}")

    async def main():
        if len(sys.argv) < 3:
            print("使用法: python twitch_irc.py <access_token> <channel1> [channel2] ...")
            return

        access_token = sys.argv[1]
        channels = sys.argv[2:]

        client = TwitchIRCClient(
            access_token=access_token,
            on_message=on_message,
            on_delete=on_delete,
            on_ban=on_ban
        )

        try:
            await client.connect()
            await client.join_channels(channels)
            await client.listen()

        except KeyboardInterrupt:
            print("\n中断されました")
        finally:
            await client.close()

    asyncio.run(main())
