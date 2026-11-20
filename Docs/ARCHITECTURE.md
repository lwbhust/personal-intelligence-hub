# PIH 系统架构（Phase 0 基线）

- 文档版本：1.0
- 日期：2026-11-16
- 阶段状态：**Phase 0 = PASSED；Phase 1 = PASS WITH CONDITIONS；Phase 2 = PASS；Phase 3 = 已实现并验收（2026-11-16）**
- 唯一产品基线：[Personal_Intelligence_Hub_开发计划书与Agent执行规范](./Personal_Intelligence_Hub_开发计划书与Agent执行规范.docx)
- 配套契约：[API_CONTRACT.md](./API_CONTRACT.md)、[DATABASE_BASELINE.md](./DATABASE_BASELINE.md)
- 环境与模型证据：[ENVIRONMENT_AUDIT.md](./ENVIRONMENT_AUDIT.md)、[LOCAL_AI_AUDIT.md](./LOCAL_AI_AUDIT.md)
- 协作规范：[AGENT_TEAM.md](./AGENT_TEAM.md)、[AGENT_WORKFLOW.md](./AGENT_WORKFLOW.md)

> 本文件定义系统分层、进程模型、目录归属、Phase 0 边界、错误与安全策略，以及后续 Phase 的扩展点。
> 与实现冲突时，以本文件与两份契约文档为准；契约变更必须先更新文档并形成 ADR，再改代码。

---

## 1. 文档目的与当前现状

### 1.1 目的

1. 固化计划书第 3 章（技术架构与工程组织）在 Phase 0 的落地方式。
2. 明确 App、Sidecar、数据库三层之间的职责与禁止事项。
3. 明确 Phase 0 允许实现的范围，防止提前实现采集、AI、事件、评分、RAG 等后续能力。
4. 给出可验证的启动/握手/健康检查/退出时序与失败降级策略。
5. 为 Phase 1–7 预留接口边界，但不在 Phase 0 引入任何业务数据模型。

### 1.2 当前仓库现状（2026-11-16 核对，验收基提交 `ad1c403`）

- Git 已初始化，分支 `phase0/init`，3 个提交，受控文件 79 个，`git status --short` 无输出。
- 已存在 `App/`（SwiftUI App、`project.yml` 生成的 Xcode 工程、`PersonalIntelligenceHubTests` 单测 target）、`Backend/`（FastAPI Sidecar、SQLite 数据层与迁移）、`Scripts/`（构建/运行脚本）、`Tests/phase0_integration_check.sh`（68 项集成检查）、`Docs/`（架构、契约、审计、ADR、路线图、验收）。
- 本文描述的 Phase 0 结构已落地并经可复现命令验证：`pytest tests -q` 57 passed、集成检查 68 PASS / 0 FAIL、`xcodebuild test` 35 passed / 0 failures。
- 本文件第 6 章的 Phase 0 范围即当前实现边界；Phase 1 及以后的能力（采集、AI、事件、评分、RAG）均未实现，接口预留不等于实现。
- 阶段验收结论见 `Docs/PHASE_ACCEPTANCE.md`。

### 1.3 阶段门禁

- Phase 0 未 PASSED 之前，禁止 Phase 1 正式开发。
- 只有 architect 可基于 qa-security 的可复现证据发布 PASSED。
- 当前状态：Phase 0 已由 architect 基于提交 `ad1c403` 的证据判定 PASS（见 `Docs/PHASE_ACCEPTANCE.md`）；用户已于 2026-11-16 批准进入 Phase 1，但**仅授权 Stage 1.1 设计**，未创建业务表、未实现采集或检索。阶段范围裁决见 `Docs/PHASE1_ADR.md` ADR-0012。

### 1.4 后续阶段落地状态（2026-11-16）

| Phase | 实际落地 | 验收文档 |
|---|---|---|
| 2 多渠道采集 | `collectors/net_guard.py`、`feed_parser.py`、`normalize.py`；文章/任务/健康表与 API；调度与重试；SwiftUI 文章与任务页 | `PHASE2_ACCEPTANCE.md` |
| 3 本地 AI 分析 | `ai_engine/`（Provider、Prompt、Schema）；`services/ai_analysis_service.py`；`ai_*` 表与 `/api/v1/ai/*`；SwiftUI AI 页与文章分析 | `PHASE3_ACCEPTANCE.md` |

Phase 3 的进程模型不变：AI worker 与采集 worker 均在 Sidecar 内，各自独立线程；AI 只访问 `127.0.0.1:11434`，不新增出网通道；模型不可用只影响 AI 任务，不影响 `/health`、文章浏览与采集。

---

## 2. 架构原则与工程约束

计划书第 2.1 节的不可妥协原则，在工程上必须落成可检查的约束：

| 原则 | 工程约束（可检查） |
|---|---|
| Local-first | 业务数据默认写入 `~/Library/Application Support/PersonalIntelligenceHub/`；Phase 0 除 loopback 外无任何网络请求 |
| Source-first | 后续文章/事件/AI 结论必须带来源与证据字段；Phase 0 不建业务表，因此不产生无来源业务数据 |
| Event-centric | 事件是后续分析主体；Phase 0 不创建事件表、不实现事件逻辑 |
| AI-assisted | AI 只做语义判断，确定性规则负责可验证计算；模型调用只能经 Provider 层（Phase 3） |
| Explainable | 评分必须带分项、权重、算法版本、时间；Phase 0 不实现评分 |
| Reliable | 任务可恢复、异常可追踪、数据库可迁移与备份；Phase 0 建立迁移与健康检查基础 |
| User-controlled | 来源、主题、频率、模型、数据保留策略由用户控制；Phase 0 仅暴露真实状态，不提供假配置 |
| Truthful UI | 禁止 mock、静态假数据、假进度、假评分、占位按钮；所有状态必须来自真实进程/HTTP/DB 检查 |

