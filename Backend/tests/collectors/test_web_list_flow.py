"""End-to-end tests for the HTML list adapter against a local HTTP server."""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import database
from collectors.html_list_collector import HtmlListCollector
from collectors.net_guard import NetGuard, NetPolicy
from core.timeutil import utc_timestamp
from database.repositories import adapter_repository as adapter_repo
from database.repositories import article_repository as article_repo
from database.repositories import source_repository as source_repo
from services.adapter_service import AdapterService
from services.collection_service import CollectionService

LIST_HTML = """<!doctype html><html><body>
<ul>
  <li><a href="/article/1">测试文章一：配电自动化与配网自愈</a></li>
  <li><a href="/article/2">测试文章二：电力通信与 SDH 网络</a></li>
</ul></body></html>"""

DETAILS = {
    "/article/1": """<!doctype html><html><head>
<meta property="og:title" content="测试文章一：配电自动化与配网自愈--测试站点">
<meta property="article:published_time" content="2026-11-18 10:00:00">
</head><body><div class="article_content">
""" + ("配电网自愈通过故障隔离与供电恢复提升可靠性。" * 30) + """
</div></body></html>""",
    "/article/2": """<!doctype html><html><head>
<meta property="og:title" content="测试文章二：电力通信与 SDH 网络">
<meta property="article:published_time" content="2026-11-18 09:30:00">
</head><body><div class="article_content">
""" + ("电力通信承载继电保护与调度自动化业务。" * 30) + """
</div></body></html>""",
}


LIST_PAGED_1 = """<!doctype html><html><body>
<a href="/article/3">测试文章三：储能与构网型技术</a>
<a href="/list-paged?page=2">下一页</a>
</body></html>"""

LIST_PAGED_2 = """<!doctype html><html><body>
<a href="/article/4">测试文章四：电力市场与现货交易</a>
</body></html>"""


def _detail(title: str, body: str) -> str:
    return f"""<!doctype html><html><head>
<meta property="og:title" content="{title}">
<meta property="article:published_time" content="2026-11-18 08:00:00">
</head><body><div class="article_content">{body * 30}</div></body></html>"""


DETAILS["/article/3"] = _detail("测试文章三：储能与构网型技术", "构网型储能支撑新能源并网稳定。")
DETAILS["/article/4"] = _detail("测试文章四：电力市场与现货交易", "电力现货市场与辅助服务机制。")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: C901
        if self.path == "/list":
            self._send(LIST_HTML.encode("utf-8"))
        elif self.path.startswith("/list-paged"):
            body = LIST_PAGED_2 if "page=2" in self.path else LIST_PAGED_1
            self._send(body.encode("utf-8"))
        elif self.path in DETAILS:
            self._send(DETAILS[self.path].encode("utf-8"))
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture()
def base_url() -> str:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture()
def data_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PIH_DATA_DIR", str(tmp_path / "data"))
    status = database.initialize()
    assert status.status == "ok"
    assert status.schema_version >= 12
    return tmp_path / "data"


@pytest.fixture()
def guard() -> NetGuard:
    return NetGuard(
        NetPolicy(
            allowed_ports=None,
            allow_loopback_for_tests=True,
            robots_enabled=False,
            total_timeout=5.0,
            read_timeout=2.0,
        )
    )


def _add_adapter_source(base_url: str, guard: NetGuard) -> str:
    source_id = str(uuid.uuid4())
    now = utc_timestamp()
    with database.session() as conn:
        source_repo.insert(
            conn,
            {
                "id": source_id,
                "category_id": None,
                "name": "网页适配器测试源",
                "source_type": "official_announcement",
                "url": base_url + "/list",
                "homepage_url": base_url,
                "description": "测试",
                "language": "zh",
                "country": "CN",
                "priority": 50,
                "credibility_score": 80,
                "fetch_interval_minutes": 60,
                "max_entries_per_fetch": None,
                "enabled": 1,
                "health_status": "unknown",
                "created_at": now,
                "updated_at": now,
            },
        )
        adapter_repo.upsert(
            conn,
            {
                "source_id": source_id,
                "adapter_type": "html_list",
                "entry_url": base_url + "/list",
                "config_json": json.dumps(
                    {
                        "list_urls": [base_url + "/list"],
                        "link_pattern": r"/article/\d+$",
                        "max_pages": 1,
                    }
                ),
                "config_version": "html-list-v1",
                "rate_limit_seconds": 1,
                "max_entries_per_run": 5,
                "fetch_full_text": 0,
                "last_verified_at": None,
                "last_verification": "unknown",
                "last_sample_json": None,
                "created_at": now,
                "updated_at": now,
            },
        )
    return source_id


def _articles() -> list:
    with database.read_session() as conn:
        return article_repo.list_articles(conn, limit=50, offset=0)[0]


def test_adapter_collects_and_dedupes(base_url: str, data_env: Path, guard: NetGuard) -> None:
    source_id = _add_adapter_source(base_url, guard)
    service = CollectionService(enabled=False, guard=guard)

    job = service.create_job(trigger_type="manual", source_ids=[source_id])
    service._execute_job(job.id)  # noqa: SLF001
    finished = service.get_job(job.id)

    assert finished.status == "succeeded"
    assert finished.inserted_count == 2
    assert finished.error_count == 0
    articles = {item.title: item for item in _articles()}
    assert set(articles) == {
        "测试文章一：配电自动化与配网自愈",
        "测试文章二：电力通信与 SDH 网络",
    }
    first = articles["测试文章一：配电自动化与配网自愈"]
    assert first.published_at == "2026-11-18T02:00:00.000Z"
    assert first.content_state == "summary_only"
    assert first.summary and len(first.summary) > 100

    # Retention soft-deletes old rows; a later run must not re-insert them.
    now = utc_timestamp()
    with database.session() as conn:
        for article in _articles():
            article_repo.update(
                conn, article.id, {"deleted_at": now, "updated_at": now}
            )
    assert _articles() == []

    second = service.create_job(trigger_type="manual", source_ids=[source_id])
    service._execute_job(second.id)  # noqa: SLF001
    repeat = service.get_job(second.id)
    assert repeat.inserted_count == 0
    assert repeat.duplicate_count == 2
    assert _articles() == []
    with database.read_session() as conn:
        adapter = adapter_repo.get(conn, source_id)
    assert adapter is not None and adapter.last_verification == "verified"
    service._item_pool.shutdown(wait=True, cancel_futures=True)


def test_adapter_follows_pagination(base_url: str, guard: NetGuard) -> None:
    result = HtmlListCollector(guard).collect(
        list_urls=[base_url + "/list-paged"],
        link_pattern=r"/article/\d+$",
        max_entries=5,
        rate_limit_seconds=0,
        fetch_full_text=False,
        max_pages=2,
    )
    titles = {entry.title for entry in result.entries}
    assert titles == {
        "测试文章三：储能与构网型技术",
        "测试文章四：电力市场与现货交易",
    }
    assert not result.errors


def test_adapter_dry_run_is_read_only(
    base_url: str, data_env: Path, guard: NetGuard
) -> None:
    source_id = _add_adapter_source(base_url, guard)
    result = AdapterService(guard=guard).dry_run(source_id, limit=2)

    assert len(result["entries"]) == 2
    assert result["suggestion"] == "verified"
    assert result["entries"][0]["published_at"].endswith("Z")
    assert _articles() == []
