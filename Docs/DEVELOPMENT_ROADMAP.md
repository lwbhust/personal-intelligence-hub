# PIH 开发路线图与阶段门禁（Phase 0–7）

- 文档版本：1.0
- 日期：2026-11-16
- 唯一产品基线：[Personal_Intelligence_Hub_开发计划书与Agent执行规范](./Personal_Intelligence_Hub_开发计划书与Agent执行规范.docx)（第 10 章为阶段定义来源）
- 关联文档：[ARCHITECTURE.md](./ARCHITECTURE.md)、[TECHNICAL_DECISIONS.md](./TECHNICAL_DECISIONS.md)、[PHASE_ACCEPTANCE.md](./PHASE_ACCEPTANCE.md)、[API_CONTRACT.md](./API_CONTRACT.md)、[DATABASE_BASELINE.md](./DATABASE_BASELINE.md)

> 本文件定义 Phase 0–7 的边界、依赖与门禁。阶段名称、实施范围与退出条件严格对齐计划书第 10 章；本文件只做工程化展开，不新增产品能力。
> 本文件不构成任何"已完成"声明。阶段结论只写在 `Docs/PHASE_ACCEPTANCE.md`，由 architect 基于可复现证据发布。

---

## 1. 门禁总则（不可协商）

1. **顺序执行**：必须按 Phase 0 → Phase 7 顺序实施；**每阶段未通过验收，不得进入下一阶段正式开发**。
2. **进入 Phase 1 需用户批准**。批准前，Phase 1 只允许文档级设计讨论（数据契约草案、技术方案比较），**不得创建业务表、业务 API、评分或事件实现**。
3. **阶段通过条件**：计划书第 11.2 节通用门禁全部满足 + 本文件该 Phase 的退出条件全部满足 + 无 P0/P1 阻断项。
4. **证据优先**：只采信可复现证据（命令输出、测试计数、真实进程/HTTP/DB 观测、截图）。开发 Agent 的"已完成"自述不构成验收证据。
5. **真实性红线**：禁止 mock、静态假数据、假进度、占位按钮、固定评分；禁止用文章数量冒充热度；禁止用静态图谱冒充事件关系。
6. **不承诺未验证数字**：未做基准测试前，不得承诺吞吐、并发、图谱节点上限、模型准确率或大规模数据性能。
7. **契约先行**：新增 API、数据表、事件结构、评分输入输出，先写契约与 ADR，再写实现。
8. **残留项随阶段关闭**：第 11 节的遗留项必须在其指定 Phase 关闭；不得跨阶段无限顺延。

---

## 2. 阶段状态总览

| Phase | 名称 | 状态 | 结论来源 | 进入下一阶段 |
|---|---|---|---|---|
| 0 | 环境审计与工程初始化 | **PASSED**（2026-11-16，验收基提交 `ad1c403`） | [PHASE_ACCEPTANCE.md](./PHASE_ACCEPTANCE.md) | 已通过；用户于 2026-11-16 批准进入 Phase 1 |
| 1 | 数据底座与信息源管理 | **PASS WITH CONDITIONS**（2026-11-16，HEAD `176557f`） | [PHASE1_ACCEPTANCE.md](./PHASE1_ACCEPTANCE.md)、[PHASE1_QA_REPORT.md](./PHASE1_QA_REPORT.md) | 允许 Phase 2 规划；真实采集前须解决 DISK-01 并实现 `net_guard` |
| 2 | 多渠道信息采集 | **PASS**（2026-11-16，验收基提交 `6b4c17b`） | [PHASE2_ACCEPTANCE.md](./PHASE2_ACCEPTANCE.md) | 已通过 |
| 3 | 本地 AI 分析 | **PASS WITH CONDITIONS**（2026-11-16，分支 `phase3/local-ai-analysis`；SEC-01 于 2026-11-17 关闭） | [PHASE3_ACCEPTANCE.md](./PHASE3_ACCEPTANCE.md)、[PHASE3_QA_REPORT.md](./PHASE3_QA_REPORT.md) | 允许 Phase 4 规划；仅余 C2（UI 视觉复核）条件项 |
| 4 | 事件聚合与智能排行 | **PASS WITH CONDITIONS**（2026-11-17，分支 `phase4/event-intelligence`；独立 QA 首轮 FAIL，Critical/High 已修复，复测经用户豁免） | [PHASE4_ACCEPTANCE.md](./PHASE4_ACCEPTANCE.md)、[PHASE4_QA_REPORT.md](./PHASE4_QA_REPORT.md)、[PHASE4_HANDOVER_AUDIT.md](./PHASE4_HANDOVER_AUDIT.md) | 允许 Phase 5 规划；条件 C1（独立复测豁免）与 C2–C8 低级别遗留 |
| 5 | 阅读与知识管理 | 未开始 | — | — |
| 6 | 可视化驾驶舱 | 未开始 | — | — |
| 7 | 正式验收与发布 | 未开始 | — | — |

