#!/usr/bin/env python3
"""
Twitch OAuth Authenticator - 初回認証用スクリプト

Authorization Code Grant Flowを使用してUser Access TokenとRefresh Tokenを取得します。
一度実行すれば、以降はRefresh Tokenで自動更新されます。

使用方法:
    python oauth_authenticator.py

実行後、ブラウザが開いてTwitch認証画面が表示されます。
承認すると、.envファイルにトークンが自動保存されます。
"""

import asyncio
import logging
import os
import secrets
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
from pathlib import Path
from typing import Optional, Dict, Any
import requests
from dotenv import load_dotenv, set_key

# .envファイルから環境変数を読み込む
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OAuthConfig:
    """OAuth認証設定"""
    CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
    CLIENT_SECRET = os.getenv('TWITCH_CLIENT_SECRET')
    REDIRECT_URI = 'http://localhost:3000/callback'
    SCOPES = ['chat:read']  # チャット読み取りのみ。送信も必要な場合は 'chat:write' を追加
    AUTHORIZE_URL = 'https://id.twitch.tv/oauth2/authorize'
    TOKEN_URL = 'https://id.twitch.tv/oauth2/token'


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """OAuth コールバックハンドラー"""

    auth_code: Optional[str] = None
    state_received: Optional[str] = None
    error: Optional[str] = None

    def do_GET(self):
        """GETリクエストハンドラー"""
        parsed_path = urlparse(self.path)

        if parsed_path.path == '/callback':
            # クエリパラメータを解析
            params = parse_qs(parsed_path.query)

            # エラーチェック
            if 'error' in params:
                OAuthCallbackHandler.error = params['error'][0]
                self.send_error_response(f"認証エラー: {OAuthCallbackHandler.error}")
                return

            # codeとstateを取得
            if 'code' in params and 'state' in params:
                OAuthCallbackHandler.auth_code = params['code'][0]
                OAuthCallbackHandler.state_received = params['state'][0]
                self.send_success_response()
            else:
                self.send_error_response("認証コードが見つかりません")
        else:
            self.send_error_response("無効なパス")

    def send_success_response(self):
        """成功レスポンスを送信"""
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>認証成功</title>
            <style>
                body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
                .success { color: green; font-size: 24px; margin: 20px; }
                .message { color: #333; font-size: 16px; }
            </style>
        </head>
        <body>
            <div class="success">✓ 認証成功</div>
            <div class="message">
                Twitch認証が完了しました。<br>
                このウィンドウを閉じて、ターミナルに戻ってください。
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode('utf-8'))

    def send_error_response(self, message: str):
        """エラーレスポンスを送信"""
        self.send_response(400)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>認証エラー</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; }}
                .error {{ color: red; font-size: 24px; margin: 20px; }}
                .message {{ color: #333; font-size: 16px; }}
            </style>
        </head>
        <body>
            <div class="error">✗ 認証エラー</div>
            <div class="message">{message}</div>
        </body>
        </html>
        """
        self.wfile.write(html.encode('utf-8'))

    def log_message(self, format, *args):
        """ログメッセージを抑制"""
        pass


class TwitchOAuthAuthenticator:
    """Twitch OAuth認証マネージャー"""

    def __init__(self):
        """初期化"""
        if not OAuthConfig.CLIENT_ID or not OAuthConfig.CLIENT_SECRET:
            raise ValueError(
                "TWITCH_CLIENT_IDとTWITCH_CLIENT_SECRETが.envファイルに設定されている必要があります。\n"
                ".env.exampleを参考に設定してください。"
            )

        self.client_id = OAuthConfig.CLIENT_ID
        self.client_secret = OAuthConfig.CLIENT_SECRET
        self.redirect_uri = OAuthConfig.REDIRECT_URI
        self.scopes = OAuthConfig.SCOPES

        # CSRF対策用のstateを生成（32文字のランダム文字列）
        self.state = secrets.token_urlsafe(32)

        logger.info("OAuth Authenticatorを初期化しました")

    def get_authorization_url(self) -> str:
        """
        認証URLを生成

        Returns:
            認証URL
        """
        params = {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(self.scopes),
            'state': self.state
        }

        url = f"{OAuthConfig.AUTHORIZE_URL}?{urlencode(params)}"
        return url

    def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """
        認証コードをトークンに交換

        Args:
            code: 認証コード

        Returns:
            トークン情報の辞書
            {
                'access_token': str,
                'refresh_token': str,
                'expires_in': int,
                'scope': list,
                'token_type': str
            }
        """
        logger.info("認証コードをトークンに交換中...")

        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': self.redirect_uri
        }

        try:
            response = requests.post(
                OAuthConfig.TOKEN_URL,
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            response.raise_for_status()

            tokens = response.json()
            logger.info("トークン取得成功")
            logger.info(f"  Access Token: {tokens['access_token'][:20]}...")
            logger.info(f"  Refresh Token: {tokens['refresh_token'][:20]}...")
            logger.info(f"  有効期限: {tokens['expires_in']}秒")
            logger.info(f"  スコープ: {tokens.get('scope', [])}")

            return tokens

        except requests.exceptions.RequestException as e:
            logger.error(f"トークン取得エラー: {e}")
            if hasattr(e.response, 'text'):
                logger.error(f"エラー詳細: {e.response.text}")
            raise

    def save_tokens_to_env(self, access_token: str, refresh_token: str) -> None:
        """
        トークンを.envファイルに保存

        Args:
            access_token: アクセストークン
            refresh_token: リフレッシュトークン
        """
        env_path = Path('.env')

        # .envファイルが存在しない場合は作成
        if not env_path.exists():
            logger.warning(".envファイルが存在しないため、新規作成します")
            env_path.touch()

        # バックアップを作成
        backup_path = Path('.env.backup')
        if env_path.exists() and env_path.stat().st_size > 0:
            import shutil
            shutil.copy(env_path, backup_path)
            logger.info(f".envファイルのバックアップを作成しました: {backup_path}")

        try:
            # トークンを保存
            set_key(str(env_path), 'TWITCH_ACCESS_TOKEN', access_token)
            set_key(str(env_path), 'TWITCH_REFRESH_TOKEN', refresh_token)

            logger.info(f"トークンを.envファイルに保存しました: {env_path}")

        except Exception as e:
            logger.error(f".envファイルへの保存に失敗しました: {e}")
            raise

    def start_local_server(self, port: int = 3000) -> tuple:
        """
        ローカルWebサーバーを起動してコールバックを待機

        Args:
            port: ポート番号

        Returns:
            (auth_code, state_received) のタプル
        """
        server_address = ('localhost', port)
        httpd = HTTPServer(server_address, OAuthCallbackHandler)

        logger.info(f"ローカルサーバーを起動しました: http://localhost:{port}")
        logger.info("Twitchの認証ページを開きます...")

        # 認証URLをブラウザで開く
        auth_url = self.get_authorization_url()
        logger.info(f"認証URL: {auth_url}")

        try:
            webbrowser.open(auth_url)
        except Exception as e:
            logger.warning(f"ブラウザを自動的に開けませんでした: {e}")
            logger.info(f"手動で以下のURLを開いてください:\n{auth_url}")

        # コールバックを待機（タイムアウト: 5分）
        logger.info("Twitchでの認証を待機中...")

        timeout = 300  # 5分
        for _ in range(timeout):
            httpd.handle_request()

            if OAuthCallbackHandler.auth_code:
                logger.info("認証コードを受信しました")
                return OAuthCallbackHandler.auth_code, OAuthCallbackHandler.state_received

            if OAuthCallbackHandler.error:
                raise ValueError(f"認証エラー: {OAuthCallbackHandler.error}")

        raise TimeoutError("認証タイムアウト（5分）")

    def authenticate(self) -> bool:
        """
        OAuth認証フローを実行

        Returns:
            成功した場合True
        """
        try:
            logger.info("=== Twitch OAuth認証を開始します ===")
            logger.info(f"スコープ: {', '.join(self.scopes)}")
            logger.info("")

            # ローカルサーバーを起動してコールバックを待機
            auth_code, state_received = self.start_local_server()

            # stateを検証（CSRF対策）
            if state_received != self.state:
                raise ValueError(
                    f"CSRF検証失敗: state不一致\n"
                    f"期待値: {self.state}\n"
                    f"受信値: {state_received}"
                )

            logger.info("CSRF検証成功")

            # 認証コードをトークンに交換
            tokens = self.exchange_code_for_tokens(auth_code)

            # トークンを.envファイルに保存
            self.save_tokens_to_env(
                tokens['access_token'],
                tokens['refresh_token']
            )

            logger.info("")
            logger.info("=== 認証完了 ===")
            logger.info("以下のコマンドでデーモンを起動できます:")
            logger.info("  python daemon.py")
            logger.info("")

            return True

        except Exception as e:
            logger.error(f"認証失敗: {e}", exc_info=True)
            return False


def main():
    """メイン関数"""
    print("=" * 60)
    print("Twitch Chat Collector - OAuth認証")
    print("=" * 60)
    print("")
    print("このスクリプトは初回認証用です。")
    print("Twitchでの承認後、トークンが.envファイルに自動保存されます。")
    print("")
    print("準備:")
    print("1. .envファイルにTWITCH_CLIENT_IDとTWITCH_CLIENT_SECRETを設定")
    print("2. Twitch Developer Consoleでリダイレクト URI を設定:")
    print("   http://localhost:3000/callback")
    print("")

    input("準備ができたらEnterキーを押してください...")
    print("")

    authenticator = TwitchOAuthAuthenticator()
    success = authenticator.authenticate()

    if success:
        print("")
        print("✓ 認証に成功しました！")
        print("")
    else:
        print("")
        print("✗ 認証に失敗しました。")
        print("エラーログを確認してください。")
        print("")
        exit(1)


if __name__ == '__main__':
    main()
