# PIH 技术决策记录（ADR）

- 文档版本：1.0
- 日期：2026-11-16
- 适用阶段：Phase 0（归档既有决策）～ Phase 7
- 唯一产品基线：[Personal_Intelligence_Hub_开发计划书与Agent执行规范](./Personal_Intelligence_Hub_开发计划书与Agent执行规范.docx)
- 关联文档：[ARCHITECTURE.md](./ARCHITECTURE.md)、[API_CONTRACT.md](./API_CONTRACT.md)、[DATABASE_BASELINE.md](./DATABASE_BASELINE.md)、[ENVIRONMENT_AUDIT.md](./ENVIRONMENT_AUDIT.md)、[LOCAL_AI_AUDIT.md](./LOCAL_AI_AUDIT.md)、[PHASE_ACCEPTANCE.md](./PHASE_ACCEPTANCE.md)

> **归档口径**
> 1. 本文件只记录**已经发生并可从仓库复现**的决策；未实施或未验证的内容必须显式写"未验证"，不得写成已验证。
> 2. 每条 ADR 的"验证结果"引用第 0 节证据基线（E1–E10）或给出具体文件路径；没有对应证据的写"未验证"。
> 3. ADR-0001…ADR-0005 对应 `ARCHITECTURE.md` §12.1 已冻结的 5 条决策；ADR-0006…ADR-0011 为 Phase 0 实施中形成的真实决策；ADR-0012…ADR-0016 为 Phase 1 决策，**正文见 [PHASE1_ADR.md](./PHASE1_ADR.md)**，本文件 §1 只登记索引。
> 4. 本文件不改变任何接口契约；契约变更仍以 `API_CONTRACT.md` / `DATABASE_BASELINE.md` 为准，且必须先更新契约再改代码。

---

## 0. 证据基线（2026-11-16 本机实测）

执行态：分支 `phase0/init`，HEAD `a27e430` + 工作树未提交修复（`Backend/main.py`、`App/.../BackendConfiguration.swift`）与未跟踪 `Tests/`。因此下列结果**只对本工作树成立**，尚不能由单个提交 SHA 复现（GIT-01）。

| ID | 命令 / 来源 | 实际结果 | 用于 |
|---|---|---|---|
| E1 | `python3 --version` | `Python 3.14.8` | ADR-0001 |
| E2 | `cd Backend && .venv/bin/python -m pytest tests -q` | `57 passed in 9.08s` | ADR-0001/0003/0008 |
| E3 | `.venv/bin/python -m pytest tests/backend -q` / `pytest tests/data -q` | `43 passed in 9.30s` / `14 passed in 0.12s` | ADR-0001/0003/0007/0008 |
| E4 | `bash Tests/phase0_integration_check.sh` | `PASS=68 FAIL=0` / `ALL CHECKS PASSED` | ADR-0003/0004/0005/0006/0007 |
| E5 | `.venv/bin/python -c "import fastapi, uvicorn, pydantic"` | `fastapi 0.163.1` / `uvicorn 0.54.0` / `pydantic 2.14.3` | ADR-0001 |
| E6 | `xcodegen --version`；`swift --version` | `2.46.0`；`Apple Swift 6.4.2` | ADR-0002 |
| E7 | `git ls-files \| grep -c xcodeproj`；`ls build/DerivedData/Build/Products/Debug/PersonalIntelligenceHub.app` | `0`；产物存在 | ADR-0002 |
| E8 | `sqlite3 --version` | `3.54.0` | ADR-0003/0008 |
| E9 | `ls Docs`；`git ls-files` | `API_CONTRACT.md` 存在、无 `Docs/contracts/`；`Backend/{main.py,api,core,database}` 扁平结构 | ADR-0007/0011 |
| E10 | [LOCAL_AI_AUDIT.md](./LOCAL_AI_AUDIT.md) §4.3 原始 `eval_count/eval_duration` | qwen3:1.7b 73.9–85.9 tok/s；gemma3:4b 37.6–37.7 tok/s；qwen3.5:4b-mlx 27.9 tok/s | ADR-0010 |
| E11 | `xcodegen generate --spec App/project.yml` + `xcodebuild test -scheme PersonalIntelligenceHub -derivedDataPath build/DerivedData -destination 'platform=macOS'` | `Executed 35 tests, with 0 failures` / `** TEST SUCCEEDED **` | ADR-0002/0009 |

> E10 为同日同机的真实推理实测，但**本轮未重跑推理**；引用时按"审计实测"标注，不当作本次复测结果。

---

## 1. ADR 索引

| ADR | 标题 | 状态 | ARCHITECTURE §12.1 已登记 |
|---|---|---|---|
| ADR-0001 | Python 3.14.8 作为本机唯一 Sidecar 运行版本（计划书为 3.12+） | Accepted | 是 |
| ADR-0002 | XcodeGen 从 `App/project.yml` 生成工程，`.xcodeproj` 不入库 | Accepted | 是 |
| ADR-0003 | 每请求短连接 + WAL + `check_same_thread=True` | Accepted | 是 |
| ADR-0004 | stdout 单行握手 + 父进程看门狗的生命周期协议 | Accepted | 是 |
| ADR-0005 | Phase 0 仅 2 张基础设施表，业务表延后至 Phase 1 | Accepted | 是 |
| ADR-0006 | 端口发现只允许 stdout 握手（拒绝端口文件 / 固定端口 / `lsof` 扫描） | Accepted | 是 |
| ADR-0007 | 后端目录采用 `Backend/{api,core,database}` 扁平结构 | Accepted | 是 |
| ADR-0008 | 标准库 `sqlite3` + 手写 Migration，不引入 ORM / Alembic | Accepted | 是 |
| ADR-0009 | Swift 单元测试 target 覆盖握手解析与健康模型解析 | Accepted | 是 |
| ADR-0010 | Ollama 模型分档策略（轻量 / 中等 / 高性能按需） | Accepted（高性能档 Deferred） | 是 |
| ADR-0011 | API 契约存放于 `Docs/API_CONTRACT.md`，Phase 0 不建 `Docs/contracts/` | Accepted | 是 |
| ADR-0012 | Phase 1 范围裁决：数据底座 + 信息源管理，采集/去重/FTS5 留在 Phase 2/5 | Accepted（2026-11-16 用户批准 C2） | 是（正文见 `PHASE1_ADR.md`） |
| ADR-0013 | macOS 14 保持最低支持目标；实机验证列为发布门禁 | Accepted（用户批准 C4） | 是（同上） |
| ADR-0014 | Ollama 监听收敛至 `127.0.0.1`，云端模型不删除、不自动启用 | Accepted（用户批准 C5，执行前需依赖确认） | 是（同上） |
| ADR-0015 | Phase 1 后端分层扩展：`api/v1` + `services` + `database/repositories` | Accepted（2026-11-16 实现并测试） | 是（同上） |
| ADR-0016 | Phase 1 数据建模约定：UUID 主键、UTC ISO8601、软删除、部分唯一索引 | Accepted（2026-11-16 实现并测试） | 是（同上） |
| ADR-0017 | Phase 1 建表范围收敛为 2 张表（分类 + 信息源），其余延后 | Accepted（用户 D1 授权） | 是（正文见 `PHASE1_ADR.md` §9） |