---

## 3. Phase 0 环境审计与工程初始化

**状态：PASSED（2026-11-16）。** 结论与完整证据见 [PHASE_ACCEPTANCE.md](./PHASE_ACCEPTANCE.md)；2026-11-16 用户已批准进入 Phase 1，但**仅授权 Stage 1.1 设计**（决策记录见 [PHASE1_ADR.md](./PHASE1_ADR.md) C1）。历史验收过程（含早期 PARTIAL 与 A1–A4 关闭过程）保留在 `PHASE_ACCEPTANCE.md` §7，不因本次修订而改写。

### 3.1 已交付并已验证的核心能力

| 能力 | 证据 |
|---|---|
| SwiftUI 最小 App 构建 | `bash Scripts/build_app.sh` → `** BUILD SUCCEEDED **`（PHASE_ACCEPTANCE §6.1） |
| Sidecar 启动、随机端口、握手 | 集成检查 68 PASS，含握手字段、`pid` 一致、连续两次端口不同 |
| `/health` 正常/降级/401 | 集成检查 68 PASS；真实 curl 401 与统一错误体 |
| SQLite 基础设施 | WAL、`schema_migrations` 仅 1 行、事务回滚、目录 0700/文件 0600 |
| 后端自动化测试 | `pytest tests -q` → 57 passed（43 + 14） |
| 安全边界 | 仅 127.0.0.1、Token 不进日志/argv、`/docs` 关闭 |

### 3.2 关闭 Phase 0 前必须完成

| 任务 | Owner | 验证 |
|---|---|---|
| A1 ADR 归档（ADR-0001…0005） | architect | `Docs/TECHNICAL_DECISIONS.md` 存在且每条有验证结果；§12.1 状态改为"已归档" |
| A2 补写路线图 | architect | 本文件；Phase 1 范围不含评分/事件实现 |
| A3 固化交付物（GIT-01） | 主控 Agent | `git status --short` 为空；新 SHA 上重跑 pytest 57 与集成 68 |
| A4 Swift 测试 target 或 ADR 例外（TEST-01） | macos-developer + architect | 已新增 `PersonalIntelligenceHubTests`；architect 实测 `xcodebuild test` → 35 tests / `TEST SUCCEEDED`（ADR-0009、E11） |

> A1/A2/A4 已关闭；**A3（GIT-01）已于 `ad1c403` 关闭**：工作树干净，新 SHA 上 pytest 57 passed、集成检查 68 PASS / 0 FAIL（2026-11-16 由主控复核）。因此 Phase 0 结论为 `PASSED`，历史 PARTIAL 记录保留在 `PHASE_ACCEPTANCE.md` §7。

### 3.3 明确排除

- 任何业务表、业务 API、采集、AI、事件、评分、搜索、RAG、驾驶舱实现。
- 任何 mock/假数据/占位 UI。
- 多实例运行、登录项常驻、自动更新、签名与公证、发布打包。

**计划书章节**：3、10（Phase 0）、11、12.2、14。

---

## 4. Phase 1 数据底座与信息源管理

| 项 | 内容 |
|---|---|
| 目标 | 建立可迁移、可备份、可回滚的业务数据底座，完成真实信息源的 CRUD 与任务表基础设施 |
| 计划书章节 | 4（数据库与数据治理）、10（Phase 1）、11、12.2、13 |

### 4.1 范围

- **Schema**：从 `0002_*.sql` 起新增业务表；首批候选为 `sources`、`source_categories`、`source_health_logs`、`user_preferences`、`collection_jobs`、`processing_jobs`（字段与最终建表集合以计划书 4.3 与数据契约评审为准，见 [PHASE1_DATABASE_DESIGN.md](./PHASE1_DATABASE_DESIGN.md)）。
- **数据契约**：更新 `DATABASE_BASELINE.md`（或新建数据契约），冻结表、字段、约束、索引、迁移与回滚方式。
- **Repository 层**：所有 API/任务只能经 Repository 访问数据库，禁止散落 SQL。
- **Sources CRUD**：`/api/v1/sources` 的创建、读取、更新、启停、删除（软删除策略必须明确）。
- **分类管理**：`/api/v1/source-categories` 的 CRUD 与引用检查。
- **任务表**：按计划书保留 `collection_jobs` 结构（`pending / running / completed / failed / cancelled` 与幂等任务键）；**Phase 1 不实现采集器，不开放任务 API/UI**，首个写入方为 Phase 2。
- **备份与恢复**：迁移前备份、在线备份 API 或 `VACUUM INTO`、`integrity_check` 校验、恢复演练。
- **健康探测收敛（DB-01）**：`/health` 从 `PRAGMA quick_check` 改为轻量探测（`SELECT 1` + `MAX(version)`），并保留契约字段不变。
- **API 契约更新**：`API_CONTRACT.md` 新增业务端点与错误码。

