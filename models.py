"""
データモデル定義 - SQLAlchemyを使用したTwitchチャットデータベーススキーマ
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text, BigInteger, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

Base = declarative_base()


class Stream(Base):
    """配信情報テーブル"""
    __tablename__ = 'streams'

    stream_id = Column(String(50), primary_key=True, comment='Twitch配信ID')
    user_id = Column(String(50), nullable=False, comment='配信者のユーザーID')
    user_login = Column(String(100), nullable=False, comment='配信者のログイン名')
    user_name = Column(String(200), comment='配信者の表示名')
    game_id = Column(String(50), comment='ゲームID')
    game_name = Column(String(200), comment='ゲーム名')
    title = Column(String(500), comment='配信タイトル')
    viewer_count = Column(Integer, comment='視聴者数')
    language = Column(String(10), comment='配信言語')
    is_mature = Column(Boolean, default=False, comment='成人向けコンテンツか')
    started_at = Column(DateTime, comment='配信開始時刻')
    ended_at = Column(DateTime, comment='配信終了時刻')
    created_at = Column(DateTime, default=datetime.utcnow, comment='レコード作成時刻')
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='レコード更新時刻')

    __table_args__ = (
        Index('idx_streams_user_id', 'user_id'),
        Index('idx_streams_started_at', 'started_at'),
    )


class ChatMessage(Base):
    """チャットメッセージテーブル"""
    __tablename__ = 'chat_messages'

    id = Column(String(100), primary_key=True, comment='メッセージID')
    stream_id = Column(String(50), nullable=False, comment='配信ID')
    broadcaster_user_id = Column(String(50), nullable=False, comment='配信者のユーザーID')
    broadcaster_user_login = Column(String(100), comment='配信者のログイン名')
    broadcaster_user_name = Column(String(200), comment='配信者の表示名')
    chatter_user_id = Column(String(50), nullable=False, comment='投稿者のユーザーID')
    chatter_user_login = Column(String(100), comment='投稿者のログイン名')
    chatter_user_name = Column(String(200), comment='投稿者の表示名')
    message_text = Column(Text, comment='メッセージ本文')
    color = Column(String(20), comment='ユーザー名の色')
    # バッジ情報（JSON形式で保存）
    badges = Column(Text, comment='バッジ情報（JSON）')
    # チアー情報
    bits = Column(Integer, comment='Bits数')
    # メッセージタイプ情報
    message_type = Column(String(50), comment='メッセージタイプ')
    # フラグ
    is_subscriber = Column(Boolean, default=False, comment='サブスクライバーか')
    is_moderator = Column(Boolean, default=False, comment='モデレーターか')
    is_vip = Column(Boolean, default=False, comment='VIPか')
    is_first_message = Column(Boolean, default=False, comment='初回メッセージか')
    # タイムスタンプ
    sent_at = Column(DateTime, comment='送信時刻')
    created_at = Column(DateTime, default=datetime.utcnow, comment='レコード作成時刻')

    __table_args__ = (
        Index('idx_chat_stream_id', 'stream_id'),
        Index('idx_chat_chatter_user_id', 'chatter_user_id'),
        Index('idx_chat_broadcaster_user_id', 'broadcaster_user_id'),
        Index('idx_chat_sent_at', 'sent_at'),
    )


class MessageDeletedEvent(Base):
    """メッセージ削除イベントテーブル"""
    __tablename__ = 'message_deleted_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    stream_id = Column(String(50), comment='配信ID')
    broadcaster_user_id = Column(String(50), nullable=False, comment='配信者のユーザーID')
    broadcaster_user_login = Column(String(100), comment='配信者のログイン名')
    broadcaster_user_name = Column(String(200), comment='配信者の表示名')
    target_user_id = Column(String(50), nullable=True, comment='削除対象ユーザーID（IRCでは取得不可）')
    target_user_login = Column(String(100), comment='削除対象ユーザーのログイン名')
    target_user_name = Column(String(200), comment='削除対象ユーザーの表示名')
    message_id = Column(String(100), nullable=False, comment='削除されたメッセージID')
    message_text = Column(Text, comment='削除されたメッセージ本文')
    deleted_at = Column(DateTime, comment='削除時刻')
    created_at = Column(DateTime, default=datetime.utcnow, comment='レコード作成時刻')

    __table_args__ = (
        Index('idx_deleted_message_id', 'message_id'),
        Index('idx_deleted_stream_id', 'stream_id'),
        Index('idx_deleted_target_user_id', 'target_user_id'),
        Index('idx_deleted_at', 'deleted_at'),
    )


class UserBannedEvent(Base):
    """ユーザーBan/タイムアウトイベントテーブル"""
    __tablename__ = 'user_banned_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    stream_id = Column(String(50), comment='配信ID')
    broadcaster_user_id = Column(String(50), nullable=False, comment='配信者のユーザーID')
    broadcaster_user_login = Column(String(100), comment='配信者のログイン名')
    broadcaster_user_name = Column(String(200), comment='配信者の表示名')
    user_id = Column(String(50), nullable=False, comment='Ban/タイムアウト対象ユーザーID')
    user_login = Column(String(100), comment='対象ユーザーのログイン名')
    user_name = Column(String(200), comment='対象ユーザーの表示名')
    moderator_user_id = Column(String(50), comment='実行したモデレーターのユーザーID')
    moderator_user_login = Column(String(100), comment='実行したモデレーターのログイン名')
    moderator_user_name = Column(String(200), comment='実行したモデレーターの表示名')
    reason = Column(Text, comment='Ban/タイムアウトの理由')
    # Ban情報
    is_permanent = Column(Boolean, comment='永久Banか（False=タイムアウト）')
    ends_at = Column(DateTime, comment='タイムアウト終了時刻（一時Banの場合）')
    banned_at = Column(DateTime, comment='Ban/タイムアウト時刻')
    created_at = Column(DateTime, default=datetime.utcnow, comment='レコード作成時刻')

    __table_args__ = (
        Index('idx_banned_user_id', 'user_id'),
        Index('idx_banned_stream_id', 'stream_id'),
        Index('idx_banned_broadcaster_user_id', 'broadcaster_user_id'),
        Index('idx_banned_at', 'banned_at'),
    )


class UserUnbannedEvent(Base):
    """ユーザーUnbanイベントテーブル"""
    __tablename__ = 'user_unbanned_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    stream_id = Column(String(50), comment='配信ID')
    broadcaster_user_id = Column(String(50), nullable=False, comment='配信者のユーザーID')
    broadcaster_user_login = Column(String(100), comment='配信者のログイン名')
    broadcaster_user_name = Column(String(200), comment='配信者の表示名')
    user_id = Column(String(50), nullable=False, comment='Unban対象ユーザーID')
    user_login = Column(String(100), comment='対象ユーザーのログイン名')
    user_name = Column(String(200), comment='対象ユーザーの表示名')
    moderator_user_id = Column(String(50), comment='実行したモデレーターのユーザーID')
    moderator_user_login = Column(String(100), comment='実行したモデレーターのログイン名')
    moderator_user_name = Column(String(200), comment='実行したモデレーターの表示名')
    unbanned_at = Column(DateTime, comment='Unban時刻')
    created_at = Column(DateTime, default=datetime.utcnow, comment='レコード作成時刻')

    __table_args__ = (
        Index('idx_unbanned_user_id', 'user_id'),
        Index('idx_unbanned_stream_id', 'stream_id'),
        Index('idx_unbanned_at', 'unbanned_at'),
    )


class EventSubSession(Base):
    """EventSubセッション情報テーブル"""
    __tablename__ = 'eventsub_sessions'

    session_id = Column(String(100), primary_key=True, comment='セッションID')
    user_id = Column(String(50), comment='対象ユーザーID')
    connected_at = Column(DateTime, comment='接続時刻')
    disconnected_at = Column(DateTime, comment='切断時刻')
    is_active = Column(Boolean, default=True, comment='アクティブか')
    keepalive_timeout = Column(Integer, comment='Keepaliveタイムアウト（秒）')
    created_at = Column(DateTime, default=datetime.utcnow, comment='レコード作成時刻')
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='レコード更新時刻')

    __table_args__ = (
        Index('idx_session_user_id', 'user_id'),
        Index('idx_session_is_active', 'is_active'),
    )


def init_database(database_url: str):
    """データベースの初期化"""
    engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(engine, checkfirst=True)
    return engine


def get_session(engine):
    """セッションの取得"""
    Session = sessionmaker(bind=engine)
    return Session()


if __name__ == '__main__':
    # テスト用: データベースの初期化
    from config import Config
    engine = init_database(Config.DATABASE_URL)
    print(f"データベースが初期化されました: {Config.DATABASE_URL}")
    print("作成されたテーブル:")
    for table_name in Base.metadata.tables.keys():
        print(f"  - {table_name}")
