# PIH 数据库基线（Phase 0）

- 文档版本：1.0
- 日期：2026-11-16
- 适用范围：SQLite 文件布局、连接管理、PRAGMA、Migration、事务、错误处理、备份策略
- 状态：Phase 0 基线已冻结（实现必须逐条满足）
- 关联文档：[ARCHITECTURE.md](./ARCHITECTURE.md)、[API_CONTRACT.md](./API_CONTRACT.md)

> 本文件仅覆盖 Phase 0 数据基础设施。**Phase 0 不设计业务表**，业务表自 Phase 1 起引入。
> Schema 变更必须先更新本文件并新增 Migration；禁止手工改库后不写迁移脚本。
>
> **主键规则适用范围**
> - 计划书要求的“主键统一 UUID（TEXT）”适用于 **Phase 1 起的业务实体**。
> - Phase 0 的两张基础设施表按冻结契约使用自然键：`schema_migrations.version` 为 `INTEGER PRIMARY KEY`，`app_meta.key` 为 `TEXT PRIMARY KEY`；二者不是业务实体，不适用 UUID 规则。
> - Phase 1 业务表不得借用 `app_meta` 规避 UUID 主键要求。

---

## 1. 边界声明

### 1.1 Phase 0 允许的表

仅允许两张基础设施表：

1. `schema_migrations`：迁移版本记录。
2. `app_meta`：最小键值验证表，用于证明数据库可读写与迁移可用，不承载任何业务语义。

### 1.2 Phase 0 禁止的表

禁止创建 `sources`、`articles`、`article_ai_analysis`、`article_topics`、`article_entities`、`article_embeddings`、`events`、`event_articles`、`event_timeline`、`event_relations`、`event_entities`、`event_score_history`、`topics`、`entities`、`knowledge_notes`、`bookmarks`、`annotations`、`ai_runs`、`ai_conversations`、`ai_messages`、`ai_model_registry`、`collection_jobs`、`processing_jobs`、`user_preferences` 等任何业务表。

> **Phase 1 才会引入业务表。** 任何提前建表、建 FTS5 索引或设计业务字段的行为，均视为越界交付，必须回退。

### 1.3 技术选型

- SQLite 为唯一权威业务数据库。
- 使用 Python 标准库 `sqlite3`，**不引入 ORM**。
- 不使用独立向量数据库；向量方案（如 sqlite-vec）在后续 Phase 以实测证据决定。
- 数据库文件位于用户数据目录，不写入 App Bundle 或源码目录。

---

## 2. 数据库文件路径与目录约定

### 2.1 路径解析

| 条件 | 数据库文件路径 | `/health` 的 `path_kind` |
|---|---|---|
| 未设置 `PIH_DATA_DIR` | `~/Library/Application Support/PersonalIntelligenceHub/pih.sqlite3` | `application_support` |
| 显式设置 `PIH_DATA_DIR=<绝对路径>` | `<PIH_DATA_DIR>/pih.sqlite3` | `custom` |

规则：

- `PIH_DATA_DIR` 必须是绝对路径；不展开 `~`，不接受相对路径。
- 路径不得位于 `.app` Bundle 内部或源码目录；检测到此类路径时拒绝启动（退出码 `2`）。
- 符号链接必须解析为真实路径后再使用。
- App 默认不注入 `PIH_DATA_DIR`，由后端使用默认目录；只有用户显式自定义时才注入。
- `/health` 只暴露 `path_kind`，不暴露绝对路径。

### 2.2 目录布局

```text
~/Library/Application Support/PersonalIntelligenceHub/
├── pih.sqlite3          # 主数据库
├── pih.sqlite3-wal      # WAL 日志（运行时生成）
├── pih.sqlite3-shm      # 共享内存索引（运行时生成）
└── backups/             # Phase 1 起使用；Phase 0 不创建
```

- `-wal`/`-shm` 为运行时文件，不得手工删除；异常恢复由 SQLite 完成。
- `backups/` 在 Phase 0 仅保留约定，不创建、不写入。

### 2.3 权限

- 数据目录创建时权限 `0700`；数据库文件权限 `0600`。
- 后端启动时设置 `umask 077`，确保 SQLite 创建的文件不暴露给其他用户。
- 对已存在目录不静默修改权限；权限异常时记录 `warn`，若无法读写则报告 `database_unavailable`。