> **范围裁决（2026-11-16，用户 C2）**：Phase 1 严格保留「数据底座 + 信息源管理」。RSS/Atom 实际采集与文章入库留在 Phase 2；内容去重按 Phase 2 实施；FTS5 全文检索与中文检索优化留在 Phase 5。Stage 1.1 只研究未来数据关系与扩展接口，不落地后续阶段功能。详见 [PHASE1_ADR.md](./PHASE1_ADR.md) ADR-0012。

### 4.2 明确排除

- 任何采集器、文章入库、正文提取、去重（Phase 2）。
- 任何 AI 调用、摘要、分类、Embedding（Phase 3）。
- 事件聚类、事件表、评分、排行榜（Phase 4）。
- FTS5、搜索、RAG、笔记/收藏（Phase 5）。
- 驾驶舱与图表（Phase 6）。
- 以空接口/空表"预留"后续能力。

### 4.3 依赖

- Phase 0 结论为 `PASSED`，且用户已批准进入 Phase 1。
- 数据契约评审通过（表、字段、约束、索引、迁移、回滚）。
- `Docs/TECHNICAL_DECISIONS.md` 中 ADR-0001…0011 已归档。

### 4.4 进入条件（全部满足）

| # | 条件 | 2026-11-16 状态 |
|---|---|---|
| 1 | Phase 0 = `PASSED`（A1–A4 全部关闭，含 GIT-01 与 TEST-01） | **已满足** |
| 2 | **用户书面批准进入 Phase 1** | **已满足**：批准进入，但仅授权 Stage 1.1 设计；Stage 1.2 需再次确认 |
| 3 | 数据契约草案完成并通过 architect 裁决 | Stage 1.1 产出中，待审查 |
| 4 | ENV-01：建立 macOS 14 验证途径，或确认"仅支持当前系统" | **已裁决（C4）**：保留 macOS 14 最低支持目标，实机验证列为发布门禁，见 [MACOS_COMPATIBILITY.md](./MACOS_COMPATIBILITY.md) |
| 5 | 磁盘可用 ≥ 20 GiB，或用户书面接受风险且 Phase 1 禁止模型下载 | **部分满足（C3）**：用户暂时接受 8.6 GiB 用于 Stage 1.1 设计；大规模构建/批量测试前须复核并恢复 ≥20 GiB |
| 6 | 备份与恢复方案可演练（不晚于 Phase 1 退出前） | Stage 1.1 给出方案，Stage 1.2 演练 |

### 4.5 退出条件 / 门禁

- Sources CRUD、事务、外键、唯一约束、迁移测试全部通过。
- 重启后数据保留；失败事务正确回滚；迁移可重复执行且幂等。
- 迁移前备份可生成、可校验、可恢复（至少完成一次真实演练）。
- `DB-01` 关闭：健康探测不再执行全库扫描。
- Repository 边界落地：API/任务代码中无直接拼接 SQL。
- 文档同步：`DATABASE_BASELINE.md`、`API_CONTRACT.md`、`ARCHITECTURE.md` 与实际一致。
- 无 P0/P1 缺陷；qa-security 出具独立测试结论。
- **Stage 1.1 设计文档经用户批准后，方可进入 Stage 1.2 实现**（用户 2026-11-16 明确要求，不得自动越过）。

### 4.6 主要风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Schema 返工 | 迁移不可回滚、数据丢失 | 契约评审 + 迁移前备份 + 小步迁移 |
| SQL 散落 | 后续无法维护/审计 | Repository 收口 + 代码审查 |
| 备份复制主文件 | WAL 事务丢失 | 强制在线备份 API / `VACUUM INTO` |
| 磁盘不足 | 备份失败/构建失败 | 进入前腾出空间；备份保留策略有上限。**当前 8.6 GiB，用户已暂时接受（C3/DISK-01），Stage 1.2 前须复核** |
| macOS 14 未验证 | 兼容性未知 | 保留 14 最低支持；实机验证列为发布门禁（C4/MAC-01） |

---

## 5. Phase 2 多渠道信息采集