---

## 2. ADR 正文

### ADR-0001 Python 3.14.8 作为本机唯一 Sidecar 运行版本

| 项 | 内容 |
|---|---|
| 编号 | ADR-0001 |
| 日期 | 2026-11-16 |
| 状态 | **Accepted** |

**背景与约束**

- 计划书第 3 章要求 `Python 3.12+ + FastAPI` 本地 Sidecar；`Backend/pyproject.toml` 声明 `requires-python = ">=3.12"`。
- 本机解释器实测（[ENVIRONMENT_AUDIT.md](./ENVIRONMENT_AUDIT.md) §5.2）：`python3` = 3.14.8（Homebrew `python@3.14`）、`python3.11` = 3.11.12（低于下限）、系统 `/usr/bin/python3` = 3.9.6；**未安装 3.12 / 3.13**。
- 磁盘可用仅约 11 GiB（RISK-01），新增解释器与依赖需要额外空间。
- 必须隔离依赖，不得污染系统 Python。

**候选方案**

| 方案 | 说明 | 结论 |
|---|---|---|
| A. 使用 `python3.11`（3.11.12） | 本机已有，零下载 | 拒绝：低于计划书 3.12+ 下限 |
| B. 安装 3.12 / 3.13 后再开发 | `uv python install` 或 Homebrew；ENVIRONMENT_AUDIT R2 建议 3.13 | 未采用：Phase 0 时间与磁盘成本，且无证据表明 3.14 不可用 |
| C. 使用 3.14.8 + 项目隔离 venv（`Backend/.venv`） | 不新增下载；依赖锁定实测版本 | **选定** |
| D. 使用系统 3.9.6 | 零安装 | 拒绝：远低于下限，且不应依赖系统解释器 |

**决策**

采用方案 C：Sidecar 运行于 `Backend/.venv`（Python 3.14.8），依赖版本锁定为 `fastapi==0.163.1`、`uvicorn==0.54.0`，开发依赖 `pytest==9.2.0`、`httpx==0.28.1`。3.14.8 属于"**高于**计划书 3.12+ 下限"，不是版本降级。

**理由**

1. 版本号满足 `>=3.12` 的语义要求，且项目已有可运行证据（E2/E3/E5）。
2. 隔离 venv 避免系统 Python 污染，符合 Local-first 与可复现要求。
3. 不新增下载，规避 11 GiB 磁盘约束（RISK-01）。

**成本与风险**

- 3.14 生态较新：二进制 wheel 覆盖与第三方行为差异未大规模验证（RISK-02，P1 风险）。
- 若后续引入需要 C 扩展的依赖（如向量、分词、PDF 解析），可能缺少 3.14 wheel；届时按回退方案处理。
- 计划书文字为 3.12+，本决策需在阶段验收中显式记录"实际高于下限"，避免被误读为合规偏差已消除。

**迁移 / 回滚影响**

无数据迁移。回退步骤（已在本文记录，尚未执行）：

1. `uv python install 3.12`（或 `brew install python@3.12`）；
2. 删除并重建 `Backend/.venv`（`rm -rf Backend/.venv && uv venv --python 3.12`）；
3. 按锁定版本重装依赖；
4. 重跑 `pytest tests -q`（期望 57 passed）与 `Tests/phase0_integration_check.sh`（期望 68 PASS）。
   代码、契约、数据库格式均不变；`pyproject.toml` 的 `requires-python` 无需修改。

**验证结果**

- E1：`Python 3.14.8`。
- E5：`fastapi 0.163.1` / `uvicorn 0.54.0` / `pydantic 2.14.3` 可导入。
- E2：`57 passed in 9.08s`（`Backend/tests`）。
- E3：`tests/backend` 43 passed、`tests/data` 14 passed。
- **未验证**：在 3.12 / 3.13 上的任何运行；Python 3.14 与非纯 Python 依赖的长期兼容性。

---

### ADR-0002 XcodeGen 从 `App/project.yml` 生成工程，`.xcodeproj` 不入库

| 项 | 内容 |
|---|---|
| 编号 | ADR-0002 |
| 日期 | 2026-11-16 |
| 状态 | **Accepted** |

**背景与约束**

- 计划书未规定 Xcode 工程生成方式；要求 Swift 6 + SwiftUI、最低 macOS 14、严格并发检查。
- 多 Agent 协作下，手工维护 `project.pbxproj` 极易产生二进制式冲突，且无法审查设置来源。
- 本机已安装 `xcodegen 2.46.0`（E6）。
- 构建配置必须可复现，且部署目标必须显式为 14.0（本机仅有 macOS 27.2 / SDK 27.2）。

**候选方案**

| 方案 | 说明 | 结论 |
|---|---|---|
| A. 手工创建并提交 `.xcodeproj` | 传统方式，Xcode 直接可开 | 拒绝：pbxproj 冲突、设置不可审查 |
| B. XcodeGen 从 `App/project.yml` 生成，`.xcodeproj` 作为生成物忽略 | 单一工程源，可 diff | **选定** |
| C. 纯 SwiftPM | 包管理简单 | 拒绝：macOS App bundle、Info.plist、签名流程支持不如 Xcode 工程直接 |

**决策**

采用方案 B。`App/project.yml` 是唯一工程源；`Scripts/build_app.sh` 先 `xcodegen generate` 再 `xcodebuild`；`.gitignore` 忽略 `*.xcodeproj/`；Xcode 内的设置修改必须回写到 `project.yml`。

**理由**

1. 工程设置可审查、可 diff、可复现，适合多 Agent 与文档驱动协作。
2. 避免 `.pbxproj` 冲突；生成物不入库，减少噪声。
3. 部署目标、Swift 版本、严格并发集中声明，便于验收。

**成本与风险**

