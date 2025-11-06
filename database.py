"""
データベース操作モジュール - CRUD操作とヘルパー関数
"""
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from models import (
    Stream, ChatMessage, MessageDeletedEvent,
    UserBannedEvent, UserUnbannedEvent, EventSubSession,
    init_database, get_session
)

logger = logging.getLogger(__name__)


class DatabaseManager:
    """データベース操作マネージャー"""

    def __init__(self, database_url: str):
        self.engine = init_database(database_url)
        logger.info(f"データベースに接続しました: {database_url}")

    def get_session(self) -> Session:
        """新しいセッションを取得"""
        return get_session(self.engine)

    # Stream操作
    def save_stream(self, session: Session, stream_data: Dict[str, Any]) -> Stream:
        """配信情報を保存"""
        stream = session.query(Stream).filter_by(stream_id=stream_data['stream_id']).first()

        if stream:
            # 既存レコードを更新
            for key, value in stream_data.items():
                setattr(stream, key, value)
            stream.updated_at = datetime.utcnow()
            logger.debug(f"配信情報を更新: {stream_data['stream_id']}")
        else:
            # 新規レコードを作成
            stream = Stream(**stream_data)
            session.add(stream)
            logger.info(f"新しい配信を登録: {stream_data['stream_id']}")

        session.commit()
        return stream

    def get_stream(self, session: Session, stream_id: str) -> Optional[Stream]:
        """配信情報を取得"""
        return session.query(Stream).filter_by(stream_id=stream_id).first()

    def get_active_streams(self, session: Session) -> List[Stream]:
        """アクティブな配信一覧を取得（終了時刻が未設定）"""
        return session.query(Stream).filter(Stream.ended_at.is_(None)).all()

    # ChatMessage操作
    def save_chat_message(self, session: Session, message_data: Dict[str, Any]) -> ChatMessage:
        """チャットメッセージを保存（重複チェック付き）"""
        existing = session.query(ChatMessage).filter_by(id=message_data['id']).first()

        if existing:
            logger.debug(f"メッセージは既に保存済み: {message_data['id']}")
            return existing

        message = ChatMessage(**message_data)
        session.add(message)
        session.commit()
        logger.debug(f"新しいメッセージを保存: {message_data['id']}")
        return message

    def bulk_save_chat_messages(self, session: Session, messages_data: List[Dict[str, Any]]) -> int:
        """複数のチャットメッセージを一括保存"""
        if not messages_data:
            return 0

        # 既存のIDを取得
        message_ids = [msg['id'] for msg in messages_data]
        existing_ids = {
            m.id for m in session.query(ChatMessage.id).filter(ChatMessage.id.in_(message_ids)).all()
        }

        # 新規メッセージのみを追加
        new_messages = [
            ChatMessage(**msg_data)
            for msg_data in messages_data
            if msg_data['id'] not in existing_ids
        ]

        if new_messages:
            session.bulk_save_objects(new_messages)
            session.commit()
            logger.info(f"{len(new_messages)}件のメッセージを保存しました")

        return len(new_messages)

    def get_message_count_by_stream(self, session: Session, stream_id: str) -> int:
        """配信ごとのメッセージ数を取得"""
        return session.query(ChatMessage).filter_by(stream_id=stream_id).count()

    # MessageDeletedEvent操作
    def save_deleted_event(self, session: Session, event_data: Dict[str, Any]) -> MessageDeletedEvent:
        """メッセージ削除イベントを保存"""
        # 重複チェック（同じメッセージIDの削除イベントは1回のみ）
        existing = session.query(MessageDeletedEvent).filter_by(
            message_id=event_data['message_id']
        ).first()

        if existing:
            logger.debug(f"削除イベントは既に記録済み: {event_data['message_id']}")
            return existing

        event = MessageDeletedEvent(**event_data)
        session.add(event)
        session.commit()
        logger.info(f"削除イベントを保存: {event_data['message_id']}")
        return event

    def get_deleted_messages_by_stream(self, session: Session, stream_id: str) -> List[MessageDeletedEvent]:
        """配信ごとの削除メッセージ一覧を取得"""
        return session.query(MessageDeletedEvent).filter_by(stream_id=stream_id).all()

    # UserBannedEvent操作
    def save_banned_event(self, session: Session, event_data: Dict[str, Any]) -> UserBannedEvent:
        """ユーザーBan/タイムアウトイベントを保存"""
        event = UserBannedEvent(**event_data)
        session.add(event)
        session.commit()
        logger.info(f"Banイベントを保存: {event_data['user_id']}")
        return event

    def get_banned_users_by_stream(self, session: Session, stream_id: str) -> List[UserBannedEvent]:
        """配信ごとのBanユーザー一覧を取得"""
        return session.query(UserBannedEvent).filter_by(stream_id=stream_id).all()

    # UserUnbannedEvent操作
    def save_unbanned_event(self, session: Session, event_data: Dict[str, Any]) -> UserUnbannedEvent:
        """ユーザーUnbanイベントを保存"""
        event = UserUnbannedEvent(**event_data)
        session.add(event)
        session.commit()
        logger.info(f"Unbanイベントを保存: {event_data['user_id']}")
        return event

    # EventSubSession操作
    def save_eventsub_session(
        self,
        session: Session,
        session_id: str,
        user_id: Optional[str] = None,
        keepalive_timeout: Optional[int] = None
    ) -> EventSubSession:
        """EventSubセッション情報を保存"""
        eventsub_session = session.query(EventSubSession).filter_by(session_id=session_id).first()

        if eventsub_session:
            eventsub_session.updated_at = datetime.utcnow()
        else:
            eventsub_session = EventSubSession(
                session_id=session_id,
                user_id=user_id,
                connected_at=datetime.utcnow(),
                is_active=True,
                keepalive_timeout=keepalive_timeout
            )
            session.add(eventsub_session)

        session.commit()
        logger.info(f"EventSubセッションを保存: {session_id}")
        return eventsub_session

    def deactivate_eventsub_session(self, session: Session, session_id: str):
        """EventSubセッションを非アクティブ化"""
        eventsub_session = session.query(EventSubSession).filter_by(session_id=session_id).first()

        if eventsub_session:
            eventsub_session.is_active = False
            eventsub_session.disconnected_at = datetime.utcnow()
            session.commit()
            logger.info(f"EventSubセッションを非アクティブ化: {session_id}")

    def get_statistics(self, session: Session, stream_id: str) -> Dict[str, Any]:
        """配信の統計情報を取得"""
        message_count = self.get_message_count_by_stream(session, stream_id)
        deleted_events = self.get_deleted_messages_by_stream(session, stream_id)
        banned_events = self.get_banned_users_by_stream(session, stream_id)

        return {
            'stream_id': stream_id,
            'total_messages': message_count,
            'deleted_messages': len(deleted_events),
            'banned_users': len(banned_events)
        }


if __name__ == '__main__':
    # テスト用
    from config import Config
    import logging

    logging.basicConfig(level=logging.INFO)

    db_manager = DatabaseManager(Config.DATABASE_URL)
    session = db_manager.get_session()

    try:
        # テストデータの保存
        test_stream_data = {
            'stream_id': 'test123',
            'user_id': 'user123',
            'user_login': 'testuser',
            'user_name': 'Test User',
            'title': 'テスト配信',
            'started_at': datetime.utcnow()
        }

        stream = db_manager.save_stream(session, test_stream_data)
        print(f"配信を保存しました: {stream.stream_id}")

        # 統計情報の取得
        stats = db_manager.get_statistics(session, 'test123')
        print(f"統計情報: {stats}")

    finally:
        session.close()