---

## 3. 系统分层与职责边界

### 3.1 总体结构

对应计划书第 3 章 3.1/3.2。Phase 0 只实现图中实线部分；虚线部分为后续 Phase 预留，Phase 0 不得创建空壳实现。

```text
┌────────────────────────────────────────────────────────────┐
│ macOS App（Swift 6 / SwiftUI / 最低 macOS 14.0）            │
│  Features/*          页面与交互、状态呈现、错误与降级展示     │
│  Packages/PIHNetworking  HTTP 客户端、Token 持有、Base URL   │
└───────────────────────────┬────────────────────────────────┘
                            │ HTTP + JSON
                            │ 127.0.0.1:<随机端口> + Bearer Token
┌───────────────────────────▼────────────────────────────────┐
│ FastAPI Sidecar（Python 3.14 / uvicorn / 仅 127.0.0.1）      │
│  api/        路由、认证、统一错误、/health、结构化日志        │
│  database/   连接、PRAGMA、Migration、Repository（Phase 1）  │
│  collectors/ processors/ scheduler/          （Phase 2+）    │
│  ai_engine/ ranking_engine/ event_engine/    （Phase 3+）    │
│  search/                                     （Phase 5）     │
└───────────────┬──────────────────────────────┬─────────────┘
                │ sqlite3（标准库，无 ORM）      │ HTTP（Phase 3+）
┌───────────────▼──────────────────┐  ┌────────▼─────────────┐
│ SQLite（唯一权威业务数据源）       │  │ Ollama（本地模型）    │
│ Phase 0：schema_migrations/app_meta│  │ Phase 0 不调用        │
└──────────────────────────────────┘  └──────────────────────┘
```

### 3.2 分层职责与禁止事项

| 组件 | 职责 | Phase 0 状态 | 禁止事项 |
|---|---|---|---|
| SwiftUI App | 展示、交互、导航、状态管理、Sidecar 生命周期管理 | 最小窗口：真实展示 Sidecar/DB 健康状态 | 不直接抓网页、不直连 SQLite、不绕过后端写业务数据 |
| PIHNetworking | 统一 HTTP 调用、Token 注入、超时、错误映射 | 仅封装 `/health` | 不把 Token 写入文件/日志/UI；不使用 URL 查询参数传 Token |
| FastAPI Sidecar | API、认证、错误、日志、后续调度与编排 | 仅 `/health` 与进程生命周期 | 不对公网监听；不在业务模块散落模型调用；不返回敏感信息 |
| `Backend/api/**` | 路由、认证中间件、统一错误、请求 ID、日志配置 | 必须实现 | 不直接拼接 SQL；不把 DB 细节暴露给 App |
| `Backend/database/**` | 连接、PRAGMA、Migration、Repository（Phase 1）、事务 | 连接 + 迁移框架 + 2 张基础设施表 | 不由 UI/Collector 任意拼接 SQL；不设计业务表 |
| SQLite | 唯一权威业务状态与结构化数据 | 初始化与健康探测 | 不得由 UI 缓存充当第二权威数据源 |
| 本地文件目录 | 正文快照、图片缓存、导出、日志 | 仅数据目录与 DB 文件 | 不把大体积正文/二进制无约束塞入主表 |
| Ollama | 本地 LLM 与 Embedding | 不调用，仅环境审计取证 | 业务代码不得硬编码模型名或直连模型 |

### 3.3 Phase 0 唯一真实链路

```text
App 启动
  → 生成随机 Token
  → 以子进程启动 Sidecar（Token 仅经环境变量）
  → 读取 stdout 握手，获得随机端口
  → GET /health（Bearer Token，2 秒超时）
  → Sidecar 探测 SQLite（schema_version / 可用性）
  → App 展示真实 ready / degraded / failed 状态
  → App 退出时发送 SIGTERM，3 秒后 SIGKILL
```

除上述链路外，Phase 0 不存在文章、事件、AI、搜索、评分等任何数据流。

### 3.4 后续数据链路（不在 Phase 0 实现）

计划书第 5–8 章的完整链路为：

```text
采集 → 规范化 → 正文提取 → 去重 → 入库（provenance）
→ AI 分析（摘要/分类/实体/Embedding）→ 事件聚类
→ 可解释评分 → 搜索/RAG → 知识管理
```

该链路仅在 Phase 2 起逐段实现，且每段必须先有数据契约与验收标准。

---

## 4. 进程与生命周期模型

### 4.1 进程模型

| 进程 | 归属 | 启动者 | 生命周期 |
|---|---|---|---|
| `PersonalIntelligenceHub.app` | macos-developer | 用户 / Xcode（开发期） | 用户退出或崩溃 |
| Sidecar（`PIH_SIDECAR_READY` 报告 `pid`） | backend-developer | App 以子进程启动 | App 发送 SIGTERM 后退出；异常时被回收 |
| Ollama | 外部服务（非 App 管理） | 用户 | Phase 0 不纳入运行时契约 |

关键约束：

- Sidecar 只监听 `127.0.0.1`，端口由内核分配（`PIH_PORT=0`）。
- Token 由 App 每次启动生成，只存在于 App 与 Sidecar 内存中。
- App 是 Sidecar 的唯一管理者；不依赖 launchd 常驻。