- 依赖本机 `xcodegen` 版本；`project.yml` 已声明 `minimumXcodeGenVersion: "2.46.0"`。
- 新环境首次构建必须先安装 XcodeGen；`build_app.sh` 在缺失时明确报错退出。
- Xcode GUI 手工改设置会被下次生成覆盖，需团队纪律与文档约束。

**迁移 / 回滚影响**

若放弃 XcodeGen：在 Xcode 中生成工程并提交 `.xcodeproj`，删除 `project.yml` 引用，调整 `Scripts/build_app.sh` 与 `.gitignore`。不影响 Sidecar、数据库、API 契约。

**验证结果**

- E6：`xcodegen 2.46.0`、`Apple Swift 6.4.2`。
- E7：`git ls-files | grep -c xcodeproj` = `0`（生成物未入库）；`build/DerivedData/Build/Products/Debug/PersonalIntelligenceHub.app` 存在。
- `App/project.yml` 实测声明 `MACOSX_DEPLOYMENT_TARGET 14.0`、`SWIFT_VERSION 6.0`、`SWIFT_STRICT_CONCURRENCY complete`。
- 构建成功的原始输出见 [PHASE_ACCEPTANCE.md](./PHASE_ACCEPTANCE.md) §6.1（`bash Scripts/build_app.sh` → `** BUILD SUCCEEDED **`）；**本轮未重跑 xcodebuild**。
- **未验证**：macOS 14 实机构建/运行（ENV-01）。

---

### ADR-0003 每请求短连接 + WAL + `check_same_thread=True`

| 项 | 内容 |
|---|---|
| 编号 | ADR-0003 |
| 日期 | 2026-11-16 |
| 状态 | **Accepted** |

**背景与约束**

- SQLite 是唯一权威业务数据源；FastAPI 同步路由在线程池执行，异步路由不得在事件循环线程执行阻塞 SQLite 调用。
- Phase 0 请求量极小（仅 `/health`），但数据层接口必须为 Phase 1 的并发写入留出正确边界。
- 需要崩溃恢复能力（App 崩溃、Sidecar 被 SIGKILL）。
- 不能为了"方便"关闭 `check_same_thread` 后跨线程共享连接。

**候选方案**

| 方案 | 说明 | 结论 |
|---|---|---|
| A. 模块级全局长连接 | 打开一次反复用 | 拒绝：跨线程风险、schema/WAL 状态陈旧、生命周期难管理 |
| B. 连接池 + `check_same_thread=False` + 锁 | 复用连接 | 拒绝：Phase 0 无收益，锁与事务边界易错；引入需基准测试与 ADR |
| C. 每请求/每操作短连接 + `check_same_thread=True` + WAL | 线程内创建、使用、关闭 | **选定** |
| D. ORM 连接管理 | 由 ORM 负责 | 拒绝：见 ADR-0008 |

**决策**

采用方案 C，落地于 [connection.py](../Backend/database/connection.py) 与 [database/__init__.py](../Backend/database/__init__.py)：

- `sqlite3.connect(..., isolation_level=None, check_same_thread=True)`；
- 每连接执行 `foreign_keys=ON`、`busy_timeout=5000`、`synchronous=NORMAL`；
- `journal_mode=WAL` 在初始化阶段设置并校验返回值必须为 `wal`；
- 健康探测使用独立短连接，`busy_timeout=500` ms，仅 `SELECT 1` + `MAX(version)`（Phase 0 另含 `quick_check`，DB-01）；
- 写操作经 `session()` 显式 `BEGIN IMMEDIATE` / `COMMIT`，异常 `ROLLBACK`。

**理由**

1. 线程内连接由构造保证线程安全，无需全局锁。
2. WAL 允许读不阻塞写，契合后续"UI 轮询 + 后台写入"形态，且支持崩溃恢复。
3. 短连接避免长事务与陈旧 schema；Phase 0 的打开开销可忽略。
4. `BEGIN IMMEDIATE` 尽早取写锁，避免锁升级失败。

**成本与风险**

- 每次操作打开连接有固定开销；Phase 0 可忽略，Phase 1 需按真实查询路径评估是否引入池。
- WAL 产生 `-wal` / `-shm` 文件；**备份不得只复制主文件**，Phase 1 必须用在线备份 API 或 `VACUUM INTO`（DATABASE_BASELINE §10）。
- `synchronous=NORMAL` 在断电场景可能丢失最近少量已提交事务（不损坏库），已接受该权衡。
- SQLite 仍是单写者；高并发写必须串行化，不能指望 WAL 提升写并发。

**迁移 / 回滚影响**

- 若 Phase 1 改用连接池：必须新增 ADR + 基准测试，且 `connect()` / `session()` 仍是唯一入口，业务代码不感知。
- 数据文件格式不变；切换连接策略无需数据迁移。

**验证结果**

- E8：SQLite `3.54.0`。
- E3：`tests/data` 14 passed（初始化、迁移幂等、事务回滚、目录不可写、checksum 篡改、跨进程重启、health）。
- E4 实测 PASS 项：`PRAGMA journal_mode（实际 wal）`、`session() 抛异常后无残留（事务回滚）`、`数据目录权限 0700`、`数据库文件权限 0600`、`PRAGMA quick_check（实际 ok）`。
- **未验证**：并发写压力、锁竞争下的重试行为、多实例迁移（Phase 0 明确不支持）。

---

### ADR-0004 stdout 单行握手 + 父进程看门狗的生命周期协议

| 项 | 内容 |
|---|---|
| 编号 | ADR-0004 |
| 日期 | 2026-11-16 |
| 状态 | **Accepted** |

**背景与约束**

- App 是 Sidecar 的唯一管理者，必须在无固定端口的前提下获知"服务已可请求"，并避免孤儿进程。
- 握手必须发生在 socket 已绑定且 ASGI startup 完成之后，否则 App 收到握手后立即请求会失败。
- Phase 0 要求优雅退出：SIGTERM 后 3 秒内退出，退出码 0；App 崩溃时子进程必须被回收。
- stdout 只能用于握手，日志必须写 stderr。

**候选方案**

| 方案 | 说明 | 结论 |
|---|---|---|
| A. App 子进程 + stdout 单行握手 + 父进程看门狗 + SIGTERM/SIGKILL | 进程所有权清晰 | **选定** |
| B. launchd 常驻服务 | 系统托管 | 拒绝：与"App 拥有生命周期"冲突，端口/Token 生命周期难约束 |
| C. 用户手工启动 Sidecar | 开发调试可行 | 拒绝：产品不可用，无法保证 Token 与端口 |
| D. 子进程但无看门狗 | 实现简单 | 拒绝：App 崩溃后残留孤儿进程，违反可靠性要求 |

**决策**

