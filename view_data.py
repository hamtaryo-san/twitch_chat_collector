#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Twitch Chat Collector データ確認ツール

使い方:
  python view_data.py              # 統計情報を表示
  python view_data.py --sample     # サンプルデータも表示
  python view_data.py --all        # 全データを表示
  python view_data.py --export     # CSVにエクスポート
"""

import sys
import io
import argparse
from datetime import datetime
import csv
from pathlib import Path
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from config import Config
from models import Stream, ChatMessage, MessageDeletedEvent, UserBannedEvent, UserUnbannedEvent

# Windows環境でのエンコーディング問題を回避
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def get_db_session(database_url=None):
    """データベースセッションを取得"""
    database_url = database_url or Config.DATABASE_URL
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    return Session()


def get_db_stats(database_url=None):
    """データベースの統計情報を取得"""
    session = get_db_session(database_url)

    # 配信情報
    stream_count = session.query(func.count(Stream.stream_id)).scalar()

    # チャット数
    chat_count = session.query(func.count(ChatMessage.id)).scalar()

    # 削除イベント
    deleted_count = session.query(func.count(MessageDeletedEvent.id)).scalar()

    # BANイベント
    banned_count = session.query(func.count(UserBannedEvent.id)).scalar()

    # ユニークユーザー数
    unique_users = session.query(func.count(func.distinct(ChatMessage.chatter_user_id))).scalar()

    # サブスクライバーチャット数
    subscriber_chats = session.query(func.count(ChatMessage.id)).filter(ChatMessage.is_subscriber == True).scalar()

    # Bitsチャット数
    bits_count = session.query(func.count(ChatMessage.id)).filter(ChatMessage.bits != None).scalar()

    # 配信情報の詳細
    streams = session.query(
        Stream.stream_id,
        Stream.user_name,
        Stream.title,
        Stream.started_at,
        Stream.ended_at,
        Stream.game_name,
        Stream.viewer_count
    ).order_by(Stream.started_at.desc()).all()

    session.close()

    return {
        'stream_count': stream_count,
        'chat_count': chat_count,
        'deleted_count': deleted_count,
        'banned_count': banned_count,
        'unique_users': unique_users,
        'subscriber_chats': subscriber_chats,
        'bits_count': bits_count,
        'streams': streams
    }


def display_stats(stats):
    """統計情報を表示"""
    print("\n" + "="*60)
    print("Twitch Chat Collector - データ統計")
    print("="*60)

    print(f"\n[配信数] {stats['stream_count']}")

    if stats['streams']:
        print("\n配信情報:")
        for stream in stats['streams']:
            stream_id, user_name, title, started_at, ended_at, game_name, viewer_count = stream
            print(f"  - 配信者: {user_name}")
            print(f"    タイトル: {title}")
            print(f"    ゲーム: {game_name or '(未設定)'}")
            print(f"    視聴者数: {viewer_count or 'N/A'}")
            print(f"    開始時刻: {started_at}")
            if ended_at:
                print(f"    終了時刻: {ended_at}")
                duration = ended_at - started_at
                hours = duration.total_seconds() / 3600
                print(f"    配信時間: {hours:.1f}時間")
            else:
                print(f"    終了時刻: (配信中または未取得)")
            print(f"    Stream ID: {stream_id}")
            print()

    print(f"[総チャット数] {stats['chat_count']:,}")
    print(f"[ユニークユーザー数] {stats['unique_users']:,}")
    print(f"[サブスクライバーチャット数] {stats['subscriber_chats']:,}")
    print(f"[Bitsチャット数] {stats['bits_count']:,}")
    print(f"[削除イベント数] {stats['deleted_count']:,}")
    print(f"[BANイベント数] {stats['banned_count']:,}")
    print()


def display_sample_data(database_url=None, limit=10):
    """サンプルデータを表示"""
    session = get_db_session(database_url)

    print("="*60)
    print("最新のチャットメッセージ（10件）")
    print("="*60)

    messages = session.query(
        ChatMessage.chatter_user_name,
        ChatMessage.message_text,
        ChatMessage.is_subscriber,
        ChatMessage.is_moderator,
        ChatMessage.is_vip,
        ChatMessage.bits,
        ChatMessage.sent_at
    ).order_by(ChatMessage.sent_at.desc()).limit(limit).all()

    if len(messages) > 0:
        for msg in messages:
            chatter_user_name, message_text, is_subscriber, is_moderator, is_vip, bits, sent_at = msg
            print(f"\n[{sent_at}] {chatter_user_name}", end="")
            if is_subscriber:
                print(" [Sub]", end="")
            if is_moderator:
                print(" [Mod]", end="")
            if is_vip:
                print(" [VIP]", end="")
            if bits:
                print(f" [Bits: {bits}]", end="")
            print(f"\n  {message_text}")
    else:
        print("\nチャットデータがありません")

    print()
    session.close()


def display_all_data(database_url=None):
    """全データを表示"""
    session = get_db_session(database_url)

    messages = session.query(
        ChatMessage.chatter_user_name,
        ChatMessage.message_text,
        ChatMessage.is_subscriber,
        ChatMessage.is_moderator,
        ChatMessage.is_vip,
        ChatMessage.bits,
        ChatMessage.sent_at
    ).order_by(ChatMessage.sent_at.asc()).all()

    print("\n" + "="*60)
    print(f"全チャットメッセージ（{len(messages)}件）")
    print("="*60 + "\n")

    for msg in messages:
        chatter_user_name, message_text, is_subscriber, is_moderator, is_vip, bits, sent_at = msg
        print(f"[{sent_at}] {chatter_user_name}", end="")
        if is_subscriber:
            print(" [Sub]", end="")
        if is_moderator:
            print(" [Mod]", end="")
        if is_vip:
            print(" [VIP]", end="")
        if bits:
            print(f" [Bits: {bits}]", end="")
        print(f"\n  {message_text}\n")

    session.close()


def export_to_csv(database_url=None):
    """データをCSVにエクスポート"""
    session = get_db_session(database_url)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # チャットメッセージをエクスポート
    messages = session.query(ChatMessage).all()
    if len(messages) > 0:
        output_file = f'chat_messages_{timestamp}.csv'
        columns = [column.name for column in ChatMessage.__table__.columns]
        with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for msg in messages:
                row = [getattr(msg, col) for col in columns]
                writer.writerow(row)
        print(f"\n[OK] チャットデータを {output_file} にエクスポートしました")

    # 配信情報をエクスポート
    streams = session.query(Stream).all()
    if len(streams) > 0:
        streams_file = f'streams_{timestamp}.csv'
        columns = [column.name for column in Stream.__table__.columns]
        with open(streams_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for stream in streams:
                row = [getattr(stream, col) for col in columns]
                writer.writerow(row)
        print(f"[OK] 配信情報を {streams_file} にエクスポートしました")

    # 削除イベントをエクスポート（データがあれば）
    deleted_events = session.query(MessageDeletedEvent).all()
    if len(deleted_events) > 0:
        deleted_file = f'deleted_events_{timestamp}.csv'
        columns = [column.name for column in MessageDeletedEvent.__table__.columns]
        with open(deleted_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for event in deleted_events:
                row = [getattr(event, col) for col in columns]
                writer.writerow(row)
        print(f"[OK] 削除イベントを {deleted_file} にエクスポートしました")

    # BANイベントをエクスポート（データがあれば）
    banned_events = session.query(UserBannedEvent).all()
    if len(banned_events) > 0:
        banned_file = f'banned_events_{timestamp}.csv'
        columns = [column.name for column in UserBannedEvent.__table__.columns]
        with open(banned_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for event in banned_events:
                row = [getattr(event, col) for col in columns]
                writer.writerow(row)
        print(f"[OK] BANイベントを {banned_file} にエクスポートしました")

    # Unbanイベントをエクスポート（データがあれば）
    unbanned_events = session.query(UserUnbannedEvent).all()
    if len(unbanned_events) > 0:
        unbanned_file = f'unbanned_events_{timestamp}.csv'
        columns = [column.name for column in UserUnbannedEvent.__table__.columns]
        with open(unbanned_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for event in unbanned_events:
                row = [getattr(event, col) for col in columns]
                writer.writerow(row)
        print(f"[OK] Unbanイベントを {unbanned_file} にエクスポートしました")

    print()
    session.close()


def main():
    parser = argparse.ArgumentParser(
        description='Twitch Chat Collector データ確認ツール',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python view_data.py              # 統計情報を表示
  python view_data.py --sample     # サンプルデータも表示
  python view_data.py --all        # 全データを表示
  python view_data.py --export     # CSVにエクスポート
        """
    )

    parser.add_argument('--sample', '-s', action='store_true',
                        help='サンプルデータ（最新10件）を表示')
    parser.add_argument('--all', '-a', action='store_true',
                        help='全データを表示')
    parser.add_argument('--export', '-e', action='store_true',
                        help='データをCSVにエクスポート')

    args = parser.parse_args()

    # DATABASE_URLが設定されているか確認
    try:
        database_url = Config.DATABASE_URL
        if not database_url:
            print("\n[エラー] DATABASE_URLが設定されていません")
            print("  .envファイルでDATABASE_URLを設定してください")
            return
    except Exception as e:
        print(f"\n[エラー] 設定の読み込みに失敗しました: {e}")
        return

    # 統計情報は常に表示
    try:
        stats = get_db_stats(database_url)
        display_stats(stats)

        # オプションに応じて追加表示
        if args.sample:
            display_sample_data(database_url)

        if args.all:
            display_all_data(database_url)

        if args.export:
            export_to_csv(database_url)
    except Exception as e:
        print(f"\n[エラー] データベースに接続できません: {e}")
        print("  DATABASE_URLが正しいか確認してください")
        import traceback
        traceback.print_exc()
        return

    # オプションが何も指定されていない場合のヒント
    if not (args.sample or args.all or args.export):
        print("[ヒント]")
        print("  - サンプルデータを見る: python view_data.py --sample")
        print("  - 全データを見る: python view_data.py --all")
        print("  - CSVにエクスポート: python view_data.py --export")
        print()


if __name__ == '__main__':
    main()