### 4.2 启动时序

```text
App                                   OS / Sidecar
 │ 1. 生成 32 字节 Token（内存）          │
 │ 2. 组装环境变量                        │
 │    PIH_SIDECAR_TOKEN=<token>          │
 │    PIH_PORT=0                         │
 │    PIH_DATA_DIR=<可选，默认不注入>      │
 │    （PYTHONUNBUFFERED=1，开发期）       │
 │ 3. spawn 子进程（Token 不在 argv） ───→│
 │                                       │ 4. 校验 Token/端口/数据目录
 │                                       │    非法 → stderr 记录 → exit 2（无握手）
 │                                       │ 5. 创建数据目录（0700）
 │                                       │ 6. 打开 SQLite + PRAGMA
 │                                       │ 7. 执行 Migration（失败不杀死进程）
 │                                       │ 8. bind 127.0.0.1:0 取得实际端口
 │                                       │ 9. uvicorn startup 完成
 │ ←── stdout 单行握手（立即 flush） ─────│ 10. 打印 PIH_SIDECAR_READY {...}
 │ 11. 10 秒内读取首行并校验              │
 │ 12. 建立 Base URL                     │
 │ 13. GET /health（2 秒超时） ──────────→│
 │ ←── 200 ok / 200 degraded ────────────│
 │ 14. 进入 ready / degraded，每 5 秒轮询 │
```

时序硬约束：

1. 握手必须在 **socket 已绑定且 ASGI startup 完成之后** 输出，保证 App 收到握手后可立即请求 `/health`。
2. 数据库初始化在绑定端口之前完成；总启动预算与握手超时一致（10 秒）。
3. 数据库初始化失败 **不阻止** Sidecar 启动，`/health` 返回 `200 + degraded`，便于前端展示真实降级。
4. stdout 在 Phase 0 **只允许**输出握手行；日志一律写 stderr。

### 4.3 握手契约摘要

完整定义见 [API_CONTRACT.md](./API_CONTRACT.md) 第 4 章。

| 字段 | 约束 |
|---|---|
| 前缀 | `PIH_SIDECAR_READY` + 一个空格 |
| 内容 | 单行紧凑 JSON：`port`、`pid`、`service`、`version` |
| `service` | 固定 `pih-backend` |
| `version` | 固定 `0.1.0`（与 `/health` 一致） |
| 终止符 | `\n`，写完立即 flush |
| 超时 | App 从 spawn 起 10 秒 |

### 4.4 就绪判定

| 条件 | 判定 |
|---|---|
| 进程存活 + 握手合法 + `/health` 200 且 `status=ok` | `ready` |
| `/health` 200 且 `status=degraded` | `degraded`（可用但必须显示降级原因） |
| `/health` 401/404/5xx、响应非法、版本不兼容 | `failed`（契约违例，不得显示为正常） |
| 进程退出 / 握手超时 / 端口无法连接 | `offline` 或 `failed`（按是否已就绪区分） |

### 4.5 停止时序

```text
App 退出（用户关闭 / applicationWillTerminate / 显式重启）
  → 停止健康轮询
  → 向 Sidecar 发送 SIGTERM
  → Sidecar 停止接收请求、完成在途请求、关闭 DB 连接、exit 0
  → App 最多等待 3 秒
  → 未退出则 SIGKILL，并等待回收（避免僵尸进程）
  → 释放 Token 引用（进程退出即失效）
```

### 4.6 崩溃与孤儿进程回收

| 场景 | 机制 |
|---|---|
| App 正常退出 | App 主动 SIGTERM → 3 秒 → SIGKILL，并等待子进程退出 |
| App 崩溃 / 被强杀 | Sidecar 每 2 秒检查 `os.getppid()`；父进程消失（ppid 变为 1 或改变）后记录 `parent_lost` 并在 1 秒内优雅退出（最坏约 3 秒） |
| Sidecar 崩溃 | App 的 termination handler 捕获退出码/信号；展示真实原因；最多自动重启 1 次，随后需用户操作 |
| Sidecar 被 SIGKILL | 下次启动由 WAL 自动恢复；不得手工删除 `-wal/-shm` 文件 |

> 父进程看门狗是“App 崩溃时子进程必须被回收”的兜底机制，属于 Phase 0 必需实现，不新增环境变量。

### 4.7 App 状态机

| 状态 | 进入条件 | UI 必须展示 | 允许操作 |
|---|---|---|---|
| `launching` | 已 spawn，未收到握手 | 启动中、进程 PID | 取消/退出 |
| `ready` | 握手 + `/health` ok | 服务版本、运行时长、DB 状态、最近检查时间 | 刷新健康、重启 Sidecar |
| `degraded` | 握手 + `/health` degraded | `database.code`、`schema_version`、真实错误说明 | 刷新、重启、打开数据目录（只读提示） |
| `offline` | 连续 3 次健康检查失败 | 最近成功时间、失败次数、错误摘要 | 手动重试（真实重启） |
| `failed` | 启动失败 / 契约违例 / 进程异常退出 | 退出码或信号、协议错误、`X-Request-ID`、stderr 尾部（已过滤敏感信息） | 重试（重新生成 Token 并启动） |
| `stopping` | 用户退出/重启 | 正在停止 | 无 |

禁止把 `degraded` 或 `offline` 显示为“正常”；禁止用静态文本冒充状态。

### 4.8 启动与运行失败分支