采用方案 A，落地于 [Backend/main.py](../Backend/main.py)：

1. App 生成 Token（仅环境变量传递）→ spawn → 10 秒内读取 stdout 首行；
2. Sidecar 在 `SidecarServer.startup()` 返回后，用 `os.write(1, …)` 输出 **一行** `PIH_SIDECAR_READY {json}`，长度上限 4096 字节；
3. `sys.stdout = sys.stderr` 预先把所有库输出重定向到 stderr，stdout 只留握手；
4. SIGTERM / SIGINT：`should_exit=True` + 3 秒强制退出兜底；
5. 父进程看门狗每 2 秒检查 `os.getppid()`；父进程消失或 `ppid==1` 时记 `parent_lost` 并在 1 秒内停止（QA-01 已修复启动竞态）。

**理由**

1. 握手由服务端在"真正可服务"时写出，天然消除"端口已开但 ASGI 未就绪"的竞态。
2. 子进程归属明确，Token 与端口随 App 生命周期失效。
3. 看门狗覆盖 App 崩溃/被强杀场景；无看门狗时孤儿进程会长期占用内存与端口。
4. 单行握手可被流式读取，不需要解析多行日志。

**成本与风险**

- 依赖 stdout 纯净：任何第三方库向 stdout 打印都会破坏协议；已用重定向 + 单点写缓解，并有集成断言（stdout 行数 = 1）。
- 看门狗轮询带来最坏约 3 秒的孤儿窗口（2 秒轮询 + 1 秒宽限）。
- 握手内容包含 `pid`，用于防端口串话；App 必须校验与子进程 PID 一致。
- 父进程 PID 复用理论风险极低，但未做额外校验。

**迁移 / 回滚影响**

- 改为 launchd 或外部托管属于生命周期协议破坏性变更：必须改 `API_CONTRACT.md` §2/§9、写新 ADR、前后端同步发布。
- 不涉及数据迁移。

**验证结果**

- E4 实测 PASS 项：`10 秒内收到握手`、`stdout 行数 = 1`、`握手字段合法（port/pid/service/version，pid 与子进程一致）`、`全程 stdout 行数保持 1`、`父进程消失后 Sidecar 1.33s 内退出（<=4s，含 2s 轮询）`、`父进程消失记录 parent_lost 事件`、`启动竞态用例中 Sidecar 已自行退出`。
- E2/E3：进程生命周期相关用例包含在 43 项后端测试中，全部通过。
- SIGTERM 退出码 0 与 0.19 秒退出见 [TEST_REPORT.md](./TEST_REPORT.md) §3；本轮集成汇总 `PASS=68 FAIL=0` 覆盖同一用例。
- **未验证**：App 进程被 SIGKILL 后 Sidecar 的真实回收（集成脚本以子进程模拟父进程消失，未覆盖 GUI 进程被强杀的完整路径）。

---

### ADR-0005 Phase 0 仅 2 张基础设施表，业务表延后至 Phase 1

| 项 | 内容 |
|---|---|
| 编号 | ADR-0005 |
| 日期 | 2026-11-16 |
| 状态 | **Accepted** |

**背景与约束**

- 计划书第 10 章要求 Phase 0 只做工程初始化与健康检查；业务表设计属于数据治理，需先有契约与裁决。
- 提前建业务表会锁定错误字段，且容易演变为"用空表假装已实现"。
- 必须证明迁移机制、读写与事务回滚真实可用，否则 Phase 1 无可靠底座。

**候选方案**

| 方案 | 说明 | 结论 |
|---|---|---|
| A. Phase 0 建完整业务 Schema | "一步到位" | 拒绝：无数据契约、无真实查询路径，必然返工；违反 ARCHITECTURE §6.4 |
| B. 仅 `schema_migrations` + `app_meta` | 只证明基础设施能力 | **选定** |
| C. 只建 `schema_migrations` | 最小 | 拒绝：无法证明真实读写与事务回滚 |

**决策**

采用方案 B。`0001_init.sql` 仅创建 `app_meta`；`schema_migrations` 由迁移运行器 bootstrap。`app_meta` 不承载业务配置，禁止被当作偏好表使用。

**理由**

1. 用最小表证明"迁移 + 读写 + 回滚 + 权限"真实可用，不引入业务语义。
2. 让 Phase 1 的 Schema 评审真正有意义：字段来自真实查询路径，而不是猜测。
3. 与 Source-first / Truthful UI 一致：没有真实数据就不建假装承载数据的表。

**成本与风险**

- Phase 1 必须从 `0002_*.sql` 开始，且 `0001_init.sql` 不可修改（已应用迁移不可变）。
- Phase 1 Schema 评审是关键路径，若延迟会阻塞采集。
- `app_meta` 有被误用为配置表的风险，需在数据契约中明确禁止。

**迁移 / 回滚影响**

- `0001_init.sql` 永久冻结；任何修复都通过更高版本迁移。
- 若误建业务表：必须回退实现并新增迁移删除（不得修改历史迁移），同时更新验收记录。

**验证结果**

- E4 实测 PASS 项：`业务表清单（仅基础设施表）（实际 app_meta,schema_migrations,）`、`schema_migrations 版本（实际 1,）`、`schema_migrations 行数（实际 1）`、`app_meta 初始行数（实际 0）`、`同目录二次启动后 schema_migrations 仍仅 1 行`。
- E3：`tests/data` 14 passed，包含 checksum 篡改与回滚用例。
- 表结构与边界声明见 [DATABASE_BASELINE.md](./DATABASE_BASELINE.md) §1、§7。
- **未验证**：Phase 1 业务 Schema（尚未设计）。

---

### ADR-0006 端口发现只允许 stdout 握手

| 项 | 内容 |
|---|---|
| 编号 | ADR-0006 |
| 日期 | 2026-11-16 |
| 状态 | **Accepted** |

**背景与约束**

- 端口必须由内核随机分配（`PIH_PORT=0`），避免固定端口冲突与被本地网页预测。
- App 必须拿到**本进程实际监听**的端口，且不能误连其他本地服务。
- 端口信息不得写入文件、环境变量回传或日志（会扩大泄漏面并引入陈旧状态）。
- 该决策是 ADR-0004 生命周期协议的子决策，单独归档以便契约审查。

**候选方案**