### 2.4 启动初始化顺序

1. 设置 `umask 077`。
2. 解析并校验数据库路径。
3. 创建数据目录（`0700`）。
4. 打开连接并设置 PRAGMA。
5. 创建 `schema_migrations`（bootstrap）。
6. 执行待应用 Migration。
7. 记录数据库状态（可用性、错误码、schema 版本、`path_kind`），供 `/health` 使用。
8. 关闭启动期连接。

数据库初始化失败不阻止 Sidecar 启动；`/health` 必须返回 `200 + degraded`。

---

## 3. 连接管理

### 3.1 总体策略：每次请求短连接

Phase 0 不使用连接池，也不维护全局长连接。每个数据库操作单元（请求、健康探测、迁移）独立建立连接并在 `finally` 中关闭。

理由：

- 避免跨线程共享连接对象，天然满足 `check_same_thread=True`。
- 避免长连接持有旧 schema/旧 WAL 状态。
- WAL 模式下打开连接开销低；Phase 0 请求量极小。
- 降低锁与事务边界不清导致的隐性错误。

Phase 1 之后如需连接池，必须有基准测试与 ADR，不得凭感觉引入。

### 3.2 线程模型与 `check_same_thread`

| 场景 | 规则 |
|---|---|
| 同步路由（`def`，FastAPI 在线程池执行） | 在路由函数内部创建连接，并在同一线程内使用、关闭 |
| 异步路由（`async def`） | 禁止在事件循环线程直接执行阻塞 SQLite 调用；使用 `asyncio.to_thread`/`anyio.to_thread`，**在线程内部创建连接** |
| 连接复用 | 禁止把一个连接从事件循环线程传到工作线程 |
| `check_same_thread` | 保持默认 `True`；不得为了“方便”设为 `False` 后跨线程共享 |
| 连接池（Phase 0） | 禁止 |

`sqlite3.Connection` 默认 `check_same_thread=True`，会在检测到跨线程使用时抛错。这是 Phase 0 的保护机制，而不是需要绕开的限制：只要每个线程创建并使用自己的连接，就无需关闭该检查。

### 3.3 连接工厂

```python
import sqlite3

def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(
        db_path,
        timeout=5.0,          # 与 busy_timeout 对齐
        isolation_level=None, # 自动提交；写操作显式 BEGIN IMMEDIATE
        check_same_thread=True,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn
```

要求：

- 连接必须在 `finally` 中关闭。
- PRAGMA 必须在任何事务开始前执行（`foreign_keys` 等不能在事务中切换）。
- 不得把游标或连接保存为模块级全局变量。
- 所有 SQL 使用参数绑定，禁止字符串拼接。
- `journal_mode=WAL` 在初始化阶段设置并验证（持久化设置）；连接工厂不重复切换。

### 3.4 健康探测连接

`/health` 的数据库探测必须满足 2 秒客户端超时，因此：

- 使用独立的短连接；
- 将该连接的 `busy_timeout` 临时设为 `500` ms（对常规连接 `5000` ms 的刻意例外）；
- 只执行 `SELECT 1` 与 `SELECT MAX(version) FROM schema_migrations`；
- 不执行 `integrity_check`、`VACUUM`、大表统计等重操作；
- 任何异常都转换为 `database.code`，HTTP 仍返回 `200`。

### 3.5 写并发与锁

- SQLite 同一时刻只允许一个写事务；Phase 0 的写操作仅发生在启动迁移。
- 写事务使用 `BEGIN IMMEDIATE`，尽早获得写锁，避免升级锁失败。
- `busy_timeout=5000` 允许等待写锁；超时后映射为 `database_locked`。
- 仅对 `database is locked`/`busy` 做有界重试（最多 2 次，带短退避）；不得重试语法/约束/IO 错误。

---

## 4. PRAGMA 配置与依据

### 4.1 配置清单