| 场景 | 检测方式 | 处理 |
|---|---|---|
| 缺少 `PIH_SIDECAR_TOKEN` | Sidecar 启动校验 | stderr 记录 `startup_failed`（不含 Token）→ exit 2，无握手 |
| `PIH_PORT` 非法 | 启动校验 | exit 2，无握手 |
| `PIH_DATA_DIR` 非绝对路径 | 启动校验 | exit 2，无握手 |
| 端口绑定失败 | bind 异常 | stderr 记录错误码 → exit 3，无握手 |
| 握手超过 10 秒 | App 计时器 | SIGTERM → 3 秒 → SIGKILL，展示超时与 stderr 尾部 |
| 握手 JSON 非法 / `service` 不符 / 端口越界 | App 解析 | 视为启动失败，终止子进程，展示具体原因 |
| `pid` 与子进程 PID 不一致 | App 校验 | 视为启动失败（防端口串话） |
| `/health` 401 | App 检查 | 视为契约违例，停止轮询，提示认证失败（不回显 Token） |
| DB 不可用 | Sidecar 健康探测 | `/health` 200 degraded；App 显示 amber 与 `database.code` |
| 迁移失败 | 迁移执行器 | 记录 `migration_failed`；health `database_migration_failed`；不自动修复 |

---

## 5. 目录结构与文件归属

### 5.1 目标目录树

```text
Personal Intelligence Hub/
├── App/                                  # macos-developer
│   ├── project.yml                       # XcodeGen 唯一工程源
│   └── PersonalIntelligenceHub/          # Swift 源码（入口、Sidecar 管理、状态视图）
├── Packages/                             # macos-developer
│   ├── PIHCore/ PIHModels/ PIHDatabase/ PIHNetworking/ PIHCharts/ PIHComponents/
├── Features/                             # macos-developer
│   ├── Dashboard/ Discover/ Intelligence/ Events/ Reader/ Analytics/
│   ├── AIChat/ Knowledge/ Sources/ Topics/ Models/ Tasks/ Settings/
├── Backend/
│   ├── main.py                           # backend-developer
│   ├── api/                              # backend-developer：app/auth/errors/health/logging/config
│   ├── api/v1/                           # Phase 1：sources / source-categories 路由
│   ├── services/                         # Phase 1：业务服务层（校验、事务边界、错误映射）
│   ├── database/                         # data-engineer：connection/migrations/repositories
│   ├── collectors/ processors/ scheduler/ event_engine/ ranking_engine/ ai_engine/ search/  # Phase 2+
│   ├── requirements.txt / pyproject.toml # 共享文件，owner 由 architect 指定
│   └── tests/backend/ tests/data/ tests/ai/
├── Resources/
│   ├── prompts/ model_profiles/          # ai-engineer
│   └── source_presets/ category_presets/ # data-engineer
├── Scripts/                              # 共享目录，逐脚本指定 owner
├── Tests/                                # qa-security（独立测试与夹具）
├── Docs/                                 # architect / technical-writer
├── RuntimeData/                          # 本地运行数据，.gitignore，不入库
└── PersonalIntelligenceHub.xcodeproj/    # XcodeGen 生成物，不手工编辑
```

### 5.2 Phase 0 必需与后续创建

| 目录/文件 | Phase 0 | 说明 |
|---|---|---|
| `App/project.yml` + Swift 源码 | 必需 | 生成工程、构建运行最小 App |
| `Backend/main.py`、`Backend/api/**` | 必需 | 启动、认证、`/health`、错误、日志 |
| `Backend/database/**` | 必需 | 连接、PRAGMA、迁移运行器、`0001_init.sql` |
| `Backend/requirements.txt` / `pyproject.toml` + 锁文件 | 必需 | 依赖必须锁定版本 |
| `Scripts/**` | 必需（最小） | 生成工程、启动后端、运行测试 |
| `Backend/tests/**`、`Tests/**` | 必需 | 后端测试与 QA 独立验证 |
| `Packages/**`、`Features/**` | 按需 | 仅当 Phase 0 真实使用；禁止空壳 |
| `collectors/ processors/ ...` | 禁止 | Phase 2+ |
| `Resources/prompts/**` 等 | 禁止 | Phase 3+ |

### 5.3 文件归属

| 路径 | Owner | 其他 Agent |
|---|---|---|
| `Docs/ARCHITECTURE.md`、`Docs/API_CONTRACT.md`、`Docs/DATABASE_BASELINE.md`、`Docs/TECHNICAL_DECISIONS.md`、`Docs/DEVELOPMENT_ROADMAP.md`、`Docs/PHASE_ACCEPTANCE.md`、`Docs/AGENT_*.md` | architect | 只读 |
| `App/**`、`Packages/**`、`Features/**` | macos-developer | 只读 |
| `Backend/main.py`、`Backend/api/**`、`Backend/services/**`、`Backend/tests/backend/**` | backend-developer | 只读 |
| `Backend/database/**`（含 `repositories/**`）、`Backend/tests/data/**` | data-engineer | 只读 |
| `Backend/ai_engine/**`、`Backend/ranking_engine/**`、`Resources/prompts/**`、`Resources/model_profiles/**` | ai-engineer | 只读 |
| `Resources/source_presets/**`、`Resources/category_presets/**` | data-engineer | 只读 |
| `Tests/**`、`Docs/TEST_REPORT.md`、`Docs/SECURITY_REVIEW.md`、`Docs/PERFORMANCE_BASELINE.md` | qa-security | 只读 |
| `README.md`、`CHANGELOG.md`、其余 Docs | technical-writer | 只读 |