| 方案 | 说明 | 风险 | 结论 |
|---|---|---|---|
| A. stdout 握手携带 `port` | 服务端在 startup 完成后写出 | 依赖 stdout 纯净（已缓解） | **选定** |
| B. 端口写入数据目录文件，App 轮询读取 | 文件可读 | 陈旧文件、多实例写同一文件、崩溃残留、权限面扩大 | 拒绝 |
| C. 固定端口（如 8765） | 简单 | 冲突、被本地网页扫描命中、多实例不可用 | 拒绝 |
| D. App 用 `lsof` 扫描子进程端口 | 无需协议 | 竞态、可能命中其他进程、无法校验 pid、依赖外部命令 | 拒绝 |

**决策**

采用方案 A，并在实现上消除 TOCTOU：先 `bind(("127.0.0.1", 0))` 得到内核分配的 socket，再把该 socket 交给 uvicorn；握手输出 `port`、`pid`、`service`、`version`，App 校验 `pid` 等于自己 spawn 的子进程 PID。

**理由**

1. 单次原子事件，不产生需要清理的文件状态。
2. `pid` 校验可检测端口串话；文件/扫描方案都缺少等价保护。
3. 与"stdout 仅握手、日志走 stderr"的日志规范一致。

**成本与风险**

- 任何向 stdout 的杂散输出都会破坏协议；已通过 `sys.stdout = sys.stderr` + `os.write(1, …)` 单点写入缓解，并由集成断言守护。
- 握手丢失（进程在写之前崩溃）时 App 只能按失败处理，这是预期行为。
- 不支持"重连到已在运行的 Sidecar"，Phase 0 明确不提供 attach 模式。

**迁移 / 回滚影响**

- 更换发现方式属于 `API_CONTRACT.md` §3/§4 破坏性变更：需新 ADR + 契约更新 + 前后端同步发布 + 契约回归。
- 不影响数据库与数据格式。

**验证结果**

- E4 实测 PASS 项：`握手字段合法（port/pid/service/version，pid 与子进程一致）`、`仅监听 127.0.0.1:<port>`、`无 0.0.0.0 / :: 监听`、`连续两次启动端口不同`（脚本 `Tests/phase0_integration_check.sh` L249–L256）。
- 本次运行未摘录具体端口值；历史一次运行的两端口为 `60837` / `60846`（[TEST_REPORT.md](./TEST_REPORT.md) §3），仅作示例，不代表本次数值。
- **未验证**：端口耗尽、极端并发启动下的分配行为。

---

### ADR-0007 后端目录采用扁平结构 `Backend/{api,core,database}`

| 项 | 内容 |
|---|---|
| 编号 | ADR-0007 |
| 日期 | 2026-11-16 |
| 状态 | **Accepted** |

**背景与约束**

- 建库前的指令示例使用 `Backend/app/{api,core,database,…}`；计划书 3.4 与 [AGENT_TEAM.md](./AGENT_TEAM.md) 文件归属矩阵使用 `Backend/{api,database,collectors,…}` 扁平结构。
- 归属矩阵按精确路径定义 owner；改路径会造成"文件在谁的边界内"歧义，属于协作风险。
- Phase 0 只有一个 Sidecar 应用，`app/` 包层不提供实际隔离价值。

**候选方案**

| 方案 | 说明 | 结论 |
|---|---|---|
| A. `Backend/app/{api,core,database}` | 常见 FastAPI 布局 | 拒绝：与归属矩阵路径不一致，需重写多份文档与 owner 规则 |
| B. `Backend/{main.py,api,core,database}` 扁平 | 与计划书/归属矩阵一致 | **选定** |
| C. `Backend/src/pih/...` 可安装包 | 规范化打包 | 推迟：Phase 7 打包方案再评估，届时需 ADR |

**决策**

采用方案 B。`main.py` 作为入口，把 `Backend` 目录加入 `sys.path` 后以顶层包导入（`import database`、`from api.app import create_app`）；测试通过 `pyproject.toml` 的 `pythonpath = ["."]` 解析。

**理由**

1. 与 [AGENT_TEAM.md](./AGENT_TEAM.md) §3 的 owner 路径逐字一致，避免越界与文档返工。
2. Phase 0 无多应用/多包需求，扁平结构更易审查。
3. `PROJECT_BASELINE.md` §6 已裁决采用扁平结构，本 ADR 为该裁决提供正式载体。

**成本与风险**

- 顶层导入依赖 `sys.path` 注入；若未来做成可安装包，需要重构导入路径。
- 部分框架约定（`app.main:app`）不适用；启动脚本与文档必须使用 `Backend/main.py`。
- 与 `app/` 布局的第三方示例存在差异，新成员需阅读本文。

**迁移 / 回滚影响**

- 若改为 `Backend/app/`：需移动 `main.py`、`api/`、`core/`、`database/`，更新测试导入、`Scripts/run_backend.sh`、`Tests/phase0_integration_check.sh` 与全部文档路径；需新 ADR。无数据迁移。

**验证结果**

- E9：`git ls-files` 显示实际结构为 `Backend/main.py`、`Backend/api/*`、`Backend/core/*`、`Backend/database/*`。
- E2/E3：在 `pythonpath = ["."]` 下 `57 passed`（43 + 14），证明扁平结构可测试。
- E4：集成脚本以 `Backend/main.py` 启动 Sidecar，`PASS=68 FAIL=0`。
- **未验证**：`Backend/src/` 打包形态（未实施）。

---

### ADR-0008 标准库 `sqlite3` + 手写 Migration，不引入 ORM / Alembic

| 项 | 内容 |
|---|---|
| 编号 | ADR-0008 |
| 日期 | 2026-11-16 |
| 状态 | **Accepted** |

**背景与约束**

- SQLite 是唯一权威业务源；所有 Schema 变更必须可审计、可回滚、可复现。
- Python 3.14 上 ORM/C 扩展的 wheel 可用性存在风险（ADR-0001）。
- Phase 0 只需要极小的迁移能力，但必须支持：版本记录、checksum 校验、版本过高拒绝、失败整体回滚。
- 禁止 API/Collector 散落 SQL（Phase 1 起由 Repository 收口）。

**候选方案**

| 方案 | 说明 | 结论 |
|---|---|---|
| A. SQLAlchemy + Alembic | 生态成熟、自动迁移 | 拒绝：引入大依赖与新版本兼容风险；Alembic 面向 SQLAlchemy 元数据，手写 SQL 更直接 |
| B. 标准库 `sqlite3` + 手写迁移运行器 | 零额外依赖、SQL 可见 | **选定** |
| C. `executescript` 无版本表 | 最省事 | 拒绝：无法校验已应用版本，失败可能半提交 |

**决策**

采用方案 B，落地于 [migrator.py](../Backend/database/migrator.py)：

