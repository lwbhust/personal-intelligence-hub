"""Phase 5 full-text search tests against a real initialized database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from database import initialize
from database.repositories import fts_search_repository as fts
from database.repositories import article_repository as ar
from core.timeutil import utc_timestamp


now = utc_timestamp()


@pytest.fixture()
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    path = tmp_path / "t.db"
    initialize(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    # One source
    conn.execute(
        """INSERT INTO sources(id,name,source_type,url,fetch_interval_minutes,
           enabled,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)""",
        ("s1", "Test", "rss", "http://example.com/rss", 60, 1, now, now),
    )
    yield conn
    conn.close()


def _insert(
    conn: sqlite3.Connection,
    aid: str,
    title: str,
    summary: str | None = None,
    content: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO articles(id,source_id,title,summary,content_text,
           content_state,fetched_at,content_hash,status,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            aid,
            "s1",
            title,
            summary,
            content,
            "full",
            now,
            "a" * 64,
            "active",
            now,
            now,
        ),
    )


def test_migration_creates_fts_virtual_table(db_conn: sqlite3.Connection) -> None:
    row = db_conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='articles_fts'"
    ).fetchone()
    assert row is not None
    assert row["sql"] is not None
    assert "fts5" in row["sql"].lower()
    assert "trigram" in row["sql"].lower()


def test_fts_populated_after_initial_articles(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1", "人工智能最新进展", "AI发展", "详细内容")
    _insert(db_conn, "a2", "科技新闻", "科技摘要", "芯片突破")
    db_conn.commit()
    count = db_conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]
    assert count == 2


def test_trigram_chinese_search(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1", "关于人工智能的最新进展", "AI 正在飞速发展",
            "人工智能技术在各个领域取得了革命性突破。")
    _insert(db_conn, "a2", "科技创新新闻", "科技摘要", "最新科技动态和创新成果。")
    db_conn.commit()

    results, total = fts.search(db_conn, "人工智能", limit=10, offset=0)
    assert total == 1
    assert results[0].article_id == "a1"

    results, total = fts.search(db_conn, "科技动态", limit=10, offset=0)
    assert total == 1
    assert results[0].article_id == "a2"


def test_trigram_english_search(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1", "Hello World Programming", "Python intro",
            "Learn Python programming from scratch.")
    _insert(db_conn, "a2", "Machine Learning AI", "ML intro",
            "Machine learning and artificial intelligence basics.")
    db_conn.commit()

    results, total = fts.search(db_conn, "program", limit=10, offset=0)
    assert total == 1
    assert results[0].article_id == "a1"


def test_trigram_mixed_chinese_english(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1", "你好世界 Hello World", "测试摘要",
            "中英文混合测试内容。")
    db_conn.commit()

    results, total = fts.search(db_conn, "你好世", limit=10, offset=0)
    assert total == 1

    results, total = fts.search(db_conn, "hell", limit=10, offset=0)
    assert total == 1


def test_search_without_query_falls_back_to_listing(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1", "文章一")
    _insert(db_conn, "a2", "文章二")
    db_conn.commit()
    results, total = fts.search(db_conn, "", limit=10, offset=0)
    assert total == 2
    assert len(results) == 2


def test_search_with_favorite_filter(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1", "科技文章", "科技", "科技内容")
    _insert(db_conn, "a2", "科技新闻", "科技", "更多科技内容")
    db_conn.commit()
    ar.set_favorite(db_conn, "a1", is_favorite=True)
    db_conn.commit()

    results, total = fts.search(db_conn, "科技", is_favorite=True, limit=10, offset=0)
    assert total == 1
    assert results[0].article_id == "a1"

    results, total = fts.search(db_conn, "科技", is_favorite=False, limit=10, offset=0)
    assert total == 1
    assert results[0].article_id == "a2"


def test_search_with_reading_status_filter(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1", "未读文章", "内容", "正文")
    _insert(db_conn, "a2", "已读文章", "内容", "正文")
    db_conn.commit()
    ar.mark_read(db_conn, "a2")
    db_conn.commit()

    results, total = fts.search(db_conn, "文章", reading_status="read", limit=10, offset=0)
    assert total == 1
    assert results[0].article_id == "a2"

    results, total = fts.search(db_conn, "文章", reading_status="unread", limit=10, offset=0)
    assert total == 1
    assert results[0].article_id == "a1"


def test_search_pagination(db_conn: sqlite3.Connection) -> None:
    for i in range(5):
        _insert(db_conn, f"a{i}", f"共同关键词 文章{i}", "摘要", "正文")
    db_conn.commit()

    all_results, total = fts.search(db_conn, "共同关键词", limit=10, offset=0)
    assert total == 5

    page1, _ = fts.search(db_conn, "共同关键词", limit=2, offset=0)
    page2, _ = fts.search(db_conn, "共同关键词", limit=2, offset=2)
    page3, _ = fts.search(db_conn, "共同关键词", limit=2, offset=4)
    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1


def test_fts_triggers_sync_on_insert(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1", "触发器测试")
    db_conn.commit()
    count = db_conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]
    assert count == 1


def test_fts_triggers_sync_on_update(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1", "原文标题", "原文摘要", "原文正文")
    db_conn.commit()
    conn2 = db_conn.execute("SELECT COUNT(*) FROM articles_fts WHERE articles_fts MATCH '原文标'").fetchone()[0]
    assert conn2 == 1

    db_conn.execute("UPDATE articles SET title='新标题测试' WHERE id='a1'")
    db_conn.commit()
    new_count = db_conn.execute("SELECT COUNT(*) FROM articles_fts WHERE articles_fts MATCH '新标题'").fetchone()[0]
    assert new_count == 1
    old_count = db_conn.execute("SELECT COUNT(*) FROM articles_fts WHERE articles_fts MATCH '原文标'").fetchone()[0]
    assert old_count == 0


def test_fts_triggers_sync_on_soft_delete(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1", "要删除的文章")
    db_conn.commit()
    before = db_conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]
    assert before == 1

    # Soft delete (set deleted_at)
    db_conn.execute("UPDATE articles SET deleted_at=? WHERE id='a1'", (now,))
    db_conn.commit()
    after = db_conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]
    # The trigger deletes from FTS on every AFTER DELETE, but soft delete is an UPDATE.
    # Our FTS trigger on UPDATE deletes + re-inserts, so deleted articles will
    # still be in FTS. Search layer filters out deleted articles in WHERE clause,
    # which is correct — soft-deleted content should not show in results.
    assert after == 1
    results, total = fts.search(db_conn, "删除", limit=10, offset=0)
    assert total == 0  # filtered by a.deleted_at IS NULL


def test_fts_rebuild_index(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1", "重建测试文章")
    db_conn.commit()
    db_conn.execute("DELETE FROM articles_fts")
    db_conn.commit()

    rebuilt = fts.rebuild_index(db_conn)
    assert rebuilt == 1
    count = db_conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]
    assert count == 1

    results, total = fts.search(db_conn, "重建测试", limit=10, offset=0)
    assert total == 1