### 5.4 共享文件的唯一 Owner（由 architect 指定）

| 共享文件 | Phase 0 Owner | 规则 |
|---|---|---|
| `App/project.yml` | macos-developer | 工程唯一源；architect 审核构建配置 |
| `PersonalIntelligenceHub.xcodeproj/**` | XcodeGen 生成 | 不手工编辑；不入库或按团队约定统一生成 |
| `Backend/main.py` | backend-developer | 启动入口与生命周期 |
| `Backend/requirements*.txt` / `pyproject.toml` | backend-developer | 变更需 architect 批准；必须锁定版本 |
| `Backend/database/migrations/**` | data-engineer | 已应用迁移不可修改 |
| `Scripts/**` | 逐脚本指定：`generate_project.sh` → macos；`run_backend_dev.sh` → backend；`db_reset_dev.sh` → data | 脚本不得写 Token/绝对用户数据 |
| `Docs/contracts/**` | architect | 当前契约暂位于 `Docs/API_CONTRACT.md`；迁移位置需 ADR |

### 5.5 生成物与运行时数据

- `PersonalIntelligenceHub.xcodeproj` 由 `xcodegen --spec App/project.yml` 生成。
- 构建产物为 `PersonalIntelligenceHub.app`，最低部署目标 macOS 14.0，Swift 6 严格并发。
- 数据库与 WAL 文件写入 `~/Library/Application Support/PersonalIntelligenceHub/`，不得写入 App Bundle 或源码目录。
- `.venv/`、`build/`、`DerivedData/`、`*.sqlite3*`、`RuntimeData/`、模型缓存必须排除出版本库。

---

## 6. Phase 0 范围

### 6.1 必须交付（可验证）

| 领域 | 交付物 | 完成条件 |
|---|---|---|
| 工程 | XcodeGen 工程、SwiftUI 最小 App | `xcodebuild` 可构建并运行；窗口可显示真实状态 |
| Sidecar | `Backend/main.py` + FastAPI 应用 | 仅监听 127.0.0.1；随机端口；stdout 握手；SIGTERM 优雅退出 |
| 认证 | Bearer Token 校验 | 无/错 Token 返回 401 统一错误体；不回显 Token |
| 健康检查 | `GET /health` | 正常 `ok`、DB 异常 `degraded`，字段与契约一致 |
| 日志 | stderr 结构化 JSON | 含 `ts/level/event/request_id`；不记录 Token/Authorization/请求体 |
| 数据层 | 连接、PRAGMA、迁移运行器 | `0001_init.sql` 可应用；事务失败整体回滚 |
| 数据库 | 2 张基础设施表 | `schema_migrations`、`app_meta`；`schema_version=1` |
| 测试 | 后端与 Swift 单元测试 | 覆盖认证、健康、迁移、握手解析；真实执行输出 |
| 文档 | 本文件与两份契约 + 审计/路线图/验收文档 | 与实现一致，无未标注的未验证项 |

### 6.2 明确排除（Phase 0 不做）

- RSS/Atom/JSON Feed、网页抓取、GitHub、arXiv、调度器、来源健康监控。
- 正文提取、清洗、分类、摘要、关键词、实体识别、Embedding、RAG。
- 事件聚类、事件关系、时间线、重要性/热度/可信度评分、排行榜。
- FTS5、中文分词、向量检索、knowledge notes、bookmarks、annotations。
- 除 `/health` 外的任何业务 API。
- 业务数据库表（见 6.4）。
- 多实例运行、登录项常驻、自动更新、签名与公证、发布打包。
- 任何 mock、静态假数据、假进度、占位按钮、固定评分。

### 6.3 后续 Phase 的接口预留不等于实现

Phase 2+ 的目录与协议只在文档中预留。Phase 0 不得创建空类、空路由、空表、空 Prompt 或 TODO 占位 UI 来“表示已预留”。

### 6.4 边界声明：Phase 0 不设计业务表

> **Phase 0 不设计、不创建任何业务表。**
>
> 数据库仅允许存在 `schema_migrations` 与 `app_meta` 两张基础设施表。
>
> `sources`、`articles`、`article_ai_analysis`、`article_topics`、`article_entities`、`article_embeddings`、`events`、`event_articles`、`event_timeline`、`event_relations`、`event_entities`、`event_score_history`、`topics`、`entities`、`knowledge_notes`、`bookmarks`、`annotations`、`ai_runs`、`ai_conversations`、`ai_messages`、`ai_model_registry`、`collection_jobs`、`processing_jobs`、`user_preferences` 等全部属于 Phase 1 及以后，且须先由 data-engineer 提方案、architect 裁决并更新数据契约。
>
> 详细约束见 [DATABASE_BASELINE.md](./DATABASE_BASELINE.md)。

---

## 7. 错误与降级策略

### 7.1 统一错误模型

所有 HTTP 错误必须使用统一结构：

```json
{
  "error": {
    "code": "unauthorized",
    "message": "未授权：访问令牌缺失或无效"
  }
}
```

- `code` 为稳定英文 snake_case；`message` 为中文可读说明。
- 所有错误必须带服务端生成的 `X-Request-ID` 响应头。
- 不得返回堆栈、SQL、绝对路径、环境变量、主机名、Token。
- 详细定义与错误码表见 [API_CONTRACT.md](./API_CONTRACT.md) 第 7 章。

### 7.2 降级矩阵