| 项 | 内容 |
|---|---|
| 目标 | 以真实来源形成稳定采集闭环：抓取、规范化、正文提取、去重、入库、调度与失败恢复 |
| 计划书章节 | 5（信息采集体系）、4.2–4.3、10（Phase 2）、12.1、13 |

### 5.1 范围

- **Collector Adapter**：RSS / Atom / JSON Feed、网页、GitHub Releases、arXiv；统一 `Article` DTO 与原始元数据。
- **文章表**：`articles`（含 `source_id`、`external_id`、`url`、`canonical_url`、`content_hash`、`published_at`、`fetched_at`、处理状态）；正文大体积内容存本地文件并保留引用。
- **规范化与去重**：canonical URL + 内容指纹 + 跨来源策略；不得只依赖 `UNIQUE(source_id, external_id)`。
- **调度器**：按来源类型设置间隔；ETag / If-Modified-Since；超时、指数退避、重试上限、断点恢复。
- **来源健康**：连续失败降频/暂停，记录原因并在 API 暴露真实状态。
- **安全**：SSRF 防护（协议/解析结果/重定向/响应体大小/类型白名单）、robots.txt 与服务条款、禁止绕过登录/付费墙/验证码。
- **来源预设**：真实验证过的来源清单与验证记录（`Resources/source_presets/**`）。

### 5.2 明确排除

- AI 摘要、分类、关键词、实体、Embedding（Phase 3）。
- 事件聚类、事件表、评分、排行（Phase 4）。
- FTS5 全文检索、RAG、阅读器 UI、知识管理（Phase 5）。
- 驾驶舱与图谱（Phase 6）。
- 用假数据/固定响应冒充采集成功。

### 5.3 依赖

- Phase 1 = `PASSED`。
- 文章数据契约冻结；`SEC-03`（stderr 路径归一化）关闭。
- 来源验证记录可复现（URL、访问方式、许可、速率限制）。

### 5.4 进入条件

1. Phase 1 `PASSED`。
2. 文章 Schema 与 DTO 契约评审通过。
3. 至少 10 个候选来源完成人工验证（可访问、许可允许、稳定）。
4. 采集安全清单（SSRF/robots/速率）写入契约。

### 5.5 退出条件 / 门禁

- **至少 10 个真实来源**持续可用，真实文章入库，原文链接准确可打开。
- 去重有效（精确 + 指纹 + 跨来源），不产生重复文章；重试与退避可验证。
- 采集任务状态、耗时、失败原因可查询；失败可恢复。
- 正文提取质量有抽样记录；不完整正文不冒充完整。
- 无 P0/P1；qa-security 出具独立结论（含 SSRF 用例）。

### 5.6 主要风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 来源结构漂移/失效 | 采集中断 | 健康监控 + 降频 + 预设可更新 |
| 反爬/许可问题 | 合规风险 | 只采允许来源，遵守 robots 与 ToS |
| 去重误判 | 丢文章/合并错误 | 多信号去重 + 抽样验证 |
| 磁盘增长 | 空间耗尽 | 正文文件保留/清理策略 + 容量监控 |
| SSRF/恶意内容 | 本机安全 | 协议/域名/重定向白名单 + 体积限制 |

---

## 6. Phase 3 本地 AI 分析

| 项 | 内容 |
|---|---|
| 目标 | 用本地 Ollama 完成分类、摘要、关键词、实体、Embedding 与结构化输出，并具备降级与可追溯能力 |
| 计划书章节 | 6（本地 AI 分析引擎）、4.2、10（Phase 3）、12.1、13 |

### 6.1 范围

- **Provider 层**：`BaseLLMProvider`（`generate` / `generate_structured` / `embed` / `health_check`）；业务代码不得硬编码模型名。
- **模型注册表**：`ai_model_registry` 记录模型名、版本、上下文长度、内存需求、实测 tok/s。
- **分档落地**：按 ADR-0010 实现轻量/中等/高性能档；Provider 强制模型白名单，**拒绝任何 `*-cloud`**。
- **分析流水线**：文本预处理、分类、摘要与实体、关键词；`article_ai_analysis` 保存结果、模型、Prompt 版本、置信度与时间。
- **结构化输出**：JSON Schema 校验；解析失败有限重试后标记任务失败。
- **Embedding**：`article_embeddings` 记录模型、版本、维度；下载模型需用户确认（AI-01）。
- **任务队列**：`ai_runs`、优先级、并发上限=1、暂停/恢复/取消；Ollama 不可用时不影响阅读与采集。
- **状态端点**：`/api/v1/ai/status`（需先更新 `API_CONTRACT.md`；不得塞入 `/health`）。

### 6.2 明确排除