| PRAGMA | 值 | 作用域 | 依据 |
|---|---|---|---|
| `journal_mode` | `WAL` | 持久化（写入 DB 文件头） | 读写并发：读不阻塞写、写不阻塞读；适合本地 App 的“UI 轮询 + 后台写入”模式 |
| `foreign_keys` | `ON` | 每连接 | SQLite 默认关闭外键；必须每条连接显式开启，保证引用完整性 |
| `busy_timeout` | `5000` ms | 每连接 | 遇到写锁时等待而非立即失败；与 5 秒本地交互容忍度一致 |
| `synchronous` | `NORMAL` | 每连接 | WAL 模式下兼顾性能与一致性：应用崩溃不损坏数据库；极端断电可能丢失最近少量事务 |

### 4.2 WAL 适用性分析

适用理由：

- 数据目录位于本机 APFS，支持 WAL 所需的共享内存与文件锁。
- Phase 0 起就是“单进程、多线程、读多写少”的形态；后续 UI 轮询、健康检查、后台任务并存，WAL 可避免读被写阻塞。
- WAL 提供崩溃恢复能力，进程被 SIGKILL 后下次打开可自动恢复。

代价与限制：

- 运行时产生 `pih.sqlite3-wal` 与 `pih.sqlite3-shm`；备份与迁移必须把它们纳入考虑。
- 不适用于网络文件系统或不可靠文件锁；若 WAL 无法启用（`PRAGMA journal_mode=WAL` 返回值不是 `wal`），视为 `database_unavailable`，并记录错误。
- 默认 `wal_autocheckpoint=1000` 页；Phase 0 不调优，后续依据实测再定。
- WAL 模式下仍只有一个写者；高并发写必须串行化或排队，不能依赖 WAL 提升写并发。

### 4.3 `synchronous=NORMAL` 的真实语义

- 在 WAL 模式下，`NORMAL` 能保证应用崩溃/进程被杀后数据库一致。
- 操作系统崩溃或突然断电时，可能丢失最近已提交的少量事务，但不会产生损坏。
- Phase 0 接受该权衡；若后续要求“提交即持久化”，必须写 ADR 并评估 `FULL` 的性能代价。

### 4.4 验证方式

`journal_mode` 是持久化设置，可用 SQLite CLI 验证；其余三个是**连接级**设置，CLI 新连接不会继承后端设置，必须由后端测试断言或在启动日志中记录实际值。

```sql
-- 持久化设置，可用任意连接验证
PRAGMA journal_mode;   -- 期望 wal

-- 以下必须在后端连接上验证（CLI 新连接会显示默认值）
PRAGMA foreign_keys;   -- 期望 1
PRAGMA busy_timeout;   -- 期望 5000
PRAGMA synchronous;    -- 期望 1（NORMAL）
```

---

## 5. Migration 体系

### 5.1 目录与命名

- 目录：`Backend/database/migrations/`
- 命名：`NNNN_snake_case.sql`
  - `NNNN` 为 4 位零填充整数，从 `0001` 开始；
  - 版本号严格递增，不建议跳号；
  - 正则：`^[0-9]{4}_[a-z0-9_]+\.sql$`
- 编码：UTF-8，无 BOM，换行统一 LF。
- 一个迁移文件只做一个逻辑变更。
- **已应用的迁移文件不可修改**；修复必须新增更高版本迁移。

Phase 0 固定文件：`0001_init.sql`。

### 5.2 `schema_migrations` 的 Bootstrap

`schema_migrations` 由迁移运行器在应用任何版本化迁移之前创建，而不是由 `0001_init.sql` 创建。原因：它需要记录自身之后的迁移，避免自引用。