| 依赖/故障 | 表现 | 系统行为 | App 呈现 |
|---|---|---|---|
| SQLite 无法打开/权限/磁盘错误 | 启动或探测异常 | `/health` 200 + `degraded`，`database.code=database_unavailable` | amber，展示错误码与请求 ID |
| SQLite 忙锁 | `busy_timeout` 超时 | `database.code=database_locked` | amber，提示稍后重试 |
| 迁移失败/校验和不一致 | 启动迁移异常 | `database.code=database_migration_failed` 或 `database_schema_error`；不自动改库 | amber/red，展示真实原因，禁止显示“正常” |
| Sidecar 未启动/崩溃 | 无连接或进程退出 | App 捕获退出码/信号 | `offline`/`failed`，提供真实重试 |
| Ollama 不可用 | Phase 0 不调用；Phase 3 起独立探测 | 不影响采集、浏览、搜索、阅读（后续） | Phase 3 起单独状态，不阻塞主界面 |
| 外网不可用 | Phase 0 无外网依赖 | 无影响 | 无 |
| Token 错误/缺失 | `/health` 401 | 停止轮询，视为契约违例 | 认证失败，禁止显示 Token |

### 7.3 日志与可观测性

- 结构化 JSON 单行写入 **stderr**；stdout 仅保留握手行。
- 必备字段：`ts`（UTC ISO8601，Z 结尾）、`level`、`event`、`request_id`（非请求事件用 `-`）。
- 可附加字段：`status_code`、`duration_ms`、`error_code`、`port`、`pid`、`path_kind`。
- 禁止记录：Token、`Authorization` 头、请求体全文、环境变量转储。
- 默认不记录绝对文件路径，使用 `path_kind` 区分数据位置类型。

### 7.4 Truthful UI 的落地

- Phase 0 至少真实覆盖 `launching / ready / degraded / offline / failed`。
- 错误视图必须展示：错误码、`X-Request-ID`（如有）、退出码/信号（如进程退出）、可重试动作。
- 重试按钮必须真实重启 Sidecar 并重新握手，不得只刷新静态文本。

---

## 8. 安全边界

### 8.1 网络边界

- Sidecar 仅绑定 `127.0.0.1`，禁止 `0.0.0.0`、`::`、局域网地址。
- App 的 Base URL 统一使用 `http://127.0.0.1:<port>`；禁止使用 `localhost` 或 `::1`，避免 DNS 解析差异与代理变量影响（审计发现 `no_proxy` 未覆盖 `::1`）。
- 端口由内核随机分配（`bind port 0`），不得使用固定端口作为默认。
- Phase 0 无任何外网请求；App 不依赖互联网即可运行。
- 不启用 CORS；Phase 0 关闭 `/docs`、`/redoc`、`/openapi.json`，避免未认证的路由信息暴露。
- 不使用代理头判断来源；不信任 `X-Forwarded-For`。

### 8.2 Token 边界

| 项目 | 规则 |
|---|---|
| 生成 | App 每次启动使用 `SecRandomCopyBytes`（或等效 CSPRNG）生成 32 字节，base64url 去 padding（43 字符，256 位熵） |
| 传递 | 仅通过子进程环境变量 `PIH_SIDECAR_TOKEN` |
| 存储 | 仅 App 与 Sidecar 内存；不写文件、UserDefaults、Keychain、URL、argv |
| 校验 | `Authorization: Bearer <token>`；常量时间比较（`hmac.compare_digest`） |
| 失败 | 缺失/格式错误/不匹配统一返回 401，不区分原因，不回显收到的值 |
| 生命周期 | 每次启动重新生成；无刷新/轮换接口；进程退出即失效 |

残余风险（必须如实记录）：同一用户下的其他进程可能通过进程检查/调试手段读取环境变量；本契约的威胁模型是“同机其他用户、浏览器跨域访问、意外日志泄漏”，不承诺防御同用户恶意进程。Token 不进入 argv 仍可显著降低 `ps` 泄漏面。

### 8.3 文件与数据边界

- 数据目录创建时权限 `0700`，数据库文件 `0600`（启动时设置 `umask 077`）。
- 不得写入 App Bundle、源码目录或共享临时目录。
- 备份、导出、日志不包含 Token。
- SQL 必须参数化；Phase 0 仅基础设施表操作，仍禁止字符串拼接 SQL。

### 8.4 输入与内容安全（为后续 Phase 预留）

- 网页、RSS、正文一律视为不可信输入；Phase 3 起必须防 Prompt Injection。
- 采集必须防 SSRF：限制协议、解析结果、重定向、响应体大小与类型（Phase 2）。
- 不执行采集内容中的命令/脚本；不绕过登录、付费墙、验证码或反爬。
- 上述规则在 Phase 0 不实现，但任何实现不得违反。

### 8.5 依赖与供应链

- Python 依赖锁定版本，优先纯 Python/有 3.14 wheel 的包。
- 引入新依赖需说明用途、许可证与替代方案；Phase 0 仅允许 FastAPI、uvicorn 及测试依赖。
- 不引入 ORM、向量数据库、云 SDK。

---

## 9. 可替换性设计

### 9.1 预留边界总览

| 边界 | 预留接口（Phase 落地） | Owner | 规则 |
|---|---|---|---|
| 数据访问 | Repository（Phase 1） | data-engineer | API 与业务模块只能经 Repository；禁止散落 SQL |
| AI 调用 | `BaseLLMProvider`（Phase 3） | ai-engineer | 业务只依赖 Provider；模型名与参数来自配置/注册表 |
| 采集 | `BaseCollector`（Phase 2） | backend-developer | `validate/fetch/normalize/health_check`；统一 Article DTO |
| 评分 | Ranking Engine（Phase 4） | ai-engineer | 分项、权重、算法版本、时间可追溯 |
| 检索 | FTS5 / 向量 Repository（Phase 5） | data-engineer | 先轻量本地方案；有实测证据才引入独立向量库 |