- 事件聚类、事件创建/合并/拆分、评分与排行榜（Phase 4）。
- RAG 对话、语义检索 UI（Phase 5）。
- 云端模型、任何数据出网路径。
- 把模型推测写成事实；无证据的结论。

### 6.3 依赖

- Phase 2 = `PASSED`；真实文章可分析。
- ADR-0010 已归档；Provider 契约与 JSON Schema 冻结。
- `SEC-01`、`SEC-02`、`AI-01` 处理完毕。

### 6.4 进入条件

1. Phase 2 `PASSED`。
2. `SEC-02`/`RISK-03` 关闭：Provider 白名单拒绝 `*-cloud`，并有测试证明。
3. `SEC-01` 关闭：Ollama 仅监听 `127.0.0.1`，或用户书面接受风险并限制使用范围。
4. `AI-01`：用户确认 Embedding 模型与磁盘占用（约 0.3–1.2 GB）；未确认前语义能力保持禁用。
5. 磁盘与内存检查：下载前 `df` 与 `memory_pressure` 留档；磁盘不足不得下载。
6. Provider 契约（含 `num_ctx` 显式传递）评审通过。

### 6.5 退出条件 / 门禁

- 真实模型调用成功；结构化输出通过 Schema 校验；模型不可用时正确降级。
- 每条分析结果可追溯：模型名、版本、Prompt 版本、参数、耗时、时间。
- 资源实测：单篇耗时、tok/s、内存占用、失败率有真实记录（不得估算冒充实测）。
- 无 `-cloud` 调用：`lsof`/网络观测证明无外连。
- Embedding 可用（若用户已确认）；语义相似度有抽样评测。
- 无 P0/P1；qa-security 出具独立结论（含 Prompt Injection 用例）。

### 6.6 主要风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 模型幻觉/推测 | 错误事实入库 | 事实/观点/推测分离标注 + Schema 校验 |
| 内存压力/换页 | 延迟抖动、系统卡顿 | 单模型常驻、`num_ctx≤4096/8192`、并发=1 |
| 磁盘不足 | 下载失败 | 下载前检查 + 用户确认 + 清理策略 |
| 3.14 依赖兼容 | Provider 库不可用 | 优先纯 Python 依赖；必要时执行 ADR-0001 回退 |
| Prompt Injection | 越权/错误输出 | 内容视为不可信输入 + 系统提示约束 + 输出校验 |

---

## 7. Phase 4 事件聚合与智能排行

| 项 | 内容 |
|---|---|
| 目标 | 将多来源报道聚合为可追溯事件，输出可解释、可重算的评分与排行榜 |
| 计划书章节 | 7（事件中心与智能排序）、4.2–4.3、10（Phase 4）、13 |

### 7.1 范围

- **事件表**：`events`、`event_articles`、`event_timeline`、`event_relations`、`event_entities`、`event_score_history`。
- **聚类**：URL/Hash 精确去重 → 标题相似度 → Embedding 召回 → 时间/实体/主题联合判断 → 必要时 LLM 二次判断。
- **人工校正**：拆分、合并、纠正，保留操作历史；关系类型区分"后续发展/因果线索/同一主体/相关主题"。
- **评分**：`S = 0.25I + 0.20T + 0.20R + 0.15N + 0.10M + 0.10P`（可配置），分项归一化 0–100；保存分项、权重、算法版本、计算时间、理由、证据。
- **排行榜**：综合重要性、当前热度、增长速度、个人关注；支持 1h/24h/7d/30d 与自定义窗口、过滤、排名变化。
- **API**：`/api/v1/events`、`/api/v1/rankings`（先更新契约）。

### 7.2 明确排除

- 阅读器、FTS5、RAG、笔记/收藏（Phase 5）。
- 驾驶舱图表、图谱可视化（Phase 6）。
- 把相关性自动解释为因果；无传播数据时把文章数称为热度。
- 固定分数、不可解释的综合分。

### 7.3 依赖

- Phase 3 = `PASSED`；Embedding 与实体抽取可用。
- 评分 ADR（权重、版本、证据规则、重算策略）已归档。
- 事件数据契约评审通过。

### 7.4 进入条件

1. Phase 3 `PASSED`。
2. 评分算法 ADR 批准（含权重来源、缺失数据时的降级策略）。
3. 事件 Schema、关系类型、证据引用规则冻结。
4. 真实文章量达到可评估规模（数量由用户在计划中确认，不得用测试夹具冒充）。

### 7.5 退出条件 / 门禁

