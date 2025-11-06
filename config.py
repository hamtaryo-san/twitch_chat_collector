"""
設定管理 - Twitch Chat Collector
"""
import os
from typing import Optional
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()


class Config:
    """アプリケーション設定"""

    # Twitch API設定
    TWITCH_CLIENT_ID: str = os.getenv('TWITCH_CLIENT_ID', '')
    TWITCH_CLIENT_SECRET: str = os.getenv('TWITCH_CLIENT_SECRET', '')
    # ユーザーアクセストークン（IRC用、必要スコープ: chat:read）
    TWITCH_ACCESS_TOKEN: Optional[str] = os.getenv('TWITCH_ACCESS_TOKEN')

    # Twitch API URL
    TWITCH_API_BASE_URL: str = 'https://api.twitch.tv/helix'
    TWITCH_OAUTH_URL: str = 'https://id.twitch.tv/oauth2/token'

    # データベース設定
    DATABASE_URL: str = os.getenv(
        'DATABASE_URL',
        'sqlite:///twitch_chats.db'
    )

    # ログ設定
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE: Optional[str] = os.getenv('LOG_FILE', 'collector.log')

    # コレクション設定
    RECONNECT_INTERVAL: int = int(os.getenv('RECONNECT_INTERVAL', '5'))
    MAX_RECONNECT_ATTEMPTS: int = int(os.getenv('MAX_RECONNECT_ATTEMPTS', '10'))

    @classmethod
    def validate(cls) -> bool:
        """
        必須設定項目のバリデーション

        Returns:
            設定が有効な場合True
        """
        if not cls.TWITCH_CLIENT_ID:
            raise ValueError("TWITCH_CLIENT_IDが設定されていません")
        if not cls.TWITCH_CLIENT_SECRET:
            raise ValueError("TWITCH_CLIENT_SECRETが設定されていません")
        return True


if __name__ == '__main__':
    # 設定のテスト
    try:
        Config.validate()
        print("設定が正常に読み込まれました")
        print(f"Client ID: {Config.TWITCH_CLIENT_ID[:8]}...")
        print(f"Database URL: {Config.DATABASE_URL}")
    except ValueError as e:
        print(f"設定エラー: {e}")