### 9.2 统一规则

1. 接口契约先于实现：新增边界必须先写契约或 ADR。
2. 禁止业务代码硬编码模型名、端口、Token、数据库路径。
3. 禁止 mock 进入生产路径；测试夹具必须与运行时数据目录隔离。
4. Phase 0 **不创建**上述接口的空实现；预留仅体现在文档与目录规划中。

### 9.3 AI Provider 的可替换性要求（Phase 3 前必须满足）

- 至少支持 `generate`、`generate_structured`、`embed`、`health_check`。
- 结构化输出必须经 JSON Schema 校验；解析失败有限重试后标记任务失败。
- 模型注册表记录模型名、版本、上下文长度、内存需求与实测结果。
- Ollama 不可用时，阅读与搜索不受影响；分析任务排队等待。

---

## 10. 后续 Phase 接口预留（方向性，未冻结）

以下仅为架构方向，**不构成 Phase 0 实现契约**。正式实现前必须更新 `Docs/API_CONTRACT.md`，涉及破坏性变更需 ADR。

| Phase | 能力 | 预期接口面（方向） | 数据边界 | 前置门禁 |
|---|---|---|---|---|
| 1 | 数据底座与来源管理 | `/api/v1/sources`、`/api/v1/source-categories` | Migration 0002+；Repository；备份实现；**不含采集器、文章入库、去重、FTS5** | Phase 0 PASSED + 用户批准（当前仅 Stage 1.1 设计） |
| 2 | 多渠道采集 | `/api/v1/articles`、采集任务与健康 | sources/articles/jobs；FTS 前的基础索引 | 数据契约冻结 |
| 3 | 本地 AI 分析 | `/api/v1/ai/status`、文章分析结果 | `article_ai_analysis`、`ai_runs`、模型注册表 | Provider 契约 + 模型实测 |
| 4 | 事件与排行 | `/api/v1/events`、`/api/v1/rankings` | 事件、证据、评分历史 | 评分算法 ADR |
| 5 | 搜索/RAG/知识 | `/api/v1/search`、`/api/v1/notes`、`/api/v1/chat` | FTS5、Embedding、引用证据 | 检索评测与引用规则 |
| 6 | 可视化驾驶舱 | `/api/v1/analytics` | 聚合查询与缓存策略 | 真实数据与性能基线 |
| 7 | 正式验收与发布 | 发布包、打包与签名 | 备份恢复、长期运行 | 全阶段证据齐备 |

### 10.1 Phase 0 关于 Ollama 状态的裁决边界

计划书 Phase 0 退出条件包含“Ollama 状态可检测”，但已冻结的 `/health` 契约不包含 Ollama 字段。

当前处理：

- Phase 0 的 Ollama 探测以 **独立诊断命令/脚本 + 审计证据** 完成（证据见 [LOCAL_AI_AUDIT.md](./LOCAL_AI_AUDIT.md)），不进入 Sidecar 运行时 API。
- **禁止**把 Ollama 字段塞入 `/health`，避免字段漂移。
- 若产品要求 App 内展示 Ollama 状态，必须先由 architect 修订 API 契约并新增独立端点（例如 `/api/v1/ai/status`，Phase 3 起），再实现。

---

## 11. 已知风险与缓解

| 风险 | 影响 | 缓解 | Owner |
|---|---|---|---|
| 本机满足 3.12+ 的版本为 Python 3.14.8（审计实测；另有 3.11.12/3.9.6 低于要求），计划书要求 3.12+ | FastAPI/uvicorn/pydantic 等依赖可能缺少 3.14 wheel 或存在行为差异 | 锁定实测通过版本；维护 `ENVIRONMENT_AUDIT.md`；启动冒烟测试 | backend-developer |
| stdout 被依赖库写入杂项输出 | App 首行握手解析失败，Sidecar 无法启动 | stdout 专用；日志强制 stderr；启动测试断言 stdout 仅一行 | backend-developer |
| App 崩溃导致孤儿进程 | 残留 Sidecar 占用端口/内存 | 父进程看门狗（2 秒轮询，1 秒内退出）+ 进程组测试 | backend-developer + macos-developer |
| XcodeGen 版本漂移（审计实测 2.46.0） | 工程生成结果不一致/构建失败 | 锁定版本；`Scripts/generate_project.sh` 显式检查 | macos-developer |
| macOS 14 最低版本与本机/CI 构建环境差异 | 构建或运行失败 | 环境审计记录 Xcode/SDK；部署目标固定 14.0 | macos-developer |
| ATS / App Sandbox 限制本地 HTTP 或子进程 | `/health` 请求被拦截或 Sidecar 无法启动 | 若实测被拦截，仅为 `127.0.0.1` 配置最小 ATS 例外与网络客户端 entitlement；禁止全局关闭 ATS | macos-developer |
| SQLite 单写者与锁竞争 | 后续高并发写失败 | WAL + `busy_timeout=5000` + 有界重试；Phase 4 做压力测试 | data-engineer |
| WAL 备份只拷贝主文件 | 备份丢失最近提交 | 备份必须用在线备份 API 或 `VACUUM INTO`；Phase 1 实现并演练 | data-engineer |
| Token 通过环境变量被同用户进程读取 | 本机同用户越权 | 威胁模型声明；不落盘不进日志；常量时间比较；随机端口 | backend-developer + qa-security |
| 发布打包未定义（系统 Python 依赖） | 发布版无法独立运行 | Phase 7 前完成打包 ADR；Phase 0 只验收开发构建 | architect |
| 多实例运行导致迁移竞争 | Schema 状态异常 | Phase 0 声明不支持多实例；启动迁移串行化；后续加锁 | data-engineer |

