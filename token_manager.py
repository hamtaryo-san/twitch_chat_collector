"""
Twitch OAuth Token Manager - User Access Tokenの自動更新管理

公式ドキュメント準拠:
- 起動時 + 毎時のトークン検証（必須要件）
- 401エラー時の即座なリフレッシュ（最優先）
- 期限前リフレッシュは補助的位置付け
- マルチスレッド環境での安全なリフレッシュ（1スレッドのみ）

参考:
https://dev.twitch.tv/docs/authentication/refresh-tokens/
https://dev.twitch.tv/docs/authentication/validate-tokens/
"""

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlencode
import requests
from dotenv import load_dotenv, set_key

logger = logging.getLogger(__name__)


class TokenManager:
    """
    Twitch OAuth Token Manager

    機能:
    1. トークンの有効性検証（起動時 + 毎時）
    2. Refresh Tokenを使用した自動更新（401対応最優先）
    3. .envファイルへのトークン保存
    4. マルチスレッド環境での安全なリフレッシュ
    """

    VALIDATE_URL = 'https://id.twitch.tv/oauth2/validate'
    TOKEN_URL = 'https://id.twitch.tv/oauth2/token'

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        env_path: str = '.env'
    ):
        """
        TokenManagerの初期化

        Args:
            client_id: Twitch Client ID
            client_secret: Twitch Client Secret
            env_path: .envファイルのパス
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.env_path = Path(env_path)

        # マルチスレッド環境での競合を防ぐためのロック
        # 公式推奨: 1スレッドだけがリフレッシュして他に配布
        self._refresh_lock = asyncio.Lock()

        logger.debug("TokenManagerを初期化しました")

    async def validate_token(self, access_token: str) -> Optional[Dict[str, Any]]:
        """
        アクセストークンの有効性を検証

        公式ドキュメント: 起動時 + 毎時検証が必須
        エンドポイント: GET https://id.twitch.tv/oauth2/validate
        ヘッダ: Authorization: Bearer <access_token>

        Args:
            access_token: 検証するアクセストークン

        Returns:
            トークンが有効な場合、検証情報の辞書:
            {
                'client_id': str,
                'login': str,          # ユーザー名
                'scopes': list,        # 付与されたスコープ
                'user_id': str,
                'expires_in': int      # 残り有効期間（秒）
            }
            トークンが無効な場合、None
        """
        if not access_token:
            logger.error("アクセストークンが空です")
            return None

        try:
            # ⚠️ 重要: validateでは oauth: 接頭辞を付けない
            # IRC用の PASS oauth:<token> とは異なる
            headers = {
                'Authorization': f'Bearer {access_token}'
            }

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.get(self.VALIDATE_URL, headers=headers, timeout=10)
            )

            if response.status_code == 200:
                validation_data = response.json()

                # スコープ検証（公式推奨）
                scopes = validation_data.get('scopes', [])

                # chat:read は必須
                if 'chat:read' not in scopes:
                    logger.error(
                        f"必須スコープ 'chat:read' がありません。"
                        f"現在のスコープ: {scopes}\n"
                        "再認証が必要です: python oauth_authenticator.py"
                    )
                    raise ValueError("必須スコープが不足しています")

                # chat:write の警告（将来拡張時の事故防止）
                if 'chat:write' not in scopes:
                    logger.warning(
                        f"スコープ 'chat:write' がありません。"
                        f"チャット送信機能を使用する場合は再認証が必要です。"
                    )

                logger.debug(
                    f"トークン検証成功: {validation_data['login']} "
                    f"(残り {validation_data['expires_in']}秒)"
                )

                return validation_data

            elif response.status_code == 401:
                # トークン無効（401エラー）
                logger.warning("トークンが無効です（401 Unauthorized）")
                return None

            else:
                logger.error(
                    f"トークン検証エラー: ステータス {response.status_code}\n"
                    f"レスポンス: {response.text}"
                )
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"トークン検証API呼び出しエラー: {e}")
            return None

        except Exception as e:
            logger.error(f"トークン検証で予期しないエラー: {e}", exc_info=True)
            return None

    async def refresh_access_token(
        self,
        refresh_token: str
    ) -> Dict[str, str]:
        """
        Refresh Tokenを使用してAccess Tokenを更新

        公式ドキュメント: 401エラー時に即座に実行（最優先）
        エンドポイント: POST https://id.twitch.tv/oauth2/token
        Content-Type: application/x-www-form-urlencoded

        ⚠️ 重要: 新しいrefresh_tokenも返されるため、両方を保存すること

        Args:
            refresh_token: Refresh Token（URLエンコード必須）

        Returns:
            新しいトークン情報:
            {
                'access_token': str,
                'refresh_token': str,  # ⚠️ 新しいrefresh_token（必ず保存）
                'scope': list,
                'token_type': str
            }

        Raises:
            ValueError: Refresh Tokenが無効な場合
        """
        if not refresh_token:
            raise ValueError(
                "Refresh Tokenが空です。\n"
                "再認証が必要です: python oauth_authenticator.py"
            )

        # マルチスレッド環境での競合を防ぐ（公式推奨）
        async with self._refresh_lock:
            try:
                logger.info("トークンをリフレッシュ中...")

                # ⚠️ URLエンコード必須（公式仕様）
                data = {
                    'grant_type': 'refresh_token',
                    'refresh_token': refresh_token,  # 自動的にURLエンコードされる
                    'client_id': self.client_id,
                    'client_secret': self.client_secret
                }

                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: requests.post(
                        self.TOKEN_URL,
                        data=data,
                        headers={'Content-Type': 'application/x-www-form-urlencoded'},
                        timeout=10
                    )
                )

                if response.status_code == 200:
                    tokens = response.json()

                    logger.info("トークンリフレッシュ成功")
                    logger.debug(f"  新しいAccess Token: {tokens['access_token'][:20]}...")
                    logger.debug(f"  新しいRefresh Token: {tokens['refresh_token'][:20]}...")

                    # .envファイルに保存
                    await self.update_env_file(
                        tokens['access_token'],
                        tokens['refresh_token']
                    )

                    return tokens

                elif response.status_code in [400, 401]:
                    # Refresh Token無効（パスワード変更 or アプリ切断）
                    error_data = response.json()
                    error_message = error_data.get('message', response.text)

                    raise ValueError(
                        f"Refresh Token無効: {error_message}\n\n"
                        "考えられる原因:\n"
                        "  - Twitchでアプリ接続を解除した\n"
                        "  - Twitchアカウントのパスワードを変更した\n"
                        "  - Refresh Tokenの有効期限切れ（Public client: 30日）\n\n"
                        "再認証が必要です: python oauth_authenticator.py"
                    )

                else:
                    raise ValueError(
                        f"トークンリフレッシュエラー: ステータス {response.status_code}\n"
                        f"レスポンス: {response.text}"
                    )

            except requests.exceptions.RequestException as e:
                logger.error(f"トークンリフレッシュAPI呼び出しエラー: {e}")
                raise ValueError(f"ネットワークエラー: {e}")

            except Exception as e:
                logger.error(f"トークンリフレッシュで予期しないエラー: {e}", exc_info=True)
                raise

    async def get_valid_access_token(
        self,
        current_access_token: str,
        current_refresh_token: str
    ) -> str:
        """
        有効なAccess Tokenを取得（必要に応じて自動リフレッシュ）

        優先度（公式準拠 + 監査反映）:
        1. 現在のトークンを検証
        2. 401エラー → 即リフレッシュ（最優先）
        3. 200成功 → expires_in < 600秒なら事前リフレッシュ（補助的）

        ⚠️ 注意: 公式は「期限値のみを根拠にした能動リフレッシュは推奨しない」
        そのため、401対応を最優先とし、期限前リフレッシュは補助的位置付け

        Args:
            current_access_token: 現在のAccess Token
            current_refresh_token: 現在のRefresh Token

        Returns:
            有効なAccess Token
        """
        # 1. 現在のトークンを検証
        validation = await self.validate_token(current_access_token)

        if validation is None:
            # 401エラー → 即リフレッシュ（最優先対応）
            logger.warning("トークン無効を検出（401）、即座にリフレッシュを実行...")
            new_tokens = await self.refresh_access_token(current_refresh_token)
            return new_tokens['access_token']

        # 2. 有効だが期限が近い → 事前リフレッシュ（補助的）
        expires_in = validation.get('expires_in', float('inf'))

        if expires_in < 600:  # 10分未満
            logger.info(
                f"トークン期限が残り{expires_in}秒のため、事前リフレッシュを実行..."
            )
            try:
                new_tokens = await self.refresh_access_token(current_refresh_token)
                return new_tokens['access_token']
            except Exception as e:
                # 事前リフレッシュ失敗時は現在のトークンを継続使用
                logger.warning(
                    f"事前リフレッシュ失敗（現在のトークンを継続使用）: {e}"
                )
                return current_access_token

        # 3. 問題なし → 現在のトークンを使用
        logger.debug(f"トークン有効（残り {expires_in}秒）")
        return current_access_token

    async def update_env_file(
        self,
        new_access_token: str,
        new_refresh_token: str
    ) -> None:
        """
        .envファイルにトークンを保存

        ⚠️ 重要: 新しいaccess_tokenと新しいrefresh_tokenの両方を保存

        Args:
            new_access_token: 新しいAccess Token
            new_refresh_token: 新しいRefresh Token（必ず保存）
        """
        try:
            # バックアップを作成
            if self.env_path.exists() and self.env_path.stat().st_size > 0:
                backup_path = self.env_path.with_suffix('.env.backup')
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: shutil.copy(self.env_path, backup_path)
                )
                logger.debug(f".envファイルのバックアップを作成: {backup_path}")

            # トークンを保存（両方とも保存することが重要）
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: [
                    set_key(str(self.env_path), 'TWITCH_ACCESS_TOKEN', new_access_token),
                    set_key(str(self.env_path), 'TWITCH_REFRESH_TOKEN', new_refresh_token)
                ]
            )

            # 環境変数を再読み込み
            load_dotenv(override=True)

            logger.info(f"トークンを.envファイルに保存しました: {self.env_path}")
            logger.debug(f"  Access Token: {new_access_token[:20]}...")
            logger.debug(f"  Refresh Token: {new_refresh_token[:20]}...")

        except Exception as e:
            logger.error(f".envファイル更新エラー: {e}", exc_info=True)
            raise


# 使用例
if __name__ == '__main__':
    import sys

    async def test_token_manager():
        """TokenManagerのテスト"""
        from config import Config

        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # 設定のバリデーション
        try:
            Config.validate()
        except ValueError as e:
            print(f"設定エラー: {e}")
            sys.exit(1)

        # TokenManager初期化
        token_manager = TokenManager(
            client_id=Config.TWITCH_CLIENT_ID,
            client_secret=Config.TWITCH_CLIENT_SECRET
        )

        # トークン検証
        print("\n=== トークン検証 ===")
        validation = await token_manager.validate_token(Config.TWITCH_ACCESS_TOKEN)

        if validation:
            print(f"✓ トークン有効")
            print(f"  ユーザー: {validation['login']}")
            print(f"  有効期限: {validation['expires_in']}秒")
            print(f"  スコープ: {validation['scopes']}")
        else:
            print("✗ トークン無効")

            # リフレッシュを試行
            if Config.TWITCH_REFRESH_TOKEN:
                print("\n=== トークンリフレッシュ ===")
                try:
                    new_tokens = await token_manager.refresh_access_token(
                        Config.TWITCH_REFRESH_TOKEN
                    )
                    print(f"✓ リフレッシュ成功")
                    print(f"  新しいAccess Token: {new_tokens['access_token'][:20]}...")
                except Exception as e:
                    print(f"✗ リフレッシュ失敗: {e}")
            else:
                print("Refresh Tokenが設定されていません")

    # テスト実行
    asyncio.run(test_token_manager())
