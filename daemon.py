"""
デーモン - スケジューラーとコレクターを統合管理

このスクリプトは以下の処理を行います：
1. データベースの初期化
2. スケジューラーとコレクターを並行実行
3. シグナルハンドリング
4. PIDファイル管理
"""

import asyncio
import logging
import signal
import sys
import os
from pathlib import Path
from typing import Optional

from config import Config
from models import init_database
from scheduler import StreamScheduler
from collector import TwitchChatCollector
from config_loader import load_config

logger = logging.getLogger(__name__)


class CollectorDaemon:
    """収集デーモン - スケジューラーとコレクターを統合管理"""

    def __init__(
        self,
        config_path: str = 'channels.yaml',
        pid_file: str = '/tmp/twitch_chat_collector.pid'
    ):
        """
        デーモンの初期化

        Args:
            config_path: 設定ファイルのパス
            pid_file: PIDファイルのパス
        """
        self.config_path = config_path
        self.pid_file = pid_file
        self.scheduler: Optional[StreamScheduler] = None
        self.collector: Optional[TwitchChatCollector] = None
        self.running = True

        # シグナルハンドラの設定
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("デーモンを初期化しました")

    def _signal_handler(self, signum, frame):
        """シグナルハンドラ"""
        logger.info(f"シグナル {signum} を受信しました。全プロセスを停止中...")
        self.running = False

        # スケジューラーを停止
        if self.scheduler:
            self.scheduler.running = False

    def init_database(self):
        """データベースの初期化"""
        logger.info("データベースを初期化中...")
        try:
            init_database(Config.DATABASE_URL)
            logger.info("データベースの初期化が完了しました")
        except Exception as e:
            logger.error(f"データベースの初期化に失敗しました: {e}")
            raise

    def write_pid_file(self):
        """PIDファイルを作成"""
        pid = os.getpid()
        try:
            with open(self.pid_file, 'w') as f:
                f.write(str(pid))
            logger.info(f"PIDファイルを作成しました: {self.pid_file} (PID: {pid})")
        except Exception as e:
            logger.error(f"PIDファイルの作成に失敗しました: {e}")

    def remove_pid_file(self):
        """PIDファイルを削除"""
        try:
            if os.path.exists(self.pid_file):
                os.remove(self.pid_file)
                logger.info(f"PIDファイルを削除しました: {self.pid_file}")
        except Exception as e:
            logger.error(f"PIDファイルの削除に失敗しました: {e}")

    def check_pid_file(self) -> bool:
        """
        既存のPIDファイルをチェック

        Returns:
            既に実行中の場合True
        """
        if not os.path.exists(self.pid_file):
            return False

        try:
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())

            # プロセスが実際に実行中かチェック
            try:
                os.kill(pid, 0)  # シグナル0は存在チェックのみ
                logger.error(f"デーモンは既に実行中です (PID: {pid})")
                return True
            except OSError:
                # プロセスが存在しない場合は古いPIDファイルを削除
                logger.warning(f"古いPIDファイルを削除します: {self.pid_file}")
                os.remove(self.pid_file)
                return False

        except Exception as e:
            logger.error(f"PIDファイルのチェックに失敗しました: {e}")
            return False

    async def run(self):
        """デーモンを実行"""
        # 既に実行中かチェック
        if self.check_pid_file():
            logger.error("既に実行中のため、起動を中止します")
            return

        # PIDファイルを作成
        self.write_pid_file()

        try:
            # データベースの初期化
            self.init_database()

            # 設定ファイルを読み込み
            config = load_config(self.config_path)
            enabled_channels = config.get_enabled_channels()

            if not enabled_channels:
                logger.error("有効なチャンネルが設定されていません")
                return

            logger.info(f"{len(enabled_channels)}チャンネルを監視します")
            for ch in enabled_channels:
                logger.info(f"  - {ch.display_name or ch.get_identifier()}")

            # スケジューラーの初期化
            self.scheduler = StreamScheduler(self.config_path)

            # コレクターの初期化
            self.collector = TwitchChatCollector()

            # スケジューラーとコレクターを並行実行
            logger.info("スケジューラーとコレクターを起動します...")

            tasks = [
                asyncio.create_task(
                    self.scheduler.run(),
                    name="scheduler"
                ),
                asyncio.create_task(
                    self.collector.collect_from_channels(enabled_channels),
                    name="collector"
                )
            ]

            # 両方のタスクが完了するまで待機
            await asyncio.gather(*tasks, return_exceptions=True)

        except KeyboardInterrupt:
            logger.info("ユーザーによる中断")

        except Exception as e:
            logger.error(f"デーモンでエラーが発生しました: {e}", exc_info=True)

        finally:
            # PIDファイルを削除
            self.remove_pid_file()
            logger.info("デーモンを停止しました")


async def main():
    """メイン関数 - CLIエントリーポイント"""
    import argparse

    parser = argparse.ArgumentParser(description='Twitch Chat Collector Daemon')
    parser.add_argument(
        '--config',
        default='channels.yaml',
        help='設定ファイルのパス'
    )
    parser.add_argument(
        '--pid-file',
        default='/tmp/twitch_chat_collector.pid',
        help='PIDファイルのパス'
    )
    parser.add_argument(
        '--stop',
        action='store_true',
        help='実行中のデーモンを停止'
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

    # デーモンを停止
    if args.stop:
        if not os.path.exists(args.pid_file):
            print("デーモンは実行されていません")
            return

        try:
            with open(args.pid_file, 'r') as f:
                pid = int(f.read().strip())

            print(f"デーモンを停止中... (PID: {pid})")
            os.kill(pid, signal.SIGTERM)
            print("停止シグナルを送信しました")

        except Exception as e:
            print(f"エラー: {e}")

        return

    # デーモンを起動
    daemon = CollectorDaemon(
        config_path=args.config,
        pid_file=args.pid_file
    )

    await daemon.run()


if __name__ == '__main__':
    asyncio.run(main())