---

## 12. 决策、变更与验收

### 12.1 ADR 归档状态（正文见 `Docs/TECHNICAL_DECISIONS.md`）

| ADR | 主题 | 当前状态 |
|---|---|---|
| ADR-0001 | Python 3.14 作为本机唯一运行版本（vs 计划书 3.12+） | 已归档（见 TECHNICAL_DECISIONS.md） |
| ADR-0002 | XcodeGen 从 `App/project.yml` 生成工程 | 已归档（见 TECHNICAL_DECISIONS.md） |
| ADR-0003 | 每请求短连接 + WAL + `check_same_thread=True` | 已归档（见 TECHNICAL_DECISIONS.md） |
| ADR-0004 | stdout 单行握手 + 父进程看门狗的生命周期协议 | 已归档（见 TECHNICAL_DECISIONS.md） |
| ADR-0005 | Phase 0 仅 2 张基础设施表，业务表延后至 Phase 1 | 已归档（见 TECHNICAL_DECISIONS.md） |
| ADR-0006 | 端口发现只允许 stdout 握手（拒绝端口文件/固定端口/`lsof` 扫描） | 已归档（见 TECHNICAL_DECISIONS.md） |
| ADR-0007 | 后端目录采用 `Backend/{api,core,database}` 扁平结构 | 已归档（见 TECHNICAL_DECISIONS.md） |
| ADR-0008 | 标准库 `sqlite3` + 手写 Migration，不引入 ORM / Alembic | 已归档（见 TECHNICAL_DECISIONS.md） |
| ADR-0009 | Swift 单元测试 target 覆盖握手解析与健康模型解析 | 已归档（见 TECHNICAL_DECISIONS.md） |
| ADR-0010 | Ollama 模型分档策略（轻量/中等/高性能按需） | 已归档（Accepted，高性能档 Deferred） |
| ADR-0011 | API 契约存放于 `Docs/API_CONTRACT.md`，Phase 0 不建 `Docs/contracts/` | 已归档（见 TECHNICAL_DECISIONS.md） |
| ADR-0012 | Phase 1 范围裁决：数据底座 + 信息源管理，采集/去重/FTS5 留在 Phase 2/5 | Accepted（正文见 `PHASE1_ADR.md`） |
| ADR-0013 | macOS 14 保持最低支持目标；实机验证列为发布门禁 | Accepted（正文见 `PHASE1_ADR.md`） |
| ADR-0014 | Ollama 监听收敛至 `127.0.0.1`，云端模型不删除、不自动启用 | Accepted（执行前需依赖确认；正文见 `PHASE1_ADR.md`） |
| ADR-0015 | Phase 1 后端分层扩展：`api/v1` + `services` + `database/repositories` | Accepted（2026-11-16） |
| ADR-0016 | Phase 1 数据建模约定：UUID 主键、UTC ISO8601、软删除、部分唯一索引 | Accepted（2026-11-16） |
| ADR-0017 | Phase 1 建表范围收敛为 2 张表，其余延后 | Accepted（正文见 `PHASE1_ADR.md` §9） |
| ADR-0018–0026 | Phase 4：实体规范化、聚类算法与守卫、生命周期、关系、评分、unmerge 语义 | Accepted（正文见 `PHASE4_ADR.md`） |
| ADR-0027 | Phase 4 独立 QA 缺陷修复（不新增 Migration、分块审计、稳定态与评分语义） | Accepted（正文见 `PHASE4_ADR.md`） |

### 12.2 变更流程

1. 任何契约字段、错误码、环境变量、端口/Token 协议变更：architect 先更新文档。
2. 破坏性变更或核心选型变更：先写 ADR（背景、选项、决策、成本、迁移影响、验证结果）。
3. backend-developer 与 macos-developer 必须按同一份契约实现；契约测试由 qa-security 独立执行。
4. 文档与实现不一致时，以文档为准并回退实现；不得“先改代码再补文档”。

### 12.3 Phase 0 验收证据要求

| 验收项 | 证据 |
|---|---|
| App 可启动 | 构建命令与真实运行截图 |
| Sidecar 启动与握手 | stdout 首行、PID/端口、进程状态 |
| `/health` | 200 ok、200 degraded、401 的真实 curl 输出与 `X-Request-ID` |
| 数据库 | `schema_migrations` 记录、`app_meta` 表、PRAGMA 实测、迁移失败回滚测试 |
| 安全 | 仅 127.0.0.1 监听（`lsof`）、Token 不出现在日志/响应/argv、`/docs` 不可用 |
| Ollama 状态 | 独立诊断命令/审计证据（`LOCAL_AI_AUDIT.md`）；不进入 `/health` |
| 失败恢复 | App 崩溃后 Sidecar 回收、SIGTERM 3 秒退出、健康检查超时处理 |
| 文档一致性 | 三份文档字段/环境变量/端口/版本一致 |

最终结论由 architect 写入 `Docs/PHASE_ACCEPTANCE.md`。
