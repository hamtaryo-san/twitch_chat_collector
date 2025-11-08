"""
スケジューラー - 配信情報を定期的に取得して状態を監視

定期的に実行され、以下の処理を行う：
1. channels.yamlから監視対象チャンネルを読み込み
2. 各チャンネルの配信状態を取得
3. 配信開始・終了を検出してログ記録
"""

import asyncio
import logging
import signal
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
from config import Config
from config_loader import load_config, ChannelConfig
from twitch_client import TwitchAPIClient
from database import DatabaseManager
from token_manager import TokenManager

logger = logging.getLogger(__name__)


class StreamScheduler:
    """配信スケジューラー"""

    def __init__(self, config_path: str = 'channels.yaml'):
        """
        スケジューラーの初期化

        Args:
            config_path: 設定ファイルのパス
        """
        self.config_path = config_path
        self.config = load_config(config_path)

        # ⚠️ TokenManager初期化（トークン自動更新用）
        self.token_manager = TokenManager(
            client_id=Config.TWITCH_CLIENT_ID,
            client_secret=Config.TWITCH_CLIENT_SECRET
        )

        self.twitch_client = TwitchAPIClient()
        self.db_manager = DatabaseManager(Config.DATABASE_URL)
        self.running = True

        # 現在配信中のユーザーID
        self.live_users: Set[str] = set()

        # シグナルハンドラの設定
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("スケジューラーを初期化しました")

    def _signal_handler(self, signum, frame):
        """シグナルハンドラ"""
        logger.info(f"シグナル {signum} を受信しました。停止中...")
        self.running = False

    def fetch_streams_from_channels(
        self,
        channels: List[ChannelConfig]
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        複数チャンネルの配信情報を取得

        Args:
            channels: チャンネル設定のリスト

        Returns:
            user_id -> 配信情報のマッピング（配信していない場合はNone）
        """
        if not channels:
            return {}

        # user_loginとuser_idのリストを作成
        user_logins = [ch.user_login for ch in channels if ch.user_login]
        user_ids = [ch.user_id for ch in channels if ch.user_id and not ch.user_login]

        # ユーザー情報を取得してuser_idを確定
        users = self.twitch_client.get_users(
            user_ids=user_ids if user_ids else None,
            user_logins=user_logins if user_logins else None
        )

        user_id_map = {user['id']: user for user in users}

        # 全チャンネルの配信状態を取得（最大100件まで一度に取得可能）
        all_user_ids = list(user_id_map.keys())
        streams_map: Dict[str, Optional[Dict[str, Any]]] = {}

        # user_idを100件ずつに分割して取得
        for i in range(0, len(all_user_ids), 100):
            batch_user_ids = all_user_ids[i:i + 100]

            try:
                # 配信中のストリームを取得
                streams = []
                for user_id in batch_user_ids:
                    user_streams = self.twitch_client.get_streams(user_id=user_id)
                    streams.extend(user_streams)

                # 配信情報をuser_idでマッピング
                for stream in streams:
                    user_id = stream['user_id']
                    streams_map[user_id] = stream

                # 配信していないユーザーにはNoneを設定
                for user_id in batch_user_ids:
                    if user_id not in streams_map:
                        streams_map[user_id] = None

            except Exception as e:
                logger.error(f"配信情報の取得エラー (batch {i}-{i+100}): {e}", exc_info=True)
                # エラー時は該当バッチのユーザーにNoneを設定
                for user_id in batch_user_ids:
                    if user_id not in streams_map:
                        streams_map[user_id] = None

        return streams_map

    async def check_and_save_streams(self) -> Dict[str, Any]:
        """
        配信状態をチェックしてデータベースに保存

        Returns:
            チェック結果の統計情報
        """
        # ⚠️ API呼び出し前にトークン検証・更新
        try:
            new_token = await self.token_manager.get_valid_access_token(
                Config.TWITCH_ACCESS_TOKEN,
                Config.TWITCH_REFRESH_TOKEN
            )
            # TwitchAPIClientのトークンを更新
            self.twitch_client.update_access_token(new_token)
        except Exception as e:
            logger.error(f"トークン更新エラー: {e}")
            # エラー時も処理継続（既存トークンで試行）

        logger.info("配信状態をチェック中...")

        enabled_channels = self.config.get_enabled_channels()
        if not enabled_channels:
            logger.warning("有効なチャンネルがありません")
            return {'checked': 0, 'live': 0, 'started': 0, 'ended': 0}

        # 配信情報を取得
        streams_map = self.fetch_streams_from_channels(enabled_channels)

        stats = {
            'checked': len(streams_map),
            'live': 0,
            'started': 0,
            'ended': 0
        }

        session = self.db_manager.get_session()
        try:
            current_live_users = set()

            for user_id, stream_info in streams_map.items():
                if stream_info:
                    # 配信中
                    current_live_users.add(user_id)
                    stats['live'] += 1

                    # 新規配信開始を検出
                    if user_id not in self.live_users:
                        logger.info(
                            f"配信開始を検出: {stream_info['user_name']} - {stream_info['title']}"
                        )
                        stats['started'] += 1

                    # データベースに配信情報を保存
                    self.db_manager.save_stream(session, stream_info)

            # 配信終了を検出
            for user_id in self.live_users:
                if user_id not in current_live_users:
                    logger.info(f"配信終了を検出: user_id={user_id}")
                    stats['ended'] += 1

                    # データベースの配信情報を更新（ended_atを設定）
                    active_streams = self.db_manager.get_active_streams(session)
                    for stream in active_streams:
                        if stream.user_id == user_id:
                            stream.ended_at = datetime.utcnow()
                            session.commit()
                            break

            # 配信中ユーザーリストを更新
            self.live_users = current_live_users

            logger.info(
                f"チェック完了: {stats['checked']}チャンネル, "
                f"{stats['live']}配信中, "
                f"{stats['started']}開始, "
                f"{stats['ended']}終了"
            )

        finally:
            session.close()

        return stats

    async def run(self, interval_minutes: Optional[int] = None):
        """
        スケジューラーを実行

        Args:
            interval_minutes: チェック間隔（分）。Noneの場合は設定ファイルから取得
        """
        if interval_minutes is None:
            interval_minutes = self.config.scheduler.interval_minutes

        interval_seconds = interval_minutes * 60

        logger.info(f"スケジューラーを開始しました（間隔: {interval_minutes}分）")

        # 初回チェック
        await self.check_and_save_streams()

        while self.running:
            try:
                # 指定された間隔で待機
                await asyncio.sleep(interval_seconds)

                if not self.running:
                    break

                # 配信状態をチェック
                await self.check_and_save_streams()

            except KeyboardInterrupt:
                logger.info("ユーザーによる中断")
                break

            except Exception as e:
                logger.error(f"スケジューラーエラー: {e}", exc_info=True)
                # エラーが発生してもスケジューラーは継続
                await asyncio.sleep(60)  # 1分待機してから再試行

        logger.info("スケジューラーを停止しました")

    async def run_once(self) -> Dict[str, Any]:
        """
        1回だけチェックを実行（テスト用）

        Returns:
            チェック結果の統計情報
        """
        return await self.check_and_save_streams()


async def main():
    """メイン関数 - CLIエントリーポイント"""
    import argparse

    parser = argparse.ArgumentParser(description='Twitch Stream Scheduler')
    parser.add_argument(
        '--config',
        default='channels.yaml',
        help='設定ファイルのパス'
    )
    parser.add_argument(
        '--interval',
        type=int,
        help='チェック間隔（分）'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='1回だけチェックして終了'
    )

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

    # スケジューラー初期化
    scheduler = StreamScheduler(args.config)

    if args.once:
        # 1回だけ実行
        stats = await scheduler.run_once()
        print("\n=== チェック結果 ===")
        print(f"チェックしたチャンネル数: {stats['checked']}")
        print(f"配信中: {stats['live']}")
        print(f"新規開始: {stats['started']}")
        print(f"終了: {stats['ended']}")
    else:
        # 継続実行
        await scheduler.run(interval_minutes=args.interval)


if __name__ == '__main__':
    asyncio.run(main())
