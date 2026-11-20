"""Phase 6.0 信息源注册 + 真实数据采集脚本。

直接通过 repository + collection_service 操作，避免启动 Sidecar。
所有源已预先验证 RSS/Atom 可达性和 feedparser 可解析。

用法:  PIH_DATA_DIR=<tmpdir> python scripts/phase6_seed_sources.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import traceback
from pathlib import Path

# 【关键】在 import Backend 之前设置 PIH_DATA_DIR，让整个后端使用临时 db
_tmpdir = Path(tempfile.mkdtemp(prefix="pih-phase6-"))
os.environ["PIH_DATA_DIR"] = str(_tmpdir)

# 让 Backend 包可导入
BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import database  # noqa: E402
from core.timeutil import utc_timestamp  # noqa: E402
from services.collection_service import CollectionService  # noqa: E402


NOW = utc_timestamp()
TMPDIR = _tmpdir
DB_PATH = _tmpdir / "pih.sqlite3"

# --- 预验证过的信息源清单 ---
SOURCES = [
    # 国际新闻
    ("BBC World", "news", "https://feeds.bbci.co.uk/news/world/rss.xml", "en", "BBC World News"),
    ("BBC Top Stories", "news", "https://feeds.bbci.co.uk/news/rss.xml", "en", "BBC Top Stories"),
    ("DW English", "news", "https://rss.dw.com/xml/rss-en-all", "en", "Deutsche Welle"),
    ("Al Jazeera", "news", "https://www.aljazeera.com/xml/rss/all.xml", "en", "Al Jazeera English"),
    ("France 24", "news", "https://www.france24.com/en/rss", "en", "France 24 English"),
    # 国内新闻
    ("中新网滚动新闻", "news_zh", "https://www.chinanews.com.cn/rss/scroll-news.xml", "zh", "中国新闻网滚动"),
    ("中新网国内", "news_zh", "https://www.chinanews.com.cn/rss/china.xml", "zh", "中国新闻网国内"),
    ("中新网国际", "news_zh", "https://www.chinanews.com.cn/rss/importnews.xml", "zh", "中国新闻网国际"),
    # 科技
    ("NIST News", "tech", "https://www.nist.gov/news-events/news/rss.xml", "en", "NIST Cybersecurity News"),
    ("NASA", "tech", "https://www.nasa.gov/feed/", "en", "NASA News Feed"),
    ("TechCrunch", "tech", "https://techcrunch.com/feed/", "en", "TechCrunch"),
    ("MIT Tech Review", "tech", "https://www.technologyreview.com/feed/", "en", "MIT Technology Review"),
    ("The Verge", "tech", "https://www.theverge.com/rss/index.xml", "en", "The Verge"),
    ("InfoQ CN", "tech_zh", "https://www.infoq.cn/feed", "zh", "InfoQ 中文站"),
    # 学术科研
    ("arXiv AI", "research", "https://rss.arxiv.org/rss/cs.AI", "en", "arXiv cs.AI"),
    ("arXiv ML", "research", "https://rss.arxiv.org/rss/cs.LG", "en", "arXiv cs.LG"),
    ("arXiv NLP", "research", "https://rss.arxiv.org/rss/cs.CL", "en", "arXiv cs.CL"),
]

# 运行时会把源写进自定义数据库，采集流程跑通后我们会把这个 db 作为真实数据集
# 交给 AI 分析 + 事件聚类，然后可以把文章合并进正式 db。
# 但这里用临时 db 做完整链路验证，然后再决定合并策略。


def run() -> int:
    from uuid import uuid4

    db_path = DB_PATH
    print(f"[1/5] 初始化数据库: {db_path}")
    status = database.initialize(db_path)
    print(f"      -> schema_version={status.schema_version}, status={status.status}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    # 建分类（直接 SQL）
    categories: dict[str, str] = {}
    for cat_key in sorted({s[1] for s in SOURCES}):
        cid = str(uuid4())
        conn.execute(
            "INSERT INTO source_categories (id,name,description,created_at,updated_at) VALUES (?,?,?,?,?)",
            (cid, cat_key, f"Phase 6: {cat_key}", NOW, NOW),
        )
        categories[cat_key] = cid
    conn.commit()
    print(f"[2/5] 分类: {list(categories.keys())}")

    # 注册信息源（直接 SQL 绕过 repo 验证）
    source_ids = []
    source_names = []
    for name, cat_key, url, lang, homepage in SOURCES:
        category_id = categories.get(cat_key)
        sid = str(uuid4())
        try:
            conn.execute(
                """INSERT INTO sources (
                    id, category_id, name, source_type, url, homepage_url,
                    description, language, country, fetch_interval_minutes,
                    enabled, health_status, priority, credibility_score,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, category_id, name, "rss", url, homepage,
                 f"Phase 6 source: {name}", lang, None, 30,
                 1, "unknown", 50, None,
                 NOW, NOW),
            )
            source_ids.append(sid)
            source_names.append(name)
            print(f"      + {name:20s} ({cat_key})")
        except Exception as e:
            print(f"      ! {name:20s} FAIL: {e}")
    conn.commit()
    print(f"[3/5] 注册 {len(source_ids)} 个源")

    # 执行采集 — create_job → run 同步采集
    print(f"[4/5] 执行真实采集...")
    svc = CollectionService()
    job = svc.create_job(trigger_type="manual", source_ids=source_ids)
    print(f"      job_id={job.id}, source scope={len(source_ids)}")
    # 直接同步跑 _execute_job（worker 是线程，我们要等完成）
    svc._execute_job(job.id)  # noqa: SLF001 — 脚本内直接调用
    conn.commit()

    # 统计文章
    count = conn.execute("SELECT COUNT(*) FROM articles WHERE deleted_at IS NULL").fetchone()[0]
    # Job/item 状态
    item_stats = conn.execute(
        """SELECT status, COUNT(*) FROM collection_job_items
           WHERE job_id = ? GROUP BY status""", (job.id,)
    ).fetchall()
    print(f"[5/5] 文章 {count} 篇；items by status: {dict((r[0], r[1]) for r in item_stats)}")

    # 失败列表
    failed = conn.execute(
        """SELECT source_id, error_message FROM collection_job_items
           WHERE job_id = ? AND status IN ('failed','http_error','invalid_feed','empty_feed')
           LIMIT 10""", (job.id,)
    ).fetchall()
    for f in failed:
        print(f"      ! src={f['source_id']}: {(f['error_message'] or '')[:80]}")
    by_source = conn.execute(
        """SELECT s.name, COUNT(a.id) as n
           FROM articles a JOIN sources s ON s.id = a.source_id
           WHERE a.deleted_at IS NULL
           GROUP BY s.name ORDER BY n DESC"""
    ).fetchall()
    print(f"[5/5] 结果: 共 {count} 篇有效文章")
    for row in by_source:
        print(f"      {row['name']:20s} : {row['n']}")

    conn.close()
    print(f"\n✅ DB 文件: {db_path}")
    print("   可以直接用 Python sqlite3 查看，也可以用 Backend 加载继续处理。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