- 迁移文件 `NNNN_snake_case.sql`，UTF-8/LF，禁止在文件内写事务控制语句；
- `schema_migrations(version, applied_at, checksum)` 由运行器 bootstrap；
- 每个迁移一个 `BEGIN IMMEDIATE` 事务，迁移 SQL 与版本记录原子提交；失败 `ROLLBACK` 并停止后续迁移；
- 已应用文件 checksum 不一致、数据库版本高于程序、缺失迁移文件 → `database_schema_error`，不自动改库；
- 已应用迁移不可修改，修复必须新增更高版本。

**理由**

1. 依赖面最小（仅标准库），规避 3.14 wheel 风险。
2. SQL 与事务边界完全可见，便于安全审查与性能分析。
3. checksum + 不可变文件提供可追溯性，符合"有迁移、可回滚"的验收要求。

**成本与风险**

- 手写运行器必须自行保证顺序、幂等、回滚与错误分类；已由测试覆盖，但复杂度随 Schema 增长。
- 无自动生成/自动 diff，Schema 文档需要人工同步（DATABASE_BASELINE §13）。
- Repository 层尚未建立（Phase 1），当前 `session()` 仍可被直接调用，需在 Phase 1 收紧边界。

**迁移 / 回滚影响**

- 迁移失败时数据库保持执行前状态；已应用迁移不可回滚到旧版本（数据库版本高于程序时拒绝启动迁移）。
- 若未来引入 ORM：需要新 ADR、双写/迁移评估与完整回归，不得直接替换。

**验证结果**

- E3：`tests/data` 14 passed，覆盖初始化、幂等、事务回滚、目录不可写、checksum 篡改、跨进程重启、health。
- E4 实测 PASS 项：`schema_migrations 版本（实际 1,）`、`同目录二次启动后 schema_migrations 仍仅 1 行`、`session() 抛异常后无残留（事务回滚）`、`PRAGMA journal_mode（实际 wal）`。
- checksum 篡改用例：集成/测试中触发 `database_schema_error` 且不自动改库（[PHASE_ACCEPTANCE.md](./PHASE_ACCEPTANCE.md) 第 11 项）。
- **未验证**：大体量迁移耗时、并发迁移、多实例竞争（Phase 0 明确不支持）。

---

### ADR-0009 Swift 单元测试 target 覆盖握手解析与健康模型解析

| 项 | 内容 |
|---|---|
| 编号 | ADR-0009 |
| 日期 | 2026-11-16 |
| 状态 | **Accepted** |

**背景与约束**

- `ARCHITECTURE.md` §6.1 要求"后端与 Swift 单元测试，覆盖握手解析"。
- Phase 0 初始化时 `App/project.yml` 只有 application target，没有测试 target；`Tests/` 下只有 shell 集成脚本。该缺口登记为 TEST-01（P2）。
- 握手解析（前缀、单行、JSON、`port` 范围、`pid`、`service`、版本）、健康响应解码与 Token 生成本身是纯逻辑，仅靠真实运行与截图无法覆盖畸形输入。
- macos-developer 已新增 `PersonalIntelligenceHubTests` target 与 3 个测试文件；architect 需独立执行并核对，不采信自述。

**候选方案**

| 方案 | 说明 | 结论 |
|---|---|---|
| A. 新增 `PersonalIntelligenceHubTests` target（XCTest），由 `project.yml` 声明 | 覆盖握手/健康模型/Token 纯逻辑 | **已实施** |
| B. 维持现状，用真实运行 + 集成脚本作为替代证据，并修订 §6.1 | 零新增代码 | 未采用：无法覆盖畸形握手与错误分支 |
| C. UI 自动化（XCUITest） | 端到端 | 不作为替代：不覆盖解析边界，成本更高 |

**决策**

采用方案 A 并已落地：

- `App/project.yml` 新增 `PersonalIntelligenceHubTests`（`type: bundle.unit-test`，依赖 app target，`TEST_HOST`/`BUNDLE_LOADER` 指向 App 可执行文件），scheme 增加 `test` 段；
- 测试文件：`App/PersonalIntelligenceHubTests/HandshakeParserTests.swift`（23 项）、`HealthModelsTests.swift`（8 项）、`SidecarTokenTests.swift`（4 项），合计 35 项；
- 覆盖：合法握手、未知字段、边界值、空行、超 4096 字节、非法 UTF-8、前缀/分隔符、JSON 畸形、缺字段、类型错误、`port` 0/越上界/负数、`pid` 0/负数/超 Int32、`service` 不符、MAJOR 版本不兼容；健康响应可选字段与错误类型；Token 长度/字符集/解码字节数/连续生成不同。

**理由**

1. 纯逻辑测试可复现、低成本，能守住 `API_CONTRACT.md` §4 的协议边界。
2. 与后端 57 项测试形成对称覆盖；Phase 0 的"Swift 单元测试"退出条件不再依赖截图。
3. 仅改工程生成源与测试文件，不改产品代码。

**成本与风险**

- 测试构建增加约数秒；磁盘紧张时需清理 DerivedData（RISK-01）。
- 测试直接链接 App target（`TEST_HOST`），App 启动逻辑变化可能影响测试宿主，但当前测试不启动 UI。
- **覆盖缺口**：`BackendConfiguration` 的路径标准化（QA-02/QA-03）未被单元测试覆盖；不影响 §6.1 的"握手解析"要求，建议 Phase 1 追加 `BackendConfigurationTests`。

**迁移 / 回滚影响**

- 无数据迁移；回退只需移除 target 段与测试目录，不影响 App 产物与 Sidecar。
- 测试 target 仍由 XcodeGen 生成，`project.yml` 是唯一源；回退不得手工改 `.xcodeproj`。

**验证结果**

- E11：`xcodegen generate --spec App/project.yml` + `xcodebuild test -project App/PersonalIntelligenceHub.xcodeproj -scheme PersonalIntelligenceHub -configuration Debug -derivedDataPath build/DerivedData -destination 'platform=macOS'` → `Executed 35 tests, with 0 failures (0 unexpected) in 0.017 (0.029) seconds`，`** TEST SUCCEEDED **`。
- 用例分布核对：`grep -c "func test"` → `HandshakeParserTests.swift` 23、`HealthModelsTests.swift` 8、`SidecarTokenTests.swift` 4。
- 测试结果包：`build/DerivedData/Logs/Test/Test-PersonalIntelligenceHub-2026.11.16_15-43-03-+0800.xcresult`。
- TEST-01 的工程侧判据已满足，待 `PHASE_ACCEPTANCE.md` 复核时关闭（该文件不在本轮写入范围）。
- **未验证**：macOS 14 实机运行（ENV-01）；UI 自动化；`BackendConfiguration` 路径标准化（未覆盖）。