Bootstrap DDL（运行器执行）：

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    checksum   TEXT NOT NULL
);
```

### 5.3 迁移运行器算法

1. 校验数据目录与数据库路径。
2. 建立连接，设置连接级 PRAGMA。
3. 设置/验证 `journal_mode=WAL`。
4. 在独立事务中执行 bootstrap DDL（幂等）；bootstrap 只创建版本记录表，不属于业务 Schema 变更。
5. 读取 `schema_migrations` 全部记录，建立 `version -> checksum` 映射。
6. 扫描迁移目录，按版本排序；校验命名、重复版本、缺失文件。
7. 对每个已应用版本重新计算文件 checksum；不一致立即终止，报 `database_schema_error`。
8. 若数据库已应用版本高于程序内置的最高版本，终止并报 `database_schema_error`（禁止降级）。
9. 对每个待应用迁移：
   - `BEGIN IMMEDIATE`；
   - 执行迁移 SQL；
   - 在同一事务内写入 `schema_migrations(version, applied_at, checksum)`；
   - `COMMIT`。
10. 任一迁移失败：`ROLLBACK`，记录 `migration_failed`，停止后续迁移，`/health` 报 `database_migration_failed`。
11. 计算并记录 `schema_version = MAX(version)`（无记录时为 `0`）。
12. 关闭连接。

### 5.4 事务与 SQL 文件约束

- 迁移脚本内**禁止**出现 `BEGIN`、`COMMIT`、`ROLLBACK`；事务完全由运行器控制。
- 不得依赖 `sqlite3.executescript()` 的隐式提交行为。Phase 0 推荐在显式事务中逐条执行语句；若使用其他方式包装脚本，必须有“失败后完整回滚”的自动化测试证明。
- 迁移失败必须整体回滚，不得留下半成品表或部分记录。
- 运行器必须在异常路径执行 `ROLLBACK` 并关闭连接。

### 5.5 数据库状态判定

| 状态 | 判定 | 行为 |
|---|---|---|
| 全新数据库 | 无 `schema_migrations` 文件或表为空 | bootstrap + 应用全部迁移 |
| 已是最新 | 已应用版本 = 程序最高版本 | 不执行 SQL |
| 落后 | 已应用版本 < 程序最高版本 | 顺序应用待执行迁移 |
| 版本过高 | 已应用版本 > 程序最高版本 | 拒绝启动迁移，`database_schema_error` |
| 校验和不一致 | 已应用文件内容变化 | 拒绝执行，`database_schema_error`，不自动修复 |
| 缺少已应用文件 | DB 有记录但目录无文件 | `database_schema_error` |

### 5.6 并发与多实例

- Phase 0 假设只有一个 App 实例、一个 Sidecar 进程访问该数据库。
- 不支持多实例同时启动迁移；若发生，SQLite 锁只能作为最后防线，不保证迁移语义正确。
- 后续如需多实例，必须引入实例锁文件或单实例约束，并写 ADR。

---

## 6. `schema_migrations` 表结构

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    checksum   TEXT NOT NULL
);
```

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `version` | INTEGER | PRIMARY KEY | 从文件名解析的版本号，如 `0001` → `1` |
| `applied_at` | TEXT | NOT NULL | 实际提交时间，UTC ISO8601，`YYYY-MM-DDTHH:MM:SSZ` |
| `checksum` | TEXT | NOT NULL | 迁移文件原始字节的 SHA-256，小写十六进制（64 字符） |

规则：

- 每个版本只允许一行。
- `schema_version` 对外暴露为 `MAX(version)`；无记录时为 `0`。
- Phase 0 成功初始化后应存在且仅存在 `version=1` 的记录。
- 写入 `schema_migrations` 必须与迁移 SQL 处于同一事务。
- 不得手工插入/修改/删除记录来“修复”迁移状态。

---

## 7. Phase 0 最小表结构与迁移

### 7.1 `app_meta`

```sql
CREATE TABLE IF NOT EXISTS app_meta (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `key` | TEXT | PRIMARY KEY | 键名；Phase 0 不预置业务键 |
| `value` | TEXT | NOT NULL | 值；仅用于基础设施验证 |
| `updated_at` | TEXT | NOT NULL | 最后更新时间，UTC ISO8601，带 `Z` |

说明：

- `app_meta` 不承载业务配置、用户偏好或任何假数据。
- Phase 0 不强制写入任何行；测试可在临时数据库中写入并回滚以验证事务。
- 后续不得把 `app_meta` 当作业务配置表的替代品。

### 7.2 `0001_init.sql`

```sql
-- 0001_init.sql
-- Phase 0 infrastructure only.
-- Business tables are forbidden in Phase 0.