- 同事件报道可聚合；不同事件不被盲目合并（有抽样评估记录）。
- 评分可解释（分项/权重/版本/时间）、可重算、可回看历史。
- 每个事件可追溯到文章证据；关系类型有依据。
- 排行榜窗口与过滤真实有效；排名变化可查。
- 无 P0/P1；qa-security 独立验证聚类误合并与评分篡改。

### 7.6 主要风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 误合并/漏合并 | 事件失真 | 多信号 + 人工校正 + 抽样评测 |
| 评分不可解释 | 违反产品原则 | 强制保存分项与理由；禁止单一总分 |
| 缺少传播数据 | "热度"造假 | 明示数据来源；无数据时降级为"文章数"，不得称热度 |
| 重算成本 | 性能下降 | 增量重算 + 版本化评分历史 |

---

## 8. Phase 5 阅读与知识管理

| 项 | 内容 |
|---|---|
| 目标 | 提供可用的阅读、全文/语义搜索、RAG 问答与知识管理闭环 |
| 计划书章节 | 8（搜索、RAG 与知识管理）、4.4、6.3、10（Phase 5） |

### 8.1 范围

- **阅读器**：三栏布局、原文打开、阅读进度、批注、高亮、AI 解释。
- **搜索**：FTS5 标题/摘要/正文/实体/笔记；中文分词方案验证（默认 `unicode61` 不作为充分方案）；必要时向量召回 + 重排。
- **知识管理**：`bookmarks`、`knowledge_notes`、`annotations`、`topics`、`entities`；笔记与文章/事件/主题关联；Markdown/JSON 导入导出。
- **AI 对话/RAG**：`ai_conversations`、`ai_messages`；检索 → 过滤 → 重排 → 生成；回答必须带 article/event 引用与不确定性说明；证据不足时拒答。
- **API**：`/api/v1/search`、`/api/v1/notes`、`/api/v1/chat`（先更新契约）。

### 8.2 明确排除

- 新的采集器/模型能力（除非为修复缺陷，且需 ADR）。
- 驾驶舱图表与图谱（Phase 6）。
- 发布打包与签名（Phase 7）。
- 无引用的 AI 回答、伪造引用、把推测写成事实。

### 8.3 依赖

- Phase 4 = `PASSED`；文章、事件、实体、Embedding 可用。
- 检索评测集与引用规则冻结。
- 中文分词方案有实测结论。

### 8.4 进入条件

1. Phase 4 `PASSED`。
2. 检索契约与引用格式冻结（article_id、来源、发布时间、URL）。
3. 中文分词方案完成对比测试（至少 2 种方案）。
4. Prompt Injection 防护方案在 RAG 路径中明确。

### 8.5 退出条件 / 门禁

- 原文可打开；搜索对中文有效（有评测记录）；收藏/批注/笔记持久化。
- AI 回答引用真实文章，可点击打开；无证据时明确拒答。
- 导出格式可用且可重新导入（至少 Markdown）。
- 无 P0/P1；qa-security 独立验证越权、注入与引用错配。

### 8.6 主要风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 中文分词不佳 | 搜索不可用 | 分词对比 + 自定义词典 + 评测集 |
| 检索召回不足 | RAG 答非所问 | 混合检索 + 重排 + 拒答策略 |
| 引用错配 | 可信度崩塌 | 引用 ID 校验 + 展示原始链接 |
| 长文上下文超限 | 截断/遗漏 | 分块 + 摘要 + 明确不确定性 |

---

## 9. Phase 6 可视化驾驶舱

| 项 | 内容 |
|---|---|
| 目标 | 以真实数据呈现总览、情报分析、趋势、时间线与事件图谱，并满足交互性能 |
| 计划书章节 | 9（UI/UX 产品结构）、13（性能与可观测性）、10（Phase 6） |

### 9.1 范围

- **页面**：Overview、Intelligence、Analytics、Events（Overview/Sources/Timeline/Relations）。
- **可视化**：趋势、热力、地图、实体与事件图谱、排名变化。
- **性能**：布局与绘制分离、视口裁剪、增量更新、节点抽稀；重活不阻塞主线程。
- **API**：`/api/v1/analytics` 聚合查询与缓存策略（先更新契约）。
- **五态**：Loading / Empty / Error / Offline / Partial Data 全部真实实现。

### 9.2 明确排除

- 新增数据语义或"为了图表好看"的派生指标。
- 静态图谱、无依据地理位置、假趋势。
- 发布打包（Phase 7）。

### 9.3 依赖

- Phase 5 = `PASSED`；真实数据量与查询路径稳定。
- 性能基线方法（Instruments/日志）确定。

### 9.4 进入条件