---

### ADR-0010 Ollama 模型分档策略

| 项 | 内容 |
|---|---|
| 编号 | ADR-0010 |
| 日期 | 2026-11-16 |
| 状态 | **Accepted（高性能档 Deferred）** |

**背景与约束**

- 本机：Apple M4 / 16 GiB / 磁盘可用约 11 GiB（RISK-01）；Ollama 0.40.15 运行中。
- 本地可用模型仅 3 个：`qwen3:1.7b`（1.4 GB）、`gemma3:4b`（3.3 GB）、`qwen3.5:4b-mlx`（4.0 GB）；4 个 `-cloud` 为云端代理，调用即出网，必须排除（SEC-02/RISK-03）。
- **无 Embedding 模型**（AI-01）：`/api/embed` 对 `nomic-embed-text`、`bge-m3` 均 not found。
- 实测：默认 `num_ctx=32768` 会让 1.7B 模型驻留 5.1 GB（4096 时仅 1.5 GB）；双模型驻留会触发换页，冷加载从 0.008 s 恶化到 8.1 s。
- Phase 0 不调用 Ollama（`ARCHITECTURE.md` §10.1），本 ADR 只冻结 Phase 3 的分档策略。

**候选方案**

| 方案 | 说明 | 结论 |
|---|---|---|
| A. 全用最大可用模型（4B/更大） | 质量优先 | 拒绝：1.7B 已能满足结构化任务，4B 常驻内存成本高 |
| B. 三档分档 + 单模型常驻 + 显式 `num_ctx` | 按任务分配 | **选定** |
| C. 使用 `-cloud` 模型补足质量 | 质量高 | 拒绝：数据出网，违反 Local-first |
| D. 立即下载 7–8B 作为主模型 | 质量优先 | 拒绝/推迟：内存临界、磁盘紧张，需用户确认与实测 |

**决策**

采用方案 B：

1. **轻量档（默认）**：`qwen3:1.7b`，负责分类、关键词、严格 JSON、≤800 字摘要；`num_ctx=4096`，单并发。
2. **中等档（按需）**：`gemma3:4b` 或 `qwen3.5:4b-mlx` 二选一常驻，负责事件综合摘要与中文通顺度要求高的文案；`num_ctx≤8192`，禁止同时常驻。
3. **高性能档（Deferred）**：7–8B Q4 级模型，仅按需加载、`num_ctx≤8192`、单并发；下载需用户确认（约 5.2 GB），下载后必须实测 tok/s 与内存占用，未实测前不得承诺吞吐。
4. **禁止项**：任何 `*-cloud` 模型不得进入 Provider 白名单；Provider 必须显式传 `num_ctx`；不得硬编码模型名。
5. **Embedding**：Phase 3 需下载 `nomic-embed-text`（约 0.3 GB）或 `bge-m3`（约 1.2 GB），由用户确认磁盘后再实施；在此之前语义去重/检索不可用（AI-01）。

**理由**

1. 轻量档实测生成 73.9–85.9 tok/s、分类端到端 0.235 s，足以承担高频结构化任务（E10）。
2. 4B 档生成 27.9–37.7 tok/s，中文更通顺，但只能单模型常驻，适合低频率综合任务。
3. 显式 `num_ctx` 可把 1.7B 驻留从 5.1 GB 降到 1.5 GB，是 16 GiB 机器上最有效的成本控制。
4. 排除云端模型是 Local-first 的硬约束，不是性能权衡。

**成本与风险**

- `gemma3:4b` 会加入原文没有的判断（T5），所有自由文本必须与来源事实分离标注；`qwen3.5:4b-mlx` 存在中文丢字（T6），必须经 schema/字数校验与后处理。
- 磁盘仅 11 GiB：Embedding + 7–8B 模型不可能同时下载，需按 Phase 优先级取舍。
- 内存压力：当前 swap 已用 2.51/3.0 GiB，模型驻留时空闲内存 0.08 GiB；并发上限必须为 1。
- 仅 1–2 条样本，未做批量质量评测；不得把单例表现当作准确率。

**迁移 / 回滚影响**

- Phase 0 无代码调用，无迁移。
- Phase 3 通过模型注册表 + Provider 白名单落地；调整分档只改注册表配置，不做数据迁移。
- 若更换 Embedding 模型，`article_embeddings` 必须记录 `embedding_model`、`model_version`、`dimensions`，并重建向量（届时写迁移方案）。

**验证结果**

- E10（[LOCAL_AI_AUDIT.md](./LOCAL_AI_AUDIT.md) §4.3，同日同机真实推理，本轮未重跑）：qwen3:1.7b 生成 73.9–85.9 tok/s；gemma3:4b 37.6–37.7 tok/s；qwen3.5:4b-mlx 27.9 tok/s；全部 100% GPU。
- 驻留实测：1.7B @32768 = 5.1 GB，@4096 = 1.5 GB；gemma3:4b @4096 = 2.3 GB；双模型驻留导致 gemma3 冷加载 8.126 s。
- Embedding 缺失：`/api/embed` 对 `nomic-embed-text`、`bge-m3` 均返回 not found（AI-01）。
- **未验证**：Provider 集成、批量质量评测、7–8B 模型速度/内存、并发吞吐、长上下文（>492 prompt tokens）。

---

### ADR-0011 API 契约存放于 `Docs/API_CONTRACT.md`

| 项 | 内容 |
|---|---|
| 编号 | ADR-0011 |
| 日期 | 2026-11-16 |
| 状态 | **Accepted** |

**背景与约束**

- `AGENT_TEAM.md` §3.1 将 `Docs/contracts/**` 列为共享契约目录；`ARCHITECTURE.md` §5.4 注明"当前契约暂位于 `Docs/API_CONTRACT.md`；迁移位置需 ADR"。
- 建库阶段指令要求契约落在 `Docs/API_CONTRACT.md`。
- Phase 0 只有一份 HTTP 契约，拆目录会增加引用维护成本；但 Phase 1 起会新增数据/事件契约，可能需要分目录。

**候选方案**

| 方案 | 说明 | 结论 |
|---|---|---|
| A. 立即迁入 `Docs/contracts/api/API_CONTRACT.md` | 与 AGENT_TEAM 目录规划一致 | 拒绝：Phase 0 无收益，需改多处引用 |
| B. 维持 `Docs/API_CONTRACT.md` 为唯一权威 | 单文件，引用稳定 | **选定** |
| C. 拆分为 API/数据/事件三份 | 面向 Phase 1+ | 推迟：Phase 1 引入数据契约时再评估 |

