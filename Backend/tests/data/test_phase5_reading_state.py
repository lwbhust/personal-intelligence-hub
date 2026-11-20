"""Phase 5 reading state + favorite tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from database import initialize
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
    conn.execute(
        """INSERT INTO sources(id,name,source_type,url,fetch_interval_minutes,
           enabled,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)""",
        ("s1", "Test", "rss", "http://example.com/rss", 60, 1, now, now),
    )
    yield conn
    conn.close()


def _insert(conn: sqlite3.Connection, aid: str) -> None:
    conn.execute(
        """INSERT INTO articles(id,source_id,title,content_state,fetched_at,
           content_hash,status,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (aid, "s1", f"文章{aid}", "full", now, "a" * 64, "active", now, now),
    )


def test_default_reading_state_is_unread(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1")
    db_conn.commit()
    row = db_conn.execute(
        "SELECT reading_status, is_favorite FROM articles WHERE id='a1'"
    ).fetchone()
    assert row["reading_status"] == "unread"
    assert row["is_favorite"] == 0


def test_mark_read_sets_state_and_bumps_counter(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1")
    db_conn.commit()
    ar.mark_read(db_conn, "a1")
    db_conn.commit()
    row = db_conn.execute(
        "SELECT reading_status, read_count, last_read_at FROM articles WHERE id='a1'"
    ).fetchone()
    assert row["reading_status"] == "read"
    assert row["read_count"] == 1
    assert row["last_read_at"] is not None

    # Second read
    ar.mark_read(db_conn, "a1")
    db_conn.commit()
    row = db_conn.execute("SELECT read_count FROM articles WHERE id='a1'").fetchone()
    assert row["read_count"] == 2


def test_mark_later_and_back(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1")
    db_conn.commit()
    ar.mark_later(db_conn, "a1")
    db_conn.commit()
    row = db_conn.execute("SELECT reading_status FROM articles WHERE id='a1'").fetchone()
    assert row["reading_status"] == "later"

    ar.mark_unread(db_conn, "a1")
    db_conn.commit()
    row = db_conn.execute("SELECT reading_status FROM articles WHERE id='a1'").fetchone()
    assert row["reading_status"] == "unread"


def test_favorite_toggle(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1")
    db_conn.commit()
    ar.set_favorite(db_conn, "a1", is_favorite=True)
    db_conn.commit()
    row = db_conn.execute("SELECT is_favorite FROM articles WHERE id='a1'").fetchone()
    assert row["is_favorite"] == 1

    ar.set_favorite(db_conn, "a1", is_favorite=False)
    db_conn.commit()
    row = db_conn.execute("SELECT is_favorite FROM articles WHERE id='a1'").fetchone()
    assert row["is_favorite"] == 0


def test_combined_state_update(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1")
    db_conn.commit()
    ar.set_reading_state(db_conn, "a1", reading_status="later", is_favorite=True)
    db_conn.commit()
    row = db_conn.execute(
        "SELECT reading_status, is_favorite FROM articles WHERE id='a1'"
    ).fetchone()
    assert row["reading_status"] == "later"
    assert row["is_favorite"] == 1


def test_invalid_reading_status_rejected(db_conn: sqlite3.Connection) -> None:
    _insert(db_conn, "a1")
    db_conn.commit()
    with pytest.raises(ValueError):
        ar.set_reading_state(db_conn, "a1", reading_status="bogus")
    # State unchanged
    row = db_conn.execute("SELECT reading_status FROM articles WHERE id='a1'").fetchone()
    assert row["reading_status"] == "unread"


def test_batch_mark_read(db_conn: sqlite3.Connection) -> None:
    for i in range(3):
        _insert(db_conn, f"a{i}")
    db_conn.commit()
    n = ar.batch_set_reading_state(
        db_conn, ["a0", "a1"], reading_status="read"
    )
    db_conn.commit()
    assert n == 2
    counts = db_conn.execute(
        "SELECT reading_status FROM articles WHERE id IN ('a0','a1','a2') ORDER BY id"
    ).fetchall()
    assert counts[0][0] == "read"
    assert counts[1][0] == "read"
    assert counts[2][0] == "unread"  # a2 untouched


def test_batch_set_favorite(db_conn: sqlite3.Connection) -> None:
    for i in range(3):
        _insert(db_conn, f"a{i}")
    db_conn.commit()
    n = ar.batch_set_reading_state(db_conn, ["a0", "a2"], is_favorite=True)
    db_conn.commit()
    assert n == 2
    rows = db_conn.execute(
        "SELECT id, is_favorite FROM articles ORDER BY id"
    ).fetchall()
    favs = {r[0]: r[1] for r in rows}
    assert favs["a0"] == 1
    assert favs["a1"] == 0
    assert favs["a2"] == 1


def test_state_persists_after_conn_close_reopen(tmp_path: Path) -> None:
    path = tmp_path / "t.db"
    conn1 = sqlite3.connect(path)
    conn1.row_factory = sqlite3.Row
    conn1.execute("PRAGMA foreign_keys=ON")
    initialize(path)
    conn1.execute(
        """INSERT INTO sources(id,name,source_type,url,fetch_interval_minutes,
           enabled,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)""",
        ("s1", "Test", "rss", "http://example.com/rss", 60, 1, now, now),
    )
    conn1.execute(
        """INSERT INTO articles(id,source_id,title,content_state,fetched_at,
           content_hash,status,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ("a1", "s1", "持久化测试", "full", now, "a" * 64, "active", now, now),
    )
    ar.mark_read(conn1, "a1")
    ar.set_favorite(conn1, "a1", is_favorite=True)
    conn1.commit()
    conn1.close()

    # Reopen
    conn2 = sqlite3.connect(path)
    conn2.row_factory = sqlite3.Row
    conn2.execute("PRAGMA foreign_keys=ON")
    row = conn2.execute(
        "SELECT reading_status, is_favorite, read_count FROM articles WHERE id='a1'"
    ).fetchone()
    assert row["reading_status"] == "read"
    assert row["is_favorite"] == 1
    assert row["read_count"] == 1
    conn2.close()
