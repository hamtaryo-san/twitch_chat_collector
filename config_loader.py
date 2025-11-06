"""
設定ファイル（channels.yaml）の読み込みモジュール
"""
import yaml
import logging
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ChannelConfig:
    """チャンネル設定"""
    user_login: Optional[str] = None
    user_id: Optional[str] = None
    display_name: Optional[str] = None
    enabled: bool = True
    notes: Optional[str] = None

    def __post_init__(self):
        """バリデーション"""
        if not self.user_login and not self.user_id:
            raise ValueError("user_loginまたはuser_idのいずれかが必要です")

    def get_identifier(self) -> str:
        """識別子を取得（user_loginを優先）"""
        return self.user_login or self.user_id


@dataclass
class SchedulerConfig:
    """スケジューラー設定"""
    interval_minutes: int = 1
    reconnect_interval: int = 5
    max_reconnect_attempts: int = 10


@dataclass
class CollectorConfig:
    """収集システム全体の設定"""
    channels: List[ChannelConfig]
    scheduler: SchedulerConfig

    def get_enabled_channels(self) -> List[ChannelConfig]:
        """有効なチャンネルのリストを取得"""
        return [ch for ch in self.channels if ch.enabled]


class ConfigLoader:
    """設定ファイル読み込みクラス"""

    def __init__(self, config_path: str = 'channels.yaml'):
        self.config_path = Path(config_path)

    def load(self) -> CollectorConfig:
        """設定ファイルを読み込む"""
        if not self.config_path.exists():
            logger.error(f"設定ファイルが見つかりません: {self.config_path}")
            raise FileNotFoundError(f"設定ファイルが見つかりません: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not data:
            logger.error("設定ファイルが空です")
            raise ValueError("設定ファイルが空です")

        # チャンネル設定の解析
        channels = []
        for ch_data in data.get('channels', []):
            try:
                channel = ChannelConfig(
                    user_login=ch_data.get('user_login'),
                    user_id=ch_data.get('user_id'),
                    display_name=ch_data.get('display_name'),
                    enabled=ch_data.get('enabled', True),
                    notes=ch_data.get('notes')
                )
                channels.append(channel)
            except ValueError as e:
                logger.warning(f"チャンネル設定をスキップ: {e}")
                continue

        # スケジューラー設定の解析
        scheduler_data = data.get('scheduler', {})
        scheduler = SchedulerConfig(
            interval_minutes=scheduler_data.get('interval_minutes', 1),
            reconnect_interval=scheduler_data.get('reconnect_interval', 5),
            max_reconnect_attempts=scheduler_data.get('max_reconnect_attempts', 10)
        )

        config = CollectorConfig(
            channels=channels,
            scheduler=scheduler
        )

        logger.info(f"設定ファイルを読み込みました: {len(channels)}チャンネル")
        logger.info(f"有効なチャンネル: {len(config.get_enabled_channels())}件")
        logger.info(f"チェック間隔: {scheduler.interval_minutes}分")

        return config

    def validate(self, config: CollectorConfig) -> bool:
        """設定の妥当性をチェック"""
        if not config.channels:
            logger.error("監視対象チャンネルが設定されていません")
            return False

        enabled_channels = config.get_enabled_channels()
        if not enabled_channels:
            logger.warning("有効なチャンネルがありません")
            return False

        # チャンネル識別子の形式チェック
        for ch in enabled_channels:
            identifier = ch.get_identifier()
            if not identifier or len(identifier) < 2:
                logger.error(f"不正なチャンネル識別子: {identifier}")
                return False

        # スケジューラー設定のチェック
        if config.scheduler.interval_minutes < 1:
            logger.error("interval_minutesは1以上である必要があります")
            return False

        if config.scheduler.reconnect_interval < 1:
            logger.error("reconnect_intervalは1以上である必要があります")
            return False

        if config.scheduler.max_reconnect_attempts < 1:
            logger.error("max_reconnect_attemptsは1以上である必要があります")
            return False

        logger.info("設定の妥当性チェックをパスしました")
        return True


def load_config(config_path: str = 'channels.yaml') -> CollectorConfig:
    """設定ファイルを読み込む（ヘルパー関数）"""
    loader = ConfigLoader(config_path)
    config = loader.load()

    if not loader.validate(config):
        raise ValueError("設定ファイルに問題があります")

    return config


if __name__ == '__main__':
    # テスト用
    logging.basicConfig(level=logging.INFO)

    try:
        config = load_config('channels.yaml.example')
        print("\n=== 設定情報 ===")
        print(f"有効なチャンネル数: {len(config.get_enabled_channels())}")
        for ch in config.get_enabled_channels():
            print(f"  - {ch.display_name or ch.get_identifier()}")
        print(f"\nチェック間隔: {config.scheduler.interval_minutes}分")
    except Exception as e:
        print(f"エラー: {e}")