1. Phase 5 `PASSED`。
2. 聚合查询契约与缓存策略评审通过。
3. 真实数据规模足以做性能测试（规模由用户确认，不得用夹具冒充）。

### 9.5 退出条件 / 门禁

- 图表全部来自真实数据；筛选有效；空态/错误态真实。
- 图谱在分级节点量下完成帧率/响应实测，并记录设备与数据规模。
- 地理位置有依据（来源字段），否则不展示地图。
- 主线程无阻塞（Instruments 证据）。
- 无 P0/P1；qa-security 独立验证 UI 真实性与性能。

### 9.6 主要风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 图谱性能 | 卡顿/崩溃 | 布局与绘制分离 + 抽稀 + 视口裁剪 |
| 图表误导 | 错误决策 | 明确口径、样本量与时间窗 |
| 16 GiB 内存限制 | 多视图并发卡顿 | 按需加载 + 缓存上限 |

---

## 10. Phase 7 正式验收与发布

| 项 | 内容 |
|---|---|
| 目标 | 完成端到端验收、性能与稳定性基线、安全与备份恢复演练、打包发布 |
| 计划书章节 | 10（Phase 7）、11、12、13、14 |

### 10.1 范围

- **端到端**：从采集到阅读/搜索/事件/评分的完整业务闭环。
- **性能与稳定性**：长时间运行、内存/磁盘增长、失败恢复、并发上限。
- **安全**：依赖 CVE 与许可证审计（SEC-06）、Token 传递强化评估（SEC-04）、Prompt Injection/SSRF 回归。
- **备份恢复**：真实删除/损坏主库后的恢复演练。
- **打包**：Sidecar 打包方案 ADR（不得依赖系统 Python）、签名与公证、安装说明。
- **文档**：README、用户手册、故障排查、CHANGELOG、阶段验收报告、性能基线、安全检查报告。

### 10.2 明确排除

- 任何新功能或范围扩张。
- 用"已知问题"掩盖 P0/P1。
- 未实测的性能承诺。

### 10.3 依赖

- Phase 6 = `PASSED`。
- 所有阶段遗留项（第 11 节）关闭或有用户书面接受的残余风险。
- 打包 ADR 批准。

### 10.4 进入条件

1. Phase 6 `PASSED`。
2. 打包与签名方案 ADR 批准。
3. 磁盘与构建环境满足发布要求（含干净机器安装测试条件）。

### 10.5 退出条件 / 门禁

- 关键业务闭环通过；无 P0/P1 阻断问题。
- 发布包可在干净环境安装并运行（不依赖开发机 Python/venv）。
- 备份恢复演练成功；长期运行无泄漏/崩溃。
- 依赖 CVE 与许可证核对完成（SEC-06）。
- 文档完整且与实现一致。
- architect 发布 Phase 7 `PASSED` 结论。

### 10.6 主要风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 系统 Python 依赖 | 发布版不可用 | Phase 7 前完成打包 ADR |
| 签名/公证 | 无法分发 | 提前验证证书与流程 |
| 长期运行泄漏 | 稳定性问题 | 长跑测试 + 资源监控 |
| 磁盘不足 | 安装/更新失败 | 发布前容量检查 |

---

### 10.7 已交付的 Phase 7.x 子阶段（2026-11-17）

| 子阶段 | 状态 | 交付 |
|---|---|---|
| 7.0 全局 UI/UX 现代化 | PASS（0.8.0） | 统一设计系统；侧边栏分组；驾驶舱/文章/阅读/事件/信息源/状态改造；深浅色与小窗口实机验收 |
| 7.05 正式安装 0.8.0 | PASS（0.8.0） | Release universal + Sidecar Bundle + adhoc 签名；DMG；`/Applications` 安装与真实运行验证；数据库备份 |
| 7.1 智能情报中心 | PASS WITH CONDITIONS（0.9.0） | Migration 0008；真实统计层；分层 AI 生成与引用白名单；去重/取消/恢复/降级；五视图 UI + 溯源跳转；后端 406 测试 |

7.1 的条件项：单份报告 60–75 秒（4B 模型）、统计按 UTC 日期、安装版仍为 0.8.0。
Phase 7 正式发布（0.9.0 打包安装、公证、独立 Python 运行时、性能与安全基线）仍按 10.1–10.5 门禁执行。

---

## 11. 遗留项 → 应关闭 Phase 映射