CREATE TABLE IF NOT EXISTS app_meta (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

运行器在该迁移成功后写入：

```text
schema_migrations(1, <applied_at>, <sha256-of-file>)
```

### 7.3 初始化完成后的预期状态

| 检查项 | 预期 |
|---|---|
| 表 | 仅 `schema_migrations`、`app_meta`（另含 SQLite 内部对象） |
| `schema_migrations` 行数 | `1` |
| `schema_version` | `1` |
| `app_meta` 行数 | `0`（Phase 0 不要求写入） |
| `PRAGMA journal_mode` | `wal` |
| `PRAGMA quick_check` | `ok` |
| `/health` | `status=ok`，`database.status=ok`，`schema_version=1` |

### 7.4 验证 SQL

```bash
DB="$HOME/Library/Application Support/PersonalIntelligenceHub/pih.sqlite3"

sqlite3 "$DB" ".tables"
sqlite3 "$DB" "SELECT version, applied_at, checksum FROM schema_migrations ORDER BY version;"
sqlite3 "$DB" "PRAGMA table_info(app_meta);"
sqlite3 "$DB" "PRAGMA journal_mode;"
sqlite3 "$DB" "PRAGMA quick_check;"
```

注意：`foreign_keys`、`busy_timeout`、`synchronous` 是连接级设置，上述 CLI 查询不代表后端连接的实际值，必须由后端测试断言。

---

## 8. 事务管理

### 8.1 基本规则

- `isolation_level=None`：关闭 Python 的隐式事务管理，所有事务显式控制。
- 读操作：自动提交，无需显式 `BEGIN`。
- 写操作：`BEGIN IMMEDIATE` → 执行 → `COMMIT`；异常时 `ROLLBACK`。
- 禁止在业务代码中嵌套事务；Phase 0 不支持 SAVEPOINT。
- 禁止跨请求持有事务。
- 事务内不得执行网络/AI 调用等长耗时操作。

### 8.2 迁移事务

- 每个迁移文件一个事务。
- 迁移 SQL 与 `schema_migrations` 插入必须原子提交。
- 失败回滚后，数据库应保持该迁移执行前的状态。

### 8.3 幂等与重试

- 迁移以版本号幂等：版本已存在则跳过。
- 写锁冲突可做有界重试；非锁错误不得重试。
- 后续任务系统需引入幂等任务键，Phase 0 不实现。

---

## 9. 异常处理与错误码

### 9.1 映射表

| 触发条件 | `database.code` | HTTP | 日志 |
|---|---|---|---|
| 无法打开文件、权限不足、磁盘 IO 错误、WAL 无法启用 | `database_unavailable` | `200` + degraded | `database_error`，含异常类型，不含路径 |
| 写锁等待超过 `busy_timeout` | `database_locked` | `200` + degraded | `database_error`，`error_code=database_locked` |
| 迁移执行失败并已回滚 | `database_migration_failed` | `200` + degraded | `migration_failed`，含版本号与异常类型 |
| 校验和不一致、数据库版本过高、缺失迁移文件、schema 不完整 | `database_schema_error` | `200` + degraded | `database_error`，含 `error_code` |
| 未预期异常（编程错误） | 不写入 `database.code` | `500` + `internal_error` | `request_error`，含 `request_id` |

### 9.2 处理原则

- 数据库异常不得返回 500 给健康检查；必须转成 `200 + degraded` 与稳定错误码。
- 不得在 HTTP 响应中返回堆栈、SQL、绝对路径、表数据。
- 日志可记录异常类型、迁移版本、`request_id`；不得记录 SQL 参数中的敏感内容（后续业务数据）。
- `sqlite3.IntegrityError` 在 Phase 0 仅可能来自测试；在后续业务 API 中映射为 `500 internal_error` 或明确的业务错误码，由契约决定。
- 连接必须在 `finally` 中关闭，异常路径不得泄漏文件句柄。

---

## 10. 备份策略（Phase 0 仅记录，不实现）

Phase 0 **不实现自动备份**，只固化策略，避免后续设计返工。

### 10.1 原则

- 备份必须在数据库一致状态下生成。
- 禁止在 WAL 活跃时只复制 `pih.sqlite3` 主文件；这会丢失最近的 WAL 事务。
- 使用 SQLite 在线备份 API（`sqlite3.Connection.backup`）或 `VACUUM INTO` 生成快照。
- 备份文件不得包含 Token（Token 本来也不在数据库中）。

### 10.2 Phase 1 计划的备份规则（待实现）

| 项目 | 计划 |
|---|---|
| 迁移前备份 | 每次启动执行迁移前生成 `backups/pih-<UTC时间戳>.sqlite3` |
| 定期备份 | 每日一次；保留最近 7 份 + 每周 4 份（具体保留策略在 Phase 1 确认） |
| 完整性校验 | 备份后执行 `PRAGMA integrity_check`，失败则标记备份无效 |
| 恢复演练 | 模拟删除/损坏主库，使用备份恢复并验证 `schema_migrations` 与数据 |
| 用户导出 | Phase 5 起支持 Markdown/JSON 导出，不等同于数据库备份 |

### 10.3 恢复步骤（Phase 1 执行）

1. 退出 App，确认 Sidecar 已停止。
2. 将 `pih.sqlite3`、`pih.sqlite3-wal`、`pih.sqlite3-shm` 移入隔离目录（不直接删除）。
3. 复制备份文件为 `pih.sqlite3`，设置权限 `0600`。
4. 启动后端，执行迁移检查与 `PRAGMA quick_check`。
5. 验证 `schema_version` 与关键数据后，再清理隔离目录。

---

## 11. 测试与验证

### 11.1 环境检查

```bash
Backend/.venv/bin/python -c "import sys, sqlite3; print(sys.version); print(sqlite3.sqlite_version)"
```

### 11.2 必测项

| 测试 | 方法 | 通过标准 |
|---|---|---|
| 全新初始化 | 使用空的临时 `PIH_DATA_DIR` 启动 | 生成 2 张表；`schema_version=1`；`/health` ok |
| 幂等重启 | 对同一目录再次启动 | 不重复应用 0001；版本仍为 1 |
| 校验和 | 修改已应用迁移文件后启动 | 报 `database_schema_error`，不执行迁移 |
| 失败回滚 | 在临时目录加入故意失败的迁移（不提交仓库） | 该版本无记录；无半成品表；`/health` degraded |
| 锁冲突 | 用另一连接持有写锁后请求 `/health` | 在超时内返回 `database_locked` |
| 权限 | 将临时数据目录设为不可写后启动 | 报 `database_unavailable`，进程仍可启动 |
| 文件权限 | 新建目录/数据库 | 目录 `0700`、文件 `0600` |
| WAL | `PRAGMA journal_mode` | `wal` |

### 11.3 后端连接级 PRAGMA 断言（必须由测试完成）

```python
from Backend.database.connection import connect

conn = connect(db_path)
assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
conn.close()
```

具体导入路径由 data-engineer 按实际模块确定，此处只约束断言内容。

---

## 12. Phase 1 才引入业务表

### 12.1 边界

- Phase 0 不设计字段、不建业务表、不建 FTS5、不建向量表。
- Phase 1 由 data-engineer 提出 Schema 方案，architect 裁决后写入数据契约与本文件的后续版本。
- Phase 1 迁移从 `0002_*.sql` 开始，禁止修改 `0001_init.sql`。

### 12.2 后续建模必须遵守的约束（方向性）

| 约束 | 要求 |
|---|---|
| 主键 | UUID，`TEXT` 存储 |
| 时间 | UTC ISO8601，`TEXT`，带 `Z`；UI 按用户时区展示 |
| 外键 | 每条连接开启 `foreign_keys=ON`；关键关系必须声明 |
| 去重 | 不得只依赖 `UNIQUE(source_id, external_id)`；需 canonical URL、内容指纹与跨来源策略 |
| 宽表 | 文章、AI 分析、事件、评分历史分表，不得混成宽表 |
| 原始正文 | 大体积正文/附件存本地文件目录，数据库保存引用与元数据 |
| 软删除 | 必须明确软删除与清理策略 |
| 索引 | 依据真实查询路径建立；禁止无依据堆索引 |
| FTS5 | 属于检索能力，Phase 5 正式实现；中文分词需单独验证 |
| 向量 | 先用轻量本地方案；有实测证据才引入独立向量库 |

### 12.3 Phase 1 前的门禁

1. Phase 0 PASSED。
2. 数据契约（表、字段、约束、迁移、回滚）评审通过。
3. 备份与恢复方案落地并能演练。
4. Repository 边界确定，禁止 API/Collector 直接拼接 SQL。

---

## 13. 变更流程

1. Schema 变更必须新增 Migration；已应用迁移不可修改。
2. 变更前更新本文件与相关数据契约，说明迁移影响与回滚方式。
3. 破坏性变更需 ADR（背景、选项、决策、成本、迁移影响、验证结果）。
4. 迁移前必须有可恢复的备份（Phase 1 起强制）。
5. qa-security 独立验证：全新安装、升级、失败回滚、锁冲突、重启一致性。

---

## 14. Phase 1 实施记录（2026-11-16）

Phase 1 按用户 C2 裁决只实现「数据底座 + 信息源管理」。详细设计见 `Docs/PHASE1_DATABASE_DESIGN.md`。

| 项目 | 实施结果 |
|---|---|
| 迁移 | `0002_source_categories.sql`、`0003_sources.sql`；`schema_version = 3` |
| 业务表 | `source_categories`、`sources`（共 2 张，符合 D1 逐表必要性裁决） |
| 延后表 | `source_health_logs`、`collection_jobs`（Phase 2）；`user_preferences`（有真实消费者时）；`processing_jobs`（Phase 3，依赖 articles） |
| 索引 | 6 个业务索引：2 个部分唯一（活动分类名、活动来源 URL）+ 4 个查询索引 |
| 软删除 | `deleted_at` + 部分唯一索引；分类删除同事务清空来源引用 |
| 主键/时间 | UUID TEXT；UTC ISO8601 毫秒 24 字符，DDL 断言长度 |
| 健康探测（DB-01） | `/health` 改为 `SELECT 1` + `MAX(version)`，不再执行 `quick_check` |
| 备份 | `database/backup.py` + `Scripts/backup_db.py` / `restore_db.py`；在线备份 API、`integrity_check`、元数据、7+4 保留、恢复前安全备份与失败回滚 |
| 备份演练 | **小规模真实测试已通过**（临时库，见 `Backend/tests/data/test_backup.py`）；**完整 ≥20 GiB 演练因磁盘不足未执行（DISK-01）** |
| 业务表边界 | 未创建 `articles`、`source_items`、FTS5、事件/AI 表 |

> 本节记录实际落地状态；与 §1.1 的 Phase 0 边界不冲突（Phase 0 的约束只在其阶段内生效）。

---

## 15. Phase 7.3.1 数据模型（2026-11-18）

Migration `0010_personalization.sql`；`schema_version = 10`。纯新增，不重建既有表。

| 表 | 关键约束 |
|---|---|
| `interest_profiles` | 单行（`id=1`）；日报时间 `HH:MM`、IANA 时区、每日条数 1–100、每日分钟 1–600、探索比例 0–0.5 |
| `interests` | 名称唯一；类型 `domain/topic/keyword/entity/source/event`；等级 `core/extended/general/muted`；权重 0–1 |
| `interest_keywords` | `(interest_id, keyword, is_exclusion)` 唯一；级联删除 |
| `interest_entity_links` | 兴趣 ↔ 既有 `entities`；`(interest_id, entity_id)` 唯一 |
| `interest_source_links` | 兴趣 ↔ 既有 `sources`；唯一 |
| `blocked_sources` | 全局屏蔽，主键 `source_id`（引用 sources，级联删除） |
| `recommendation_feedback` | 追加写 + `revoked_at` 软撤销；部分唯一索引保证每目标一条有效反馈 |
| `recommendation_results` | 每目标一条 `is_current=1`（部分唯一索引）；保存五维分数、理由、警告、`inputs_version`、`algorithm_version` |
| `daily_digests` | 每个 `(digest_date, timezone)` 一条 `succeeded`（部分唯一索引）；`superseded` 保留历史 |
| `daily_digest_items` | 级联删除；条目引用真实事件/文章 ID（无外键，避免跨表删除耦合） |

索引：兴趣等级、反馈时间/兴趣、推荐分数排行、日报日期、日报条目分区排序。

未新增任何人物/组织/产品表；实体匹配复用 `entities`，来源匹配复用 `sources`。
