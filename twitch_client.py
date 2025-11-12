"""
Twitch Helix API クライアント - ストリーム情報とユーザー情報の取得
"""
import logging
import requests
from typing import Optional, Dict, List, Any
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)


class TwitchAPIClient:
    """Twitch Helix API v5 クライアント"""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        access_token: Optional[str] = None
    ):
        self.client_id = client_id or Config.TWITCH_CLIENT_ID
        self.client_secret = client_secret or Config.TWITCH_CLIENT_SECRET
        self.access_token = access_token or Config.TWITCH_ACCESS_TOKEN

        if not self.client_id or not self.client_secret:
            raise ValueError("Twitch Client IDとClient Secretが必要です")

        # アクセストークンが設定されていない場合は取得
        if not self.access_token:
            self.access_token = self._get_app_access_token()

        self.headers = {
            'Client-ID': self.client_id,
            'Authorization': f'Bearer {self.access_token}'
        }

        logger.info("Twitch API クライアントを初期化しました")

    def update_access_token(self, new_access_token: str):
        """
        アクセストークンを更新

        Args:
            new_access_token: 新しいアクセストークン
        """
        self.access_token = new_access_token
        self.headers['Authorization'] = f'Bearer {new_access_token}'
        logger.info("アクセストークンを更新しました")

    def _get_app_access_token(self) -> str:
        """
        アプリアクセストークンを取得（Client Credentials Flow）

        Returns:
            アクセストークン
        """
        logger.info("アプリアクセストークンを取得中...")

        params = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'client_credentials'
        }

        response = requests.post(Config.TWITCH_OAUTH_URL, params=params)
        response.raise_for_status()

        data = response.json()
        access_token = data.get('access_token')

        if not access_token:
            raise ValueError("アクセストークンの取得に失敗しました")

        logger.info("アプリアクセストークンを取得しました")
        return access_token

    def validate_token(self) -> Dict[str, Any]:
        """
        アクセストークンの検証

        Returns:
            トークン情報の辞書
        """
        headers = {'Authorization': f'Bearer {self.access_token}'}
        response = requests.get('https://id.twitch.tv/oauth2/validate', headers=headers)
        response.raise_for_status()

        token_info = response.json()
        logger.info(f"トークン検証成功: {token_info.get('client_id')}")
        return token_info

    def get_streams(
        self,
        user_id: Optional[str] = None,
        user_login: Optional[str] = None,
        game_id: Optional[str] = None,
        language: Optional[str] = None,
        first: int = 20
    ) -> List[Dict[str, Any]]:
        """
        ライブ配信中のストリームを取得

        Args:
            user_id: ユーザーID（複数指定可）
            user_login: ユーザーログイン名（複数指定可）
            game_id: ゲームID
            language: 配信言語（例: 'ja', 'en'）
            first: 取得件数（最大100）

        Returns:
            ストリーム情報のリスト
        """
        url = f'{Config.TWITCH_API_BASE_URL}/streams'
        params = {'first': min(first, 100)}

        if user_id:
            params['user_id'] = user_id
        if user_login:
            params['user_login'] = user_login
        if game_id:
            params['game_id'] = game_id
        if language:
            params['language'] = language

        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()

            data = response.json()
            streams = data.get('data', [])

            logger.info(f"{len(streams)}件のライブ配信を取得しました")
            return self._parse_streams(streams)

        except requests.exceptions.HTTPError as e:
            # 401エラーの場合、トークンを再取得してリトライ
            if e.response.status_code == 401:
                logger.warning("401 Unauthorized検出、トークンを再取得してリトライします")
                try:
                    # 新しいApp Access Tokenを取得
                    self.access_token = self._get_app_access_token()
                    self.headers['Authorization'] = f'Bearer {self.access_token}'

                    # リトライ
                    response = requests.get(url, headers=self.headers, params=params)
                    response.raise_for_status()

                    data = response.json()
                    streams = data.get('data', [])

                    logger.info(f"{len(streams)}件のライブ配信を取得しました（リトライ成功）")
                    return self._parse_streams(streams)
                except Exception as retry_error:
                    logger.error(f"トークン再取得後のリトライ失敗: {retry_error}")
                    raise
            else:
                logger.error(f"Twitch API エラー (ストリーム取得): {e}")
                raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Twitch API エラー (ストリーム取得): {e}")
            raise

    def get_users(
        self,
        user_ids: Optional[List[str]] = None,
        user_logins: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        ユーザー情報を取得

        Args:
            user_ids: ユーザーIDのリスト（最大100）
            user_logins: ユーザーログイン名のリスト（最大100）

        Returns:
            ユーザー情報のリスト
        """
        url = f'{Config.TWITCH_API_BASE_URL}/users'
        params = {}

        if user_ids:
            params['id'] = user_ids
        if user_logins:
            params['login'] = user_logins

        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()

            data = response.json()
            users = data.get('data', [])

            logger.info(f"{len(users)}件のユーザー情報を取得しました")
            return users

        except requests.exceptions.HTTPError as e:
            # 401エラーの場合、トークンを再取得してリトライ
            if e.response.status_code == 401:
                logger.warning("401 Unauthorized検出、トークンを再取得してリトライします")
                try:
                    # 新しいApp Access Tokenを取得
                    self.access_token = self._get_app_access_token()
                    self.headers['Authorization'] = f'Bearer {self.access_token}'

                    # リトライ
                    response = requests.get(url, headers=self.headers, params=params)
                    response.raise_for_status()

                    data = response.json()
                    users = data.get('data', [])

                    logger.info(f"{len(users)}件のユーザー情報を取得しました（リトライ成功）")
                    return users
                except Exception as retry_error:
                    logger.error(f"トークン再取得後のリトライ失敗: {retry_error}")
                    raise
            else:
                logger.error(f"Twitch API エラー (ユーザー情報取得): {e}")
                raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Twitch API エラー (ユーザー情報取得): {e}")
            raise

    def get_channel_info(self, broadcaster_id: str) -> Optional[Dict[str, Any]]:
        """
        チャンネル情報を取得

        Args:
            broadcaster_id: 配信者のユーザーID

        Returns:
            チャンネル情報の辞書
        """
        url = f'{Config.TWITCH_API_BASE_URL}/channels'
        params = {'broadcaster_id': broadcaster_id}

        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()

            data = response.json()
            channels = data.get('data', [])

            if not channels:
                logger.warning(f"チャンネル情報が見つかりません: {broadcaster_id}")
                return None

            logger.info(f"チャンネル情報を取得: {channels[0].get('broadcaster_name')}")
            return channels[0]

        except requests.exceptions.RequestException as e:
            logger.error(f"Twitch API エラー (チャンネル情報取得): {e}")
            return None

    def _parse_streams(self, streams: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        ストリーム情報を解析

        Args:
            streams: APIレスポンスのストリームリスト

        Returns:
            解析されたストリーム情報のリスト
        """
        parsed_streams = []

        for stream in streams:
            parsed_stream = {
                'stream_id': stream.get('id'),
                'user_id': stream.get('user_id'),
                'user_login': stream.get('user_login'),
                'user_name': stream.get('user_name'),
                'game_id': stream.get('game_id'),
                'game_name': stream.get('game_name'),
                'title': stream.get('title'),
                'viewer_count': stream.get('viewer_count'),
                'language': stream.get('language'),
                'is_mature': stream.get('is_mature', False),
                'started_at': self._parse_datetime(stream.get('started_at')),
            }
            parsed_streams.append(parsed_stream)

        return parsed_streams

    @staticmethod
    def _parse_datetime(datetime_str: Optional[str]) -> Optional[datetime]:
        """RFC3339形式の日時文字列をdatetimeオブジェクトに変換"""
        if not datetime_str:
            return None
        try:
            # RFC3339形式（例: 2024-01-01T12:00:00Z）
            return datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            logger.warning(f"日時の解析に失敗: {datetime_str}")
            return None


if __name__ == '__main__':
    # テスト用
    logging.basicConfig(level=logging.INFO)

    try:
        client = TwitchAPIClient()

        # トークン検証
        token_info = client.validate_token()
        print(f"トークン検証成功: {token_info}")

        # 日本語配信を取得
        streams = client.get_streams(language='ja', first=5)
        print(f"\n日本語ライブ配信 ({len(streams)}件):")
        for stream in streams:
            print(f"  - {stream['user_name']}: {stream['title']}")
            print(f"    視聴者数: {stream['viewer_count']}, ゲーム: {stream['game_name']}")

    except Exception as e:
        print(f"エラー: {e}")
