"""
Twitch EventSub WebSocketクライアント - リアルタイムチャットイベント受信
"""
import asyncio
import json
import logging
import websockets
from typing import Optional, Dict, Any, Callable
from datetime import datetime
import requests
from config import Config

logger = logging.getLogger(__name__)


class TwitchEventSubClient:
    """Twitch EventSub WebSocketクライアント"""

    def __init__(
        self,
        client_id: str,
        access_token: str,
        on_message: Optional[Callable] = None,
        on_delete: Optional[Callable] = None,
        on_ban: Optional[Callable] = None,
        on_unban: Optional[Callable] = None
    ):
        """
        EventSubクライアントの初期化

        Args:
            client_id: Twitch Client ID
            access_token: ユーザーアクセストークン
            on_message: チャットメッセージ受信時のコールバック
            on_delete: メッセージ削除時のコールバック
            on_ban: ユーザーBan時のコールバック
            on_unban: ユーザーUnban時のコールバック
        """
        self.client_id = client_id
        self.access_token = access_token
        self.session_id: Optional[str] = None
        self.websocket = None
        self.is_connected = False

        # イベントハンドラー
        self.on_message = on_message
        self.on_delete = on_delete
        self.on_ban = on_ban
        self.on_unban = on_unban

        # サブスクリプション管理
        self.subscriptions: Dict[str, str] = {}

        logger.info("EventSubクライアントを初期化しました")

    async def connect(self):
        """WebSocketサーバーに接続"""
        logger.info("EventSub WebSocketに接続中...")

        try:
            self.websocket = await websockets.connect(
                Config.TWITCH_EVENTSUB_WS_URL,
                ping_interval=20,
                ping_timeout=10
            )
            self.is_connected = True
            logger.info("EventSub WebSocketに接続しました")

            # Welcomeメッセージを待機
            await self._handle_welcome()

        except Exception as e:
            logger.error(f"WebSocket接続エラー: {e}")
            self.is_connected = False
            raise

    async def _handle_welcome(self):
        """Welcomeメッセージを処理してセッションIDを取得"""
        try:
            message = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            data = json.loads(message)

            if data.get('metadata', {}).get('message_type') == 'session_welcome':
                session = data.get('payload', {}).get('session', {})
                self.session_id = session.get('id')
                keepalive_timeout = session.get('keepalive_timeout_seconds')

                logger.info(f"セッション確立: {self.session_id}")
                logger.info(f"Keepaliveタイムアウト: {keepalive_timeout}秒")
            else:
                raise ValueError("Welcomeメッセージが受信できませんでした")

        except asyncio.TimeoutError:
            logger.error("Welcomeメッセージのタイムアウト")
            raise

    async def subscribe_to_channel_events(
        self,
        broadcaster_user_id: str,
        subscribe_chat: bool = True,
        subscribe_moderation: bool = True
    ):
        """
        チャンネルのイベントをサブスクライブ

        Args:
            broadcaster_user_id: 配信者のユーザーID
            subscribe_chat: チャットメッセージをサブスクライブするか
            subscribe_moderation: モデレーションイベントをサブスクライブするか
        """
        if not self.session_id:
            raise ValueError("セッションIDが設定されていません")

        logger.info(f"チャンネルイベントをサブスクライブ中: {broadcaster_user_id}")

        # チャットメッセージのサブスクリプション
        if subscribe_chat:
            await self._create_subscription(
                'channel.chat.message',
                {'broadcaster_user_id': broadcaster_user_id, 'user_id': broadcaster_user_id}
            )

        # モデレーションイベントのサブスクリプション
        if subscribe_moderation:
            # メッセージ削除
            await self._create_subscription(
                'channel.chat.message_delete',
                {'broadcaster_user_id': broadcaster_user_id, 'user_id': broadcaster_user_id}
            )

            # ユーザーBan/タイムアウト
            await self._create_subscription(
                'channel.ban',
                {'broadcaster_user_id': broadcaster_user_id}
            )

            # ユーザーUnban
            await self._create_subscription(
                'channel.unban',
                {'broadcaster_user_id': broadcaster_user_id}
            )

    async def _create_subscription(self, event_type: str, condition: Dict[str, str]):
        """
        EventSubサブスクリプションを作成

        Args:
            event_type: イベントタイプ
            condition: サブスクリプション条件
        """
        url = 'https://api.twitch.tv/helix/eventsub/subscriptions'
        headers = {
            'Client-ID': self.client_id,
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

        payload = {
            'type': event_type,
            'version': '1',
            'condition': condition,
            'transport': {
                'method': 'websocket',
                'session_id': self.session_id
            }
        }

        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()

            data = response.json()
            subscription_id = data['data'][0]['id']
            self.subscriptions[event_type] = subscription_id

            logger.info(f"サブスクリプション作成成功: {event_type} (ID: {subscription_id})")

        except requests.exceptions.RequestException as e:
            logger.error(f"サブスクリプション作成エラー ({event_type}): {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"レスポンス: {e.response.text}")
            raise

    async def listen(self):
        """イベントをリッスン"""
        if not self.is_connected or not self.websocket:
            raise ValueError("WebSocketが接続されていません")

        logger.info("イベントのリッスンを開始...")

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
        """受信メッセージを処理"""
        try:
            data = json.loads(message)
            metadata = data.get('metadata', {})
            message_type = metadata.get('message_type')

            if message_type == 'session_keepalive':
                logger.debug("Keepalive受信")

            elif message_type == 'notification':
                await self._handle_notification(data)

            elif message_type == 'session_reconnect':
                reconnect_url = data.get('payload', {}).get('session', {}).get('reconnect_url')
                logger.warning(f"再接続が必要です: {reconnect_url}")
                # 再接続処理は呼び出し側で実装

            elif message_type == 'revocation':
                subscription_type = data.get('payload', {}).get('subscription', {}).get('type')
                logger.warning(f"サブスクリプションが取り消されました: {subscription_type}")

            else:
                logger.debug(f"未知のメッセージタイプ: {message_type}")

        except json.JSONDecodeError:
            logger.error(f"JSONデコードエラー: {message}")

    async def _handle_notification(self, data: Dict[str, Any]):
        """通知イベントを処理"""
        subscription = data.get('payload', {}).get('subscription', {})
        event = data.get('payload', {}).get('event', {})
        event_type = subscription.get('type')

        logger.debug(f"イベント受信: {event_type}")

        if event_type == 'channel.chat.message':
            if self.on_message:
                parsed_event = self._parse_chat_message(event)
                await self._safe_callback(self.on_message, parsed_event)

        elif event_type == 'channel.chat.message_delete':
            if self.on_delete:
                parsed_event = self._parse_message_delete(event)
                await self._safe_callback(self.on_delete, parsed_event)

        elif event_type == 'channel.ban':
            if self.on_ban:
                parsed_event = self._parse_ban_event(event)
                await self._safe_callback(self.on_ban, parsed_event)

        elif event_type == 'channel.unban':
            if self.on_unban:
                parsed_event = self._parse_unban_event(event)
                await self._safe_callback(self.on_unban, parsed_event)

    async def _safe_callback(self, callback: Callable, event: Dict[str, Any]):
        """コールバックを安全に実行"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(event)
            else:
                callback(event)
        except Exception as e:
            logger.error(f"コールバック実行エラー: {e}", exc_info=True)

    def _parse_chat_message(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """チャットメッセージイベントを解析"""
        message = event.get('message', {})
        chatter = event.get('chatter_user_id')

        return {
            'id': event.get('message_id'),
            'broadcaster_user_id': event.get('broadcaster_user_id'),
            'broadcaster_user_login': event.get('broadcaster_user_login'),
            'broadcaster_user_name': event.get('broadcaster_user_name'),
            'chatter_user_id': chatter,
            'chatter_user_login': event.get('chatter_user_login'),
            'chatter_user_name': event.get('chatter_user_name'),
            'message_text': message.get('text'),
            'color': event.get('color'),
            'badges': json.dumps(event.get('badges', [])),
            'bits': event.get('cheer', {}).get('bits') if event.get('cheer') else None,
            'message_type': event.get('message_type'),
            'sent_at': self._parse_datetime(event.get('sent_at'))
        }

    def _parse_message_delete(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """メッセージ削除イベントを解析"""
        return {
            'broadcaster_user_id': event.get('broadcaster_user_id'),
            'broadcaster_user_login': event.get('broadcaster_user_login'),
            'broadcaster_user_name': event.get('broadcaster_user_name'),
            'target_user_id': event.get('target_user_id'),
            'target_user_login': event.get('target_user_login'),
            'target_user_name': event.get('target_user_name'),
            'message_id': event.get('message_id'),
            'message_text': event.get('message_body'),
            'deleted_at': datetime.utcnow()
        }

    def _parse_ban_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Ban/タイムアウトイベントを解析"""
        return {
            'broadcaster_user_id': event.get('broadcaster_user_id'),
            'broadcaster_user_login': event.get('broadcaster_user_login'),
            'broadcaster_user_name': event.get('broadcaster_user_name'),
            'user_id': event.get('user_id'),
            'user_login': event.get('user_login'),
            'user_name': event.get('user_name'),
            'moderator_user_id': event.get('moderator_user_id'),
            'moderator_user_login': event.get('moderator_user_login'),
            'moderator_user_name': event.get('moderator_user_name'),
            'reason': event.get('reason'),
            'is_permanent': event.get('is_permanent'),
            'ends_at': self._parse_datetime(event.get('ends_at')),
            'banned_at': self._parse_datetime(event.get('banned_at'))
        }

    def _parse_unban_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Unbanイベントを解析"""
        return {
            'broadcaster_user_id': event.get('broadcaster_user_id'),
            'broadcaster_user_login': event.get('broadcaster_user_login'),
            'broadcaster_user_name': event.get('broadcaster_user_name'),
            'user_id': event.get('user_id'),
            'user_login': event.get('user_login'),
            'user_name': event.get('user_name'),
            'moderator_user_id': event.get('moderator_user_id'),
            'moderator_user_login': event.get('moderator_user_login'),
            'moderator_user_name': event.get('moderator_user_name'),
            'unbanned_at': datetime.utcnow()
        }

    @staticmethod
    def _parse_datetime(datetime_str: Optional[str]) -> Optional[datetime]:
        """RFC3339形式の日時文字列をdatetimeオブジェクトに変換"""
        if not datetime_str:
            return None
        try:
            return datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            logger.warning(f"日時の解析に失敗: {datetime_str}")
            return None

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
        print(f"\n[削除] {event['target_user_name']}のメッセージが削除されました")

    async def on_ban(event):
        ban_type = "永久Ban" if event['is_permanent'] else "タイムアウト"
        print(f"\n[{ban_type}] {event['user_name']} by {event['moderator_user_name']}")

    async def on_unban(event):
        print(f"\n[Unban] {event['user_name']} by {event['moderator_user_name']}")

    async def main():
        if len(sys.argv) < 4:
            print("使用法: python twitch_eventsub.py <client_id> <access_token> <broadcaster_user_id>")
            return

        client_id = sys.argv[1]
        access_token = sys.argv[2]
        broadcaster_user_id = sys.argv[3]

        client = TwitchEventSubClient(
            client_id=client_id,
            access_token=access_token,
            on_message=on_message,
            on_delete=on_delete,
            on_ban=on_ban,
            on_unban=on_unban
        )

        try:
            await client.connect()
            await client.subscribe_to_channel_events(broadcaster_user_id)
            await client.listen()

        except KeyboardInterrupt:
            print("\n中断されました")
        finally:
            await client.close()

    asyncio.run(main())