**决策**

采用方案 B。`Docs/API_CONTRACT.md` 为 Phase 0 唯一权威 HTTP 契约；`Docs/contracts/` 在 Phase 0 不创建。Phase 1 引入数据/事件契约时，由 architect 决定是否新建 `Docs/contracts/` 并写新 ADR，同时同步全部引用。

**理由**

1. 契约已被 9 份文档引用，迁移只增加断链风险。
2. 单文件便于前后端逐条对照，Phase 0 契约规模可控（14 章）。
3. 与 `PROJECT_BASELINE.md` §6 的既有裁决一致，避免二次裁决。

**成本与风险**

- 与计划书 14.2 的文档清单命名（`API_REFERENCE.md`）不同；后者定位为后期整合文档，不得据此改变本契约。
- 单文件会随 Phase 增长变长；Phase 1 起需评估拆分。
- 目录规划与 `AGENT_TEAM.md` 存在文字差异，需在 Phase 1 文档评审时统一。

**迁移 / 回滚影响**

- 未来迁移：`git mv` + 更新全部引用 + 新 ADR；代码不感知文档路径。
- 无数据迁移。

**验证结果**

- E9：`Docs/API_CONTRACT.md` 存在；`Docs/contracts/` 不存在。
- `PROJECT_BASELINE.md` §6 第 2 行已记录该裁决。
- `API_CONTRACT.md` 自身 §0 声明"当前权威位置为 `Docs/API_CONTRACT.md`；若后续迁入 `Docs/contracts/`，需 architect 记录 ADR"。
- **未验证**：无（文档位置可直接由 `ls` 验证）。

---

## 3. 索引缺口、未关闭项与文档冲突

### 3.1 ARCHITECTURE §12.1 登记缺口

本轮仅按白名单把 §12.1 表中 ADR-0001…0005 的状态改为"已归档（见 TECHNICAL_DECISIONS.md）"，未新增表格行。以下 6 条 ADR 已在 2026-11-16 的验收复核中补登记到 §12.1（状态同步为"已归档"）：

| ADR | 标题 | 状态 |
|---|---|---|
| ADR-0006 | 端口发现只允许 stdout 握手 | Accepted |
| ADR-0007 | 后端扁平目录结构 | Accepted |
| ADR-0008 | 标准库 sqlite3 + 手写 Migration | Accepted |
| ADR-0009 | Swift 单元测试 target | Accepted |
| ADR-0010 | Ollama 模型分档 | Accepted（高性能档 Deferred） |
| ADR-0011 | API 契约位置 | Accepted |

### 3.2 未关闭项

| 项 | 关联 ADR | 关闭条件 |
|---|---|---|
| TEST-01 | ADR-0009 | **已关闭**：`xcodebuild test` 35 passed / `TEST SUCCEEDED`（E11）；`Docs/PHASE_ACCEPTANCE.md` 已复核关闭 |
| RISK-02 | ADR-0001 | Phase 1 复核：现有依赖 22/23 为纯 Python，唯一二进制 `pydantic_core` 有 `cp314` wheel；Phase 1 计划依赖均支持 3.14（见 `PYTHON_COMPATIBILITY.md`）。维持持续回归 |
| DISK-01 | ADR-0012 | **用户 2026-11-16 接受**：可用 8.6 GiB 继续 Stage 1.1 设计；大规模构建/批量采集前须复核并恢复 ≥20 GiB。未关闭 |
| MAC-01 / ENV-01 | ADR-0013 | 保持 macOS 14 最低支持；实机验证方案见 `MACOS_COMPATIBILITY.md`，列为发布门禁。未关闭 |
| SEC-02 / RISK-03 | ADR-0010 / ADR-0014 | Phase 3 Provider 白名单拒绝 `*-cloud`，并用 `lsof`/抓包证明无外连；用户不批准删除 Cloud 模型 |
| SEC-01 | ADR-0010 / ADR-0014 | 用户已批准收敛至 `127.0.0.1`，但执行前须完成局域网依赖确认并提供回滚方案；**尚未执行** |
| AI-01 | ADR-0010 | Phase 3 下载 Embedding 模型并实测（需用户确认磁盘） |

### 3.3 与现有文档的冲突（本轮不修改，记录待办）

| 冲突 | 现状 | 建议处理 |
|---|---|---|
| `ARCHITECTURE.md` §1.2 | 原写"仅存在 Docs/…，不存在 App/、Backend/，尚未初始化 Git" | 已于 2026-11-16 修订为提交 `ad1c403` 的实况（79 个受控文件、3 个提交、完整源码） |
| `ARCHITECTURE.md` §12.1 | 原只登记 5 条 ADR | 已补登记 ADR-0006…0016（见 §3.1 与 §1 索引） |
| `AGENT_TEAM.md` §3.1 vs ADR-0011 | 归属矩阵写 `Docs/contracts/**` | 以 ADR-0011 为准；Phase 1 文档评审时统一措辞 |
| `DEVELOPMENT_ROADMAP.md` §2/§3/§4.3 | 仍写 Phase 0 = PARTIAL、禁止进入 Phase 1 | **已于 2026-11-16 按用户 C6 裁决修订**：Phase 0 = PASSED，Phase 1 仅授权 Stage 1.1 设计；历史验收过程保持不变（见 `PHASE_ACCEPTANCE.md` §7） |
| `ARCHITECTURE.md` 头部阶段状态 | 原写 Phase 0 = IN_PROGRESS | **已于 2026-11-16 修订**为 Phase 0 = PASSED、Phase 1 = Stage 1.1 设计 |

---

## 4. 变更规则

1. 新增/推翻核心选型、数据模型、评分算法、阶段标准：先写 ADR（本文件），再实施。
2. ADR 状态只能取 `Accepted` / `Proposed` / `Deferred`；`Accepted` 必须有可复现验证结果或明确的"未验证"声明。
3. 已 `Accepted` 的 ADR 被推翻时，不删除原文，新增 ADR 并在旧条目顶部标注"Superseded by ADR-XXXX"。
4. 契约（API/数据/事件）变更仍先改 `Docs/*_CONTRACT.md` / `Docs/*_BASELINE.md`，ADR 只记录决策与证据。
5. 任何"已验证"表述必须能由命令、测试计数或文件路径复现；无法复现的写"未验证"。
6. 阶段专属 ADR（如 Phase 1 的 ADR-0012…0016）正文可放在该阶段设计文档（`PHASE1_ADR.md`）中，但必须在本文 §1 索引登记，且编号全局唯一、不复用。