| 编号 | 级别 | 内容 | 必须关闭于 | 关闭判据 |
|---|---|---|---|---|
| DOC-01 | P2 | ADR 正文与路线图缺失 | **Phase 0** | 本文件 + `TECHNICAL_DECISIONS.md` 落盘，architect 复核 |
| GIT-01 | P2 | 已验证修复与测试资产未提交 | **Phase 0** | `git status --short` 为空；新 SHA 重跑 pytest 57 与集成 68 |
| TEST-01 | P2 | 无 Swift 测试 target | **Phase 0** | 已满足工程侧判据：`xcodebuild test` 35 passed / `TEST SUCCEEDED`（ADR-0009）；待 `PHASE_ACCEPTANCE.md` 复核关闭 |
| ENV-01 | P2 | macOS 14 未实机验证 | **Phase 1 进入前** | 建立 14.x 验证途径，或用户确认"仅支持当前系统"并记录 |
| DB-01 | P3 | `/health` 使用 `PRAGMA quick_check` | **Phase 1** | 改为 `SELECT 1` + `MAX(version)`，契约字段不变 |
| SEC-03 | P3 | stderr 尾部暴露绝对路径/traceback | **Phase 2 进入前** | 路径归一化或诊断信息脱敏 |
| SEC-01 | P2 | Ollama 监听 `0.0.0.0:11434` | **Phase 3 进入前** | 约束为 `127.0.0.1`，或用户书面接受风险 |
| SEC-02 | P2 | 无模型白名单，存在 `-cloud` 误用 | **Phase 3 进入前** | Provider 白名单拒绝 `*-cloud`，测试证明 |
| RISK-03 | P1 风险 | `-cloud` 模型存在 | **Phase 3 进入前** | 同 SEC-02 |
| AI-01 | P2 | 无 Embedding 模型 | **Phase 3 内（需用户确认）** | 下载并实测；未确认前语义能力禁用 |
| RISK-01 | P1 风险 | 磁盘可用约 11 GiB | **全程；Phase 3 下载前必须复核** | 保持 ≥ 20 GiB（或书面接受限制 + 禁止下载） |
| DISK-01 | P1 风险 | 磁盘可用降至 8.6 GiB（2026-11-16 实测） | **Stage 1.2 前** | 用户已暂时接受并仅授权 Stage 1.1 设计；Stage 1.2 前复核并恢复 ≥20 GiB，否则不得批量构建/采集 |
| MAC-01 / ENV-01 | P2 | macOS 14 未实机验证 | **Phase 7 发布前（发布门禁）** | 按 `MACOS_COMPATIBILITY.md` 完成虚拟机或实机验证；静态审计不等于实机验证 |
| OLL-01 | P2 | Ollama 监听 `*:11434`，`OLLAMA_NO_CLOUD=0` | **Phase 3 进入前** | 用户已批准收敛至 `127.0.0.1`；执行前完成局域网依赖确认并保留回滚方案（ADR-0014） |
| RISK-02 | P1 风险 | Python 3.14 兼容风险 | **Phase 0 归档；Phase 1 起持续回归** | ADR-0001 归档；依赖变更时重跑全套测试 |
| SEC-04 | P3 | Token 环境变量对同用户可见 | **Phase 7 前评估** | 保持现状并记录，或 ADR 改为 fd/管道传递 |
| SEC-06 | 信息 | 未核对依赖 CVE | **Phase 7** | 依赖审计与许可证核对完成 |
| QA-05 | P3 | QA 报告独立署名缺位 | **每个后续阶段** | qa-security 独立执行并署名 |

---

## 12. 阶段门禁检查单（复制使用）

进入下一阶段前，architect 必须逐项确认：

- [ ] 上一阶段 `PHASE_ACCEPTANCE.md` 结论为 `PASSED`。
- [ ] 本阶段退出条件全部有可复现证据（命令/测试计数/截图/DB 记录）。
- [ ] 本阶段应关闭的遗留项（第 11 节）已关闭。
- [ ] 无 P0/P1 缺陷；P2 遗留有明确关闭 Phase 与 owner。
- [ ] API/数据/事件契约与实际实现一致。
- [ ] `ARCHITECTURE.md`、`TECHNICAL_DECISIONS.md`、本文件与实现一致。
- [ ] 未引入 mock、假数据、占位按钮、固定评分。
- [ ] 未承诺未实测的吞吐/规模/准确率。
- [ ] 用户已批准进入下一阶段（Phase 1 必须书面批准）。

---

## 13. 变更规则

1. 阶段范围、顺序或退出条件变更：先更新本文件与计划书对应章节，经用户确认后实施。
2. 阶段标准变更必须写 ADR（背景、选项、成本、迁移影响、验证结果）。
3. 任何"提前实现后续 Phase 能力"的行为视为越界交付，必须回退。
4. 阶段结论只写入 `Docs/PHASE_ACCEPTANCE.md`，本文件不发布 PASSED/BLOCKED 结论。
