# Changelog

本文件记录 PIH（Personal Intelligence Hub）的重要变更。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

Phase 7.6（跨来源事件聚合与推荐质量）与 Phase 7.7（电力行业网页适配器）。最终版本 `0.14.0`，Schema 12；无破坏性 API 变更。

### Phase 7.6 Added

- `event-aggregate-v1` 事件聚合层：文章→事件、事件→事件、未归属文章组→新事件，与入库去重和 `event-cluster-v1` 解耦。
- `GET /api/v1/event-aggregation/status`、`GET /dry-run`（只读）、`POST /apply`（confirm + 自动备份 + 重算校验 + 审计）。
- 日报事件级 `event_detail`：代表文章、其他报道、最新进展、信息增量、事件重要性；SwiftUI 可展开其他来源。
- 审计脚本：`Scripts/phase7_6_dry_run.py`、`phase7_6_validation_sample.py`、`phase7_6_metrics.py`、`phase7_6_apply.py`。

### Phase 7.6 Changed

- `must_not_miss` 最多预留 2 个事件位，同一事件只占一个日报位置。
- 聚合对缺失 AI 信号做可用信号归一化；同源近似标题作为 duplicate 成员，不拒绝整组。

### Phase 7.6 Verified

- 真实库 Dry Run：131 个文章组合并对、2 个事件合并、1 个文章→事件；79 组、185 篇。
- 120 对分层人工标注：Precision 1.0000 / Recall 0.7895 / F1 0.8824 / 误合并 0 / 漏合并 21.05%。
- 生产 Apply：文章 2 387 不变、事件 527→623、事件关联 548→754、跨来源事件 20→122；102 次审计操作；完整性 `ok`。
- 45 条推荐人工评估：强烈推荐 1 / 值得阅读 25 / 一般 15 / 不感兴趣 4 / 重复 0；未修改推荐权重或阈值。
- 后端 pytest **519 passed**；XCTest **69 passed**；Release 0.14.0 构建、签名、安装并真实运行。
- 文档：`Docs/PHASE7_6_*`（5 份）。

Phase 7.7（电力行业网页适配器）。Schema 12，新增一张适配器配置表；无破坏性 API 变更。

### Added

- Migration `0012_source_adapters.sql`：`source_adapter_configs`。
- `html_list` 采集器：列表页链接提取、详情页标题/日期/正文、分页与限流。
- 适配器 API：读取、写入、删除、dry-run（不落库）。
- 首批 3 个电力源：国家能源局、中国电力报、中国能源报。
- `find_existing` 支持匹配软删除文章，避免保留策略后的重复回插。
- Phase 2：网页适配器配置面板、分页跟随、全文开关、适配器漂移状态与列表告警。

### Changed

- 可采集来源从 RSS/Atom 扩展到“存在网页适配器的 website/official_announcement/api”。
- 采集任务按来源类型分派 RSS 路径或网页适配器路径。
- 版本升级 `0.14.0`。

### Fixed

- 保留策略软删除旧文章后，下一轮采集重新插入同一文章的问题。
- 网页标题尾部站点后缀（`--中国能源新闻网`）未清理。

### Verified

- 3 个来源各连续 3 次 dry-run 均解析 3 条且 verified。
- 首采 36 篇；后续采集 0 新增 / 36 重复；第二次 7 篇为真实新增。
- 国家能源局、中国电力报 robots.txt 为 404（无规则）；中国能源报 `Allow: /`。
- 生产分页：中国电力报 `max_pages=2`；国家能源局/中国能源报无稳定分页，保持 1。
- 适配器漂移：有条目 → verified；0 条且阻断 → blocked；0 条非阻断 → selector_drift。
- 后端 pytest **520 passed**；XCTest **69 passed**；Release 0.14.0 构建、签名、安装并启动。
- 文档：`Docs/PHASE7_POWER_WEB_ADAPTER.md`。

Phase 7.5（国内信息源扩充与全局去重）。无 Schema / API 破坏性变更；推荐权重与阈值未修改。

### Added

- 3 个经真实验证的国内信息源：雷峰网、智东西、爱范儿。
- 采集第 4 层去重：同源 + 标题规范化 + 发布时间 ±15 分钟。
- 兴趣「AI for Science 与科学智能」；电力/人工智能/前沿科技中文关键词补充 193 个。
- 6 份国内源审计、候选、导入、画像、推荐与数据完整性文档。

### Changed

- 电力核心兴趣删除 9 个过泛词（电力、能源、电网、发电、用电、电价、绿电、水电、新能源），补充 30+ 复合词。
- 国内新增源优先级/可信度：B 级 55/78，C 级 35/65。

### Fixed

- 同一 Feed 以不同 GUID/URL 重复推送同一标题时重复入库。
- GPU、Token 工厂、主板等算力文章被误判为电力行业内容。

### Verified

- 65 个国内机构/站点审计；3 个国内源导入；首采 45 篇；二次采集 0 新增/45 重复。
- 后端 pytest **502 passed**；XCTest **69 passed**；Release 构建、adhoc 签名与安装成功。
- 45 篇国内文章推荐：recommended 37、watch 4、low 4；无电力行业样本。
- 文档：`Docs/PHASE7_DOMESTIC_SOURCE_DEDUP_AUDIT.md`、`PHASE7_DOMESTIC_SOURCE_CANDIDATES.md`、`PHASE7_DOMESTIC_SOURCE_IMPORT_REPORT.md`、`PHASE7_INTEREST_PROFILE_UPDATE.md`、`PHASE7_DOMESTIC_RECOMMENDATION_VALIDATION.md`、`PHASE7_DATA_INTEGRITY_REPORT.md`。

Phase 7.4（RSS 信息源扩充、个人兴趣画像初始化）与 7.3.3（信息源与文章量控制）。无破坏性 API 变更；推荐算法权重与阈值未修改。

### Added

- Migration `0011_article_volume.sql`：`sources.max_entries_per_fetch`（1–100，可空）。
- 文章保留策略：默认 30 天，软删除；收藏、稍后阅读、事件证据永久保护。
- 33 个经真实验证的 RSS/Atom 源：电力能源 11、人工智能 11、前沿科技 9、综合科技 2。
- 来源路由分类：电力能源、人工智能、前沿科技、综合科技。
- 兴趣画像：3 个核心兴趣、17 个二级主题、2 个实体关注，共 23 个兴趣、436 个关键词。
- 信息源 API：`language` 过滤、`article_count` 字段。
- UI：语言筛选、单源文章数、最近错误、单次入库上限。

### Changed

- 采集按源配置上限，按发布时间倒序保留最新条目。
- `personalization` 关键词匹配：CJK 字符视为英文关键词边界。
- 停用 `healthy` 源时同步重置健康状态，避免 CHECK 约束失败。

### Fixed

- 中文混排中 `AI`、`GPU` 等英文关键词漏匹配。
- `RAN` 关键词误命中英文动词 `ran`，导致无关文章进入通信主题。
- 电力、通信、半导体关键词覆盖不足。

### Verified

- 123 个候选 Feed，41 个可解析，33 个导入；30 个首采成功，395 篇入库，保留策略软删除 50 篇。 
- 345 篇新文章全部生成推荐：recommended 219、watch 92、low 34、must_read 0。
- 后端 pytest **501 passed**；XCTest **69 passed**；Debug/Release BUILD SUCCEEDED；0.12.0 已安装。
- 文档：`Docs/PHASE7_RSS_SOURCE_AUDIT.md`、`PHASE7_RSS_IMPORT_REPORT.md`、`PHASE7_INTEREST_PROFILE.md`、`PHASE7_RECOMMENDATION_VALIDATION.md`、`PHASE7_DATA_INTEGRITY_REPORT.md`。

Phase 7.3.2（Personal Intelligence Feed UI/UX 深度重构）。无 Schema / Migration / API 破坏性变更；推荐算法、评分、阈值与历史数据未修改。

### Added

- 情报流组件：`LevelPill`、`FeedTargetBadge`、`InterestChip`、`InterestTagRow`、`FeedMetaLine`、`RecommendationReasonLine`、`ScoreBreakdownPopover`、`FeedbackMenu`、`RecommendationActions`、`RecommendationRow`、`FeaturedRecommendationCard`、`EventRecommendationCard`、`ArticleLeadCard`、`ReadingBudgetControl`。
- 语义色：`PIHColor.info/positive/warning/danger/neutral`。
- 「为我筛选」兴趣导航（真实条数、可筛选、可进入编辑）、紧凑三指标概览、快捷阅读预算（5/10/20/自定义）。
- 今日必读主推荐与克制空状态；事件 / 独立新闻线索 / 文章类型明确区分。
- `feed` 与推荐详情新增真实 `summary`（AI 摘要优先，回退文章摘要，截断 400 字符）。
- 独立新闻线索：当后端 `leads` 被预算挤入观察区时，按真实 `targetType/eventId/score` 提升高分文章，并从折叠区去重。

### Changed

- 侧边栏：品牌区、分组标题、行对比度与运行状态区更紧凑；列宽 208–280 pt。
- 每日精选改为编辑式简报：概览、编号分区、整行可点击、折叠“更多重点”、历史日期。
- 兴趣画像：新增兴趣概览与等级筛选；阅读预算增加快捷预设。
- 卡片评分降为辅助信息；“评分依据”改为轻量 Popover，未评估项明确标注。
- 工具栏与概览在窄窗口自动切换为图标按钮/堆叠布局；最小窗口约 928 pt。

### Fixed

- 推荐卡片摘要缺失（此前只有标题与理由）。
- 事件与单篇文章视觉混淆；单篇线索不再被展示为多源事件。
- 每日精选条目标题点击区域过小（改为整行可点击）。
- 评分依据 Popover 背景透明导致文字穿透。

### Verified

- 后端 pytest **495 passed**；XCTest **69 passed**；Debug/Release **BUILD SUCCEEDED**。
- 真实运行截图 12 张：1280×800、1024×700、928×700、深色、兴趣筛选、评分依据、日报、兴趣画像/编辑器、独立线索。
- 数据核对：72 条 feed、10 条首选、0 条必读（80 分仍为推荐）、40 分钟估算、400 事件/477 独立文章、日报 14 条。
- 交互核对：兴趣筛选、刷新、日报条目跳转、事件卡跳转、文章阅读、折叠展开、评分 Popover。

### Known Limitations

- 相似信息组（未确认合并）与事件内文章展开需要后续 API。
- 1440×900 受当前 1280×832 pt 显示器限制，未物理验证。
- 未在本次验收中写入生产库（反馈/预算），由既有后端测试覆盖。

Phase 7.7 Reader（文章阅读中心 UI/UX 深度优化）。纯前端 UI 修订，无 Schema / API / 后端变更，版本仍为 `0.14.0`。

### Added

- 阅读器组件层 `ArticleReaderComponents.swift`：字号档位、自适应阅读宽度、标题区、摘要区、正文区、AI 分析区、来源区与固定工具栏。
- 阅读字号小/中/大三档，`@AppStorage("pih.reader.text-size")` 本地持久化。
- 阅读器固定操作栏：收藏、阅读状态、分析、原文、字号、更多（复制标题/链接、兴趣反馈）。
- 操作结果轻提示（成功/失败），2.6 秒自动消失。
- 文章列表摘要校验：占位摘要（如「点击查看原文」）不再显示。

### Changed

- 文章阅读页改为「标题 → 来源与时间 → 摘要 → 正文 → AI 辅助分析 → 来源与原文」的阅读层级；阅读行宽 760–820 pt、随面板宽度在 20/32/44 pt 边距间切换。
- 摘要与正文按真实句子边界分段；正文与摘要完全重复时不再重复展示。
- 无正文时使用紧凑空状态（说明来源仅提供摘要 + 阅读原文），不再显示技术性错误文案与大型空白区。
- AI 分析区去除大面积强调底色，改为可折叠卡片；只展示现有真实字段（主题、摘要、关键词、实体、模型、时间、置信度）。
- 元数据、来源 URL 弱化并收进「文章信息」折叠区；切换文章时阅读位置回到顶部。
- 列表行增加留白、标题最多 3 行，移除每行的「仅摘要」标签以降低噪声；中间列表宽度 340–480 pt。

### Fixed

- 长摘要以连续密集长段落展示，缺少段落层级。
- 摘要与正文重复展示（arXiv 等源 summary 与 content_text 相同）。
- 「服务端仅提供摘要，未提供正文纯文本」被当作正文内容展示。
- 阅读操作失败只在列表顶部报错、详情页无反馈。

### Verified

- XCTest **85 passed**（新增 16 个阅读器文本/布局测试）；Debug/Release **BUILD SUCCEEDED**。
- 真实应用验证：1280×800 与最小 1208×760；深色/浅色；长标题、超长多段摘要、无摘要、无正文、完整正文、AI 已完成/未分析、收藏/已读切换、更多菜单复制、字号切换与持久化。
- 截图 9 张：`Docs/PHASE7_7_SCREENSHOTS/`（含优化前 2 张）。

### Known Limitations

- 部分源的 `content_text` 含站点导航/页脚文本，阅读器按原样展示，未做正文抽取清洗。
- 生产库当前仅 1 篇 AI 分析结果，AI 完成态在单篇真实数据上验证。
- AI 分析未提供「关键事实 / 关联事件 / 重要性判断」结构化字段，本次未展示这些模块。
- 服务端无「阅读中」独立动作，工具栏不提供该状态切换。

## [0.11.0] - 2026-11-18

Phase 7.3.1（Personal Intelligence Feed：个人兴趣画像与智能信息筛选）。新增 Migration `0010`（schema 10，10 张纯新增表）；App/后端/契约版本统一到 `0.11.0`。

### Added

- **兴趣画像**：`interest_profiles` / `interests` / `interest_keywords` / `interest_entity_links` / `interest_source_links` / `blocked_sources`。四级关注（核心/延伸/一般/暂不关注）、权重、领域键（taxonomy-v1）、关键词与排除词、关联既有实体与来源、屏蔽来源、阅读预算（条数/分钟）、探索比例、评分阈值覆盖、隐私重置。
- **推荐算法 `personal-reco-v1`**：兴趣 35% + 事件重要性 25% + 新颖性 15% + 来源质量 15% + 时效 10%；五档分层（必读/推荐/观察/低优先级/不推荐）；重大事件兜底；反馈即时调整；理由码、警告与五维拆解全部持久化。
- **事件级推荐与去重**：事件为推荐单位、文章为证据；事件成员不重复推荐；未进事件的高分文章可独立推荐；被屏蔽来源或已入事件的旧结果自动失效。
- **反馈与自适应建议**：`recommendation_feedback`（追加写 + 软撤销）；感兴趣/不感兴趣/非常重要/重复内容/不喜欢来源/暂不处理；≥3 次同类反馈生成权重与等级建议，用户点击后才应用。
- **每日精选**：`daily_digests` / `daily_digest_items`；六分区（不容错过/重点/核心兴趣/事件变化/新兴主题/独立线索）；阅读预算约束；同日幂等；`force` 重生成保留 `superseded` 历史；时区按画像。
- **API**：`/api/v1/personalization/*`（画像、兴趣、关键词、实体/来源关联、屏蔽来源、信息流、推荐详情、反馈、建议、统计、重置）与 `/api/v1/digest/*`（今日、日期、生成、历史）。
- **SwiftUI**：侧边栏「为我筛选」并设为默认首屏；信息流卡片（等级、分数、匹配兴趣、理由、评分依据、反馈）；兴趣画像与编辑器；每日精选弹窗；驾驶舱摘要卡；文章详情反馈菜单。
- **Pipeline 集成**：事件任务完成后规则刷新推荐（无模型调用，失败不影响任务）。

### Changed

- `MARKETING_VERSION` 0.10.0 → 0.11.0；后端 `VERSION` 与契约展示版本同步；新增 `0010` 迁移。
- 默认首屏从驾驶舱改为「为我筛选」（驾驶舱仍可一键进入）。

### Fixed

- 事件成员特征查询缺少 `summary` 导致真实数据重算崩溃。
- 信息流首帧早于 Sidecar 握手，永久停留“正在连接”（改为跟随 state 重试）。
- 事件推荐卡显示“未知来源”，改为显示真实文章数与来源数。
- 日报未受阅读预算约束，推荐条目按预算截断，溢出保留在折叠区。

### Verified

- 后端 pytest **495 passed**（新增 38）；XCTest **69 passed**（新增 5）；Debug/Release BUILD SUCCEEDED。
- 真实数据副本：400 事件 + 400 独立文章评分；信息流 72 条（60 推荐 / 12 观察）；日报 14 条；全部来源可信度缺失时中性标注。
- 反馈实测：81.1 → 93.1（非常重要，必读）；不感兴趣 −25；撤销恢复；阈值调至 80 时必读 7 条。
- 0.11.0 已安装（universal、adhoc 签名通过），安装包 Sidecar `/health` 返回 `schema_version=10`、真实 commit 与构建时间。
- 生产库 Schema 10、文章 1683、事件 527、分析 447 未被清空；`phase731` 备份 `integrity_check=ok`。

### Known Limitations

- 来源 `credibility_score` 仍为空，来源维度只能中性处理。
- 事件评分上限约 64，未反馈时难以自然达到必读（可反馈或调阈值）。
- 日报为规则生成，暂无 AI 概览；历史日期按当前数据生成。
- 兴趣画像与日报弹窗未做自动化 UI 测试。

## [0.10.1] - 2026-11-18

Phase 7.2.1（生产运行验收与自动化小规模试运行）。版本仍为 App/后端 `0.10.0` 契约，内部修订 `0.10.1`；**无新 Migration**（schema 保持 9）。自动化最终仍为关闭。

### Added

- **构建元数据注入**：`Scripts/build_metadata.py` 生成 `Backend/build_meta.json`（commit / branch / dirty / build_time），`build_app.sh` 与 `package_sidecar.sh` 接入；`Backend/core/version.py` 按 env → 包内 `build_meta.json` → `unknown` 解析，未提交代码显示为 `<commit>+dirty`。Release 包运行时不依赖 git 仓库。
- **测试隔离保护**：`Backend/database/paths.py` 在 pytest 环境下拒绝解析生产数据目录；`Backend/tests/data/test_test_isolation.py` 3 个回归用例。
- **文档**：`Docs/PHASE7_2_1_PRODUCTION_BASELINE.md`、`PHASE7_2_1_CLASSIFICATION_REVIEW.md`、`PHASE7_2_1_SMOKE_TEST_REPORT.md`、`PHASE7_2_1_BACKFILL_REPORT.md`、`PHASE7_2_1_RECOVERY_TEST.md`、`PHASE7_2_1_LIVE_AUTOMATION_REPORT.md`、`PHASE7_2_1_FINAL_ACCEPTANCE.md`。

### Fixed

- **`retry_wait` 任务永久卡住（阻断级）**：`claim_ready` / `claim_stage` / `has_ready_backfill` 现在会领取退避到期的 `retry_wait` 任务；`_park` 把崩溃后处于 `event_score/refresh` 的任务重新挂到 `event_match`。租约过期、AI 超时、瞬时失败后可自动重试。
- **XCTest 宿主迁移生产数据库**：Swift 测试宿主检测到 XCTest 后不再自动启动开发版 Sidecar。
- **Release 签名失效**：Sidecar 注入 `PYTHONDONTWRITEBYTECODE=1`，打包脚本清理 `__pycache__`，运行后 `codesign --verify --deep --strict` 仍通过。

### Verified

- 生产基线：文章 1260 → 1656（外部采集）、事件 502 → 527、分析 424 → 447、实体 593 → 657；软删除 0、人工事件 0 被覆盖。
- 备份：`pih-20261118T030510505792Z-phase721.sqlite3`，`integrity_check=ok`，行数与 SHA-256 核对一致。
- 5 篇烟雾测试：5/5 succeeded，Ollama 6.1–12.5 s/篇；重复入队、重复 AI、重复聚类均无重复数据。
- 20 篇回填：4 批，17 succeeded / 2 skipped（内容不足）/ 1 failed（`schema_invalid`，3 次尝试），无重复关联与无意义评分。
- 进程恢复：正常退出、等待退出、AI 中 SIGKILL、阶段转换中断、重复触发 5 个场景在独立副本全部通过。
- 实时自动化：真实新增 5 篇文章 → 5 个任务自动执行（4 成功、1 跳过）；试运行后恢复关闭。
- 测试：后端 pytest **457 passed**；XCTest **64 passed**；Debug/Release BUILD SUCCEEDED。
- 安装：`/Applications/Personal Intelligence Hub.app` 0.10.0，universal、adhoc 签名通过，数据库未被清空/重建；`/health.build` 返回真实 commit 与 build time。

### Known Limitations

- Sidecar 无单实例锁：并发实例会互相标记运行中的 AI 任务为中断（本阶段实测一次，自动恢复）。
- 224 条分类建议仍未 Apply（需用户授权）；103 条 unresolved 保留。
- 历史全量回填（当前待处理 934+ 篇）未执行。
- 实时自动化仅在 5 分钟窗口验证，长周期稳定性待日常使用观察。

## [0.10.0] - 2026-11-18

Phase 7.2（数据基线校准与自动化管道）。版本 `0.10.0`；新增 Migration `0009`（schema_version 9）。App / 后端 / 契约版本统一；自动化默认关闭。

### Added

- **持久化管道**：`pipeline_tasks / pipeline_task_logs / pipeline_settings / pipeline_runs`。一篇文章一个任务，幂等键 `article_pipeline:<id>`，状态机 `pending/ready/running/retry_wait/succeeded/failed/skipped/cancelled`，阶段 `quality_check → ai_analysis → entity_sync → event_match → event_score → refresh → done`。
- **Pipeline Orchestrator**（`services/pipeline_orchestrator.py`）：单 worker、批量上限、租约与过期恢复、指数退避、AI 调用间隔节流、暂停/恢复、人工重试/取消、历史回填批次。只调度既有 AI/实体/聚类/评分服务。
- **采集联动**：`CollectionService` 新文章入库后通知 Orchestrator；自动化关闭时不创建任务。
- **统一分类字典** `taxonomy-v1`（`event_intelligence/taxonomy.py`）：十领域 + 八主题 + 来源路由；`scoring` 改用字典基分，未知分类使用中性 40。
- **分类一致性**（`services/classification_service.py`）：事件成员加权投票（主文章 ×2）、`category_source/category_reason/category_updated_at`、人工保护、审计、Dry Run 与显式 Apply（先备份再事务）。
- **API** `/api/v1/pipeline/*`：总览、状态、设置、控制、任务列表/详情/日志、重试/取消、回填预览/创建、批次、分类字典/报告/Apply。
- **SwiftUI 任务中心**：侧边栏「自动化管道」，六视图（总览/正在处理/等待处理/失败任务/历史记录/自动化设置）；任务详情含阶段进度、错误、输入/输出摘要与日志。
- **版本与观测**：`/health` 增加 `build.git_commit` / `build.build_time`；状态页展示 App 版本、后端版本、Git Commit、构建时间、Schema。

### Changed

- `MARKETING_VERSION` 0.9.0 → 0.10.0；后端 `VERSION` 0.5.0 → 0.10.0；schema_version 8 → 9；契约展示版本同步。
- `events` 新增分类来源列；`EventRecord` 暴露新字段；人工修改分类写入 `manual`。
- 事件聚类在成员变化后重算事件分类；管道完成时对既有事件再次重算，修复“后补分析不更新分类”。
- Schema 与版本断言测试同步到 9 / 0.10.0。

### Fixed

- 已归属事件的文章在历史回填后补 AI 分析时，事件分类不会从“其他”更新为真实领域；现在会重算并生成审计。
- 未知分类不再被统一压到最低基分 20，避免系统性低估。

### Verified

- 真实数据库只读 Dry Run：502 事件中 224 个建议变更（其他→科技 217、健康 5、教育 1、财经 1）、103 个待确认、0 个人工保护；未执行 Apply。
- 真实数据库副本端到端：MIT Tech Review 全文 5712 字符 → Ollama 13.1s → 实体同步 → 事件匹配 → 分类修正 → 评分刷新 → `succeeded`。
- 后端 pytest **451 passed**；XCTest **64 passed**；Debug/Release BUILD SUCCEEDED。
- Release 0.10.0 + Sidecar 0.10.0 已安装，Sidecar `/health` 返回 `schema_version=9`、`automation=false`；旧版 0.8.0 回滚副本保留。

### Known Limitations

- 历史 869 篇回填与 224 个分类修正需要用户显式操作。
- 正文抓取、AI 事件判定、LaunchAgent 常驻仍属后续阶段。
- 未做真实进程强杀/退出中断演练；构建 commit 尚未由打包脚本注入。

## [0.9.0] - 2026-11-17

Phase 7.1（智能情报中心）。版本 `0.9.0`；新增 Migration `0008`（schema_version 8）。所有结论可追溯到事件与原始文章，数字全部来自 SQLite。

### Added

- **情报数据层**：`intelligence_reports`（报告、状态机、数据区间、模型与 Prompt 版本、去重锚点）与 `intelligence_report_citations`（事件/文章引用，级联删除）。同周期唯一索引防止重复生成。
- **统计层** `services/intelligence_stats.py`（`intelligence-stats-v1`）：文章/来源/事件计数、分类环比、上升关键词、多来源主题、新实体、高频实体、事件证据、事件关系、未聚合报道。
- **分层生成** `ai_engine/intelligence.py` + `services/intelligence_service.py`：逐事件简报（小上下文）→ 汇总（标题/概要/主题/不确定性）；引用白名单校验，未知 ID 与无证据主题直接丢弃；Ollama 不可用或输出非法时降级为仅统计报告，不回退云端。
- **任务控制**：单并发 Worker、取消、重启恢复（残留 `pending/running` 标记失败）、历史上限 200、`force` 重生成产生 `superseded` 版本。
- **API** `/api/v1/intelligence`：`status`、`reports`（列表/详情）、`reports/generate`、`reports/{id}/cancel`、`emerging`（纯统计）、`rankings`（importance/heat/emerging/new）。
- **SwiftUI 情报中心**：侧边栏「工作台 → 情报中心」，包含今日简报、重要事件、本周总结、新兴主题、历史记录五个视图与报告详情弹窗；AI 章节与数据库统计分别标注，引用可跳转事件中心/文章详情；覆盖生成中、失败、降级、空态与深浅色。
- **测试**：新增 16 个后端用例（统计、分层生成、引用过滤、降级、去重、取消、恢复、周窗口、API 集成）。

### Changed

- `MARKETING_VERSION` 0.8.0 → 0.9.0；后端 schema_version 7 → 8。
- 排行榜新增 `new`（按 `first_seen_at`）类型，复用 Phase 4 评分快照，评分取 `total_score`。
- Schema 断言测试同步到版本 8 与两张新表；Swift 侧边栏测试更新为新增「情报中心」后的顺序。

### Fixed

- **驾驶舱趋势只显示单柱**：`articles_trend` 原按 `fetched_at` 统计，历史文章集中在同一天采集，导致 14 天趋势只有一根柱。现按 `COALESCE(published_at, fetched_at)`（发布时间优先）统计，并用递归 CTE 补齐窗口内全部日期（含 0 值）；指标卡的今日/近 7 天文章数同步为同一口径。实测真实库 14 天分布为 1 / 2 / 5 / 1 / 308 / 710（共 1,027 篇，8 个零值日期正常显示）。
- 驾驶舱：零值柱不显示数字标签并使用淡色基线；指标卡副标题改为“今日发布 X”；趋势说明改为统计口径提示。
- 新增 `Backend/tests/dashboard/test_dashboard_stats.py`（发布时间优先 + 补零、overview 口径）；情报测试种子改为当天 UTC 固定时刻，消除跨日边界抖动。

### Verified

- 真实数据库 + 本地 `qwen3.5:4b-mlx` 生成 2 份活跃报告：今日（695 文章 / 56 事件 / 6 关键事件 / 3 主题 / 22 引用 / 71.4s）与本周（1012 文章 / 462 事件 / 6 关键事件 / 3 主题 / 21 引用 / 68.6s），状态均为 `succeeded`、`ai_status=used`。
- 后端 pytest **408 passed**；Swift XCTest **64 passed**；Debug 构建 0.9.0 成功。
- 实机截图：今日简报、重要事件、本周总结、新兴主题、历史记录、详情弹窗、浅色模式、事件跳转（`Docs/PHASE7_1_SCREENSHOTS/`）。
- 数据库升级前已备份；`integrity_check=ok`；未重建数据库；未 Push / 未合并 main。

### Known Limitations

- 分层生成以 6 个关键事件为上限，单份报告约 60–75 秒（4B 本地模型）。
- 情报页内容较长，验收截图未覆盖页面底部的支撑文章区域（数据已含完整文章引用）。
- 统计按 UTC 日期划分，与驾驶舱一致。
- `/Applications` 安装版仍为 0.8.0，本阶段未重新打包。

## [0.8.0] - 2026-11-17

Phase 7.0（全局 UI/UX 现代化改造）。版本 `0.8.0`。无 schema 变更、无后端 API 契约变更、无新增依赖。

### Added

- **统一设计系统** `Core/DesignSystem.swift`：字体、间距、圆角、表面色令牌，以及 `PIHCard`、`PageHeader`、`SectionHeader`、`CardHeader`、`MetricCard`、`LoadingStateView`、`SearchField`、`HighlightedText`、行悬停背景等可复用组件。
- **侧边栏信息架构**：工作台（驾驶舱/文章/事件中心）、采集与分析（信息源/分类/采集任务/AI 分析）、系统（运行状态）三分组；底部固定 Sidecar 状态入口。
- **文章关键词高亮**：标题与摘要高亮搜索词；ASCII 关键词按词首匹配，避免 `brain` 误命中 `AI`。
- **阅读中心排版**：30 pt 标题、17 pt 正文、8 pt 行距、760 pt 最大阅读宽度；技术元数据折叠进“文章信息”。
- **运行状态分级**：常用状态与采集引擎置顶，进程/端口/数据库/日志收进“高级诊断”。
- **Phase 7.0 文档与截图**：`Docs/PHASE7_0_UI_REDESIGN.md`、`Docs/PHASE7_0_ACCEPTANCE.md`、`Docs/PHASE7_0_SCREENSHOTS/`。

### Changed

- `MARKETING_VERSION` 0.7.2 → 0.8.0；默认窗口 1040×720 → 1240×820。
- 页面主标题统一 28 pt，卡片标题 16 pt，正文 15 pt，辅助信息 13 pt，元数据 12 pt；10–11 pt 不再承载重要信息。
- 卡片统一 14 pt 圆角、20 pt 内边距、1 px 柔和描边；页面边距 28 pt、卡片间距 18 pt。
- 驾驶舱：指标卡自适应网格、34 pt 数字、趋势柱宽上限并居中、单日数据提示、领域环图重写（中心总数不再旋转）、热点事件层级优化。
- 文章列表：标题 17 pt、未读强调、摘要 2 行、元数据收敛；搜索 300 ms 防抖；筛选/排序收入工具栏菜单；列表宽度上限 520 pt。
- 事件中心：头部与筛选区收敛为单行，榜单独立横向滚动，详情卡片化，评分条与字号升级。
- 信息源/分类：名称 15 pt、状态胶囊、技术字段降级，新增行悬停与双击编辑。
- 采集任务、AI 分析与运行状态统一卡片与字号层级。
- 移除重复的 `navigationTitle`，标题栏仅保留应用名。

### Fixed

- **导航取消误报错误**：页面切换取消在途请求时，AI 卡片显示“已取消 (NSURLErrorDomain -999)”。`APIClient` 现在透传取消，`ArticlesStore` 忽略取消并清理旧错误。
- **驾驶舱趋势图单柱铺满整块**：柱宽改为上限 44 pt，少量数据居中显示。
- **领域环图不显示/中心文字旋转**：改用 `Circle().trim` 绘制，中心文字保持正向。
- **侧边栏品牌与底部状态截断**：缩短文案并限制行数。

### Verified

- Swift Debug `BUILD SUCCEEDED`（XcodeGen 重新生成工程，App 版本 0.8.0）。
- `XCTest` 64 / 64 passed。
- 后端 `pytest` 390 / 390 passed（首次因 Sidecar 运行导致恢复测试按设计拒绝，退出 App 后重跑通过）。
- 实机运行验证：真实 Sidecar + SQLite（1048 文章 / 17 源 / 502 事件），驾驶舱、文章/阅读、搜索与高亮、空态、事件详情、信息源、状态页均正常；深浅色模式与 1210×760 小窗口无截断/遮挡。
- 未修改 Migration、Repository、API 契约；未重建用户数据库；未 Push/合并 main。

### Installed（Phase 7.05，2026-11-17）

- Release 重新打包：universal（x86_64 + arm64），Sidecar 打包进 Bundle（34 MB），adhoc 签名校验通过，App 50 MB。
- 安装到 `/Applications/Personal Intelligence Hub.app`，实际运行版本 `0.8.0`；旧版 0.7.2 已备份到 `Build/backups/`。
- DMG：`Build/PersonalIntelligenceHub-0.8.0.dmg`（30 MB，含 Applications 链接，`hdiutil verify` VALID）。
- 安装版实测：Sidecar 仅监听 `127.0.0.1` 随机端口且鉴权生效（未带 Token 401）；SQLite `integrity_check=ok`、`schema_version=7`、1052 文章 / 17 源 / 502 事件；Ollama `0.40.16` 可用；驾驶舱真实渲染；退出后 Sidecar 无残留。
- 安装前数据库备份：`pih.sqlite3.bak_phase705_20261117_232301`。


### Known Limitations

- 趋势图仍只有单日采集数据，已加真实提示，需随时间积累。
- 信息源 API 未返回单源文章数；失败详情仅在健康日志中。
- 无独立设置页，设置类信息由“运行状态”承担。
- `/Applications/Personal Intelligence Hub.app` 已由 Phase 7.05 更新为 0.8.0。

## [0.7.2] - 2026-11-17

Phase 6.8（macOS 本地安装、启动与首次使用验收）。版本 `0.7.2`。无 schema 变更。本节包含 Release 安装验收中实际发现并修复的运行期缺陷。

### Added

- **Release App Bundle 打包方案**：Sidecar 后端代码 + venv site-packages 打包进 `App Bundle/Contents/Resources/sidecar/`，App 从 Bundle 独立启动，不依赖开发目录。新增脚本 `Scripts/package_sidecar.sh`。
- **双模式 Sidecar 路径发现**：`BackendConfiguration.load()` 优先查找 Bundle 内 sidecar（Release 安装版），找不到 fallback 到 Info.plist 开发路径（Debug / Xcode 运行时）。SidecarLaunchConfig 新增 `extraEnvironment` 字段用于注入 `PYTHONPATH`。
- **App 图标与显示名称**：新增 `App/Resources/AppIcon.icns`（iconset 生成），`CFBundleIconFile=AppIcon`，`CFBundleName=Personal Intelligence Hub`；Dock 与菜单栏名称正常。
- **DMG 安装包**：`Build/PersonalIntelligenceHub-0.7.2.dmg`（30MB，含 App 与 Applications 快捷链接），`hdiutil verify` 校验通过。

### Changed

- `MARKETING_VERSION` 0.5.0 → 0.7.2。
- `Backend/scripts/phase6_seed_sources.py`：`credibility_score` 由错误的 `0.8` 改为 `NULL`（该列为 0–100 INTEGER，且不得写入猜测值）。
- `Backend/services/article_service.py`、`Backend/services/search_service.py`：不存在的 `database.write_session()` 改为 `database.session()`。

### Fixed

- **Dashboard 首屏永久加载**：首帧早于 Sidecar 握手，`task` 早退后不再重试。改为 `task(id: model.state)`，握手成功后自动补拉。
- **Dashboard 全部 DTO 解码失败**：`APIClient` 使用 `convertFromSnakeCase`，DTO 却声明 snake_case 属性（含 `last_7_days`）。统一改为 camelCase（`last7Days` / `articlesCount` / `heatScore` 等）。
- **Dashboard 趋势与热点 404**：查询串被写入 `path` 导致 URL 编码错误，改用 `query:` 参数。
- **趋势响应解码失败**：`{"days":14,"items":[...]}` 不能按 `[String: [Point]]` 解码，新增 `DashboardTrendResponse`。
- **信息源列表 500**：种子数据把 `credibility_score` 写成浮点 `0.8`，Pydantic `int` 校验失败。备份数据库后执行定向 UPDATE 置为 `NULL`，并修正种子脚本。
- **已读/收藏接口 500**：`AttributeError: module 'database' has no attribute 'write_session'`，导致 Phase 5 阅读状态、收藏、`reading-state` 全部失败。修复后新增回归测试 `test_reading_state_and_favorite_endpoints`。

### Verified（均为真实执行）

- Release `xcodebuild` BUILD SUCCEEDED，产物 universal (x86_64 + arm64)，安装后 50MB；adhoc 签名后 `codesign --verify --deep --strict` 通过。
- 安装到 `/Applications/Personal Intelligence Hub.app`，`CFBundleShortVersionString=0.7.2`；旧版本先备份到 `Build/backups/`，未覆盖用户数据库。
- Sidecar 从 Bundle 启动（`Resources/sidecar/main.py`），`/health` 返回 `status=ok`、`schema_version=7`、`path_kind=application_support`。
- 生命周期：退出 App 后 Sidecar 进程消失；再次启动分配新随机端口（60244 → 53695），无端口冲突、无重复进程。
- 真实 UI 验收：驾驶舱卡片/趋势/信息源 Top10/领域环图/热点事件全部渲染；信息源 17 个；文章列表、中文搜索（`中国` → 64 篇）、文章详情、事件详情与评分解释正常。
- 持久化：收藏 → 标记已读 → 稍后阅读 → 退出 → 重启，星标与“稍后阅读”状态保留（SQLite 同步确认 `is_favorite=1`、`reading_status=later`）。
- Ollama 可用：单篇 AI 分析真实成功（1/1，11.4s）；停止 Ollama 后 AI 页显示“降级 / Ollama 不可用”，驾驶舱与阅读功能不受影响，随后恢复服务。
- `pytest` 390 passed（含新增回归测试）；`XCTest` 64 passed。
- 数据库现状：17 sources / 1028 articles / 502 events / 593 entities / schema_version 7（采集持续运行，数量会继续增长）。

### Installed

| 项目 | 位置 |
|---|---|
| Release App | `/Applications/Personal Intelligence Hub.app` |
| DMG 安装包 | `Build/PersonalIntelligenceHub-0.7.2.dmg` |
| 用户数据 | `~/Library/Application Support/PersonalIntelligenceHub/pih.sqlite3` |
| 安装指南 | `Docs/INSTALLATION.md` |
| 验收报告 | `Docs/PHASE6_8_ACCEPTANCE.md` |

### Known Limitations

- L1：Sidecar 依赖 Homebrew Python 3.14+（`/opt/homebrew/bin/python3`），新机器需先安装；后续可打包 Python.framework。
- L2：未做 Apple Developer 公证，首次运行可能需要在“隐私与安全性”中允许。
- L3：`BBC Top Stories` 在当前网络下被 net_guard 以 `blocked_target` 拦截（DNS 返回 Teredo IPv6），属安全策略的保守行为，其他 16 个源采集正常。
- L4：趋势图目前只有单日数据（历史文章均为当日采集），图表显示为单柱，数据真实但视觉信息量有限。
- L5：事件/实体视图依赖已运行的 AI 分析与事件聚类结果，不做自动补偿。

---

## [0.7.1] - 2026-11-17

Phase 6.5（真实数据激活与端到端验证）。版本 `0.7.1`。无 schema 变更。

### Added

- **AI 分析激活**：本地 `qwen3.5:4b-mlx` 分批处理 524 篇文章 → 360 篇 AI 完成（69%），平均 ~9s/篇。失败 4 篇（`schema_invalid`/`invalid_json`，模型偶发 JSON 结构不合规，不影响整体）。
- **实体入库**：`entity_service.sync_article()` 从 AI analysis JSON 抽取实体 → 593 唯一实体 / 742 文章-实体关联 / 500 事件-实体关联。高频实体：arXiv ML(18)、OpenAI(10)、深圳(10)、France 24(7)。
- **Phase 4 事件聚类激活**：`event_clustering_service.create_run(scope="full")` 382 篇带 AI 的文章 → 502 events + 522 articles_in_events（100% 覆盖）。125s 完成，candidate_pair=55 / ambiguous=2（use_llm=False）。
- **事件评分快照**：`event_scoring_service.recompute(scope="all")` 502 events 全部生成 current snapshot。Top event: Palantir 替代（heat=47, importance=80, arts=2）。

### Dashboard 验证结果（全部真实数据）

| 端点 | 结果 |
|---|---|
| overview | articles=524 / sources=17 / events=502 (active=2) |
| events_hot | heat 排名，Top 1: Palantir 替代 (heat=47) |
| entities_top | arXiv ML(18) / OpenAI(10) / 深圳(10) |
| categories | research(300) / tech(90) / news_zh(90) / news(24) / tech_zh(20) |
| sources_top | arXiv ML/AI/NLP (各100) / NIST(40) / 中新网国际(30) |

### Performance

| 指标 | 数值 |
|---|---|
| AI 分析 | ~9s/篇，27 tok/s |
| 事件聚类 | 382 articles → 125s |
| 事件评分 | 502 events → 495ms |

### Verified

- 后端 389 passed（Phase 0–6 全量，无回归）。
- Swift Debug BUILD SUCCEEDED。
- Swift XCTest 64/64 passed。
- Dashboard 8 端点 against 真实 DB — events_hot 和 entities_top 不再是空数组。
- 数据库完整性：所有 article_entities → entity_id 外键存在；所有 event_articles → event_id 外键存在。

### Remaining

- 4 篇文章 AI 分析持续失败（`ea44bf26`, `bc06d9fe`, `21f9fcfa`, `2c90bc71`）— 模型输出 schema_invalid/invalid_json，重试 3 次后放弃。不影响 69% 覆盖率。
- AI 分析未完全覆盖剩余 164 篇（360/524）— 继续让后台 AI worker 运行即可；增量聚类/评分脚本已可增量刷新。
- 多数事件为 1-2 篇文章（Phase 4 聚类 use_llm=False 仅做 vector 余弦相似度 + 实体 Jaccard），跨来源同主题事件未充分合并。生产环境可开启 `use_llm=True` 进一步合并。

---

## [0.7.0] - 2026-11-17

Phase 6（信息源扩充与可视化智能驾驶舱）。版本 `0.7.0`。沿用 schema_version=6，无新 Migration。

### Added

- **信息源扩充（Phase 6.0）**：接入 17 个公开 RSS/Atom 来源（BBC World/Top Stories、DW、Al Jazeera、France 24、中新网 3 路、NIST、NASA、TechCrunch、MIT Tech Review、The Verge、InfoQ CN、arXiv AI/ML/NLP），真实采集 524 篇文章，覆盖 5 个分类、中英文混合。13/17 成功采集，4 个因网络受限跳过。
- **驾驶舱后端 API（Phase 6.1）**：`Backend/services/dashboard_service.py` + `Backend/api/v1/dashboard.py`，8 个端点全部真实 SQLite 数据：
  - `GET /api/v1/dashboard/overview` — hero counters（articles total/today/7days/unread/favorites、sources total/active、events total/active）
  - `GET /api/v1/dashboard/articles/trend?days=N` — 日文章数量趋势
  - `GET /api/v1/dashboard/sources` — 信息源文章贡献 Top 20
  - `GET /api/v1/dashboard/categories` — 领域分布
  - `GET /api/v1/dashboard/events/hot?limit=N` — 热点事件（JOIN event_score_snapshots.is_current=1，ORDER BY heat_score DESC）
  - `GET /api/v1/dashboard/entities/top?limit=N` — 高频实体（JOIN article_entities）
  - `GET /api/v1/dashboard/reading-state` — 未读/收藏分布
  - `GET /api/v1/dashboard/source-health` — 信息源健康状态
- **SwiftUI 智能驾驶舱**：`DashboardScreen.swift` 作为新默认首页（AppSection.dashboard，chart.bar.xaxis 图标）。Hero cards + 14 天趋势柱状图 + 信息源 Top 10 横条 + 领域甜甜圈图 + 热点事件列表。全部无外部图表库（GeometryReader + RoundedRectangle + 自定义 PieSlice Shape）。尊重深浅色模式、空数据状态、刷新手势。

### Fixed

- events 表无 `heat_score`/`importance_score` 列（评分在 event_score_snapshots），events_hot 改为 JOIN snapshots.is_current=1。
- source_health_logs 表字段名（status/http_status/checked_at vs 预期的 status_code/status_text/fetched_at），已修正。
- entities 表 `canonical_name` 字段名（不是 name），entities_top 已修正。
- DashboardScreen.swift 头部残留 Python docstring → Swift 注释。
- SidecarViewModel 用 `isDataReady`（不是 `isReady`），DashboardScreen 状态检查已修正。
- CategoryDonut ForEach 内 `start += sweep` 违反 ViewBuilder，改为预先计算 SliceData 数组。
- EventModelsTests.testAppSectionIncludesEventCenter section index 4→5（新增 .dashboard）。
- Xcode project 需手动添加 DashboardScreen.swift 到 PBXBuildFile/PBXFileReference/Features group/Sources build phase。

### Verified

- 后端 389 测试全绿（Phase 0–6 全量，无回归）。
- Swift Debug BUILD SUCCEEDED。
- Swift XCTest 64/64 全绿。
- Dashboard 8 端点 against 真实 DB（524 文章 / 17 源 / 5 分类）全部返回正确 JSON。

---

## [0.6.0] - 2026-11-17

Phase 5（阅读与知识管理）。版本 `0.6.0`，schema_version=6。

### Added

- **FTS5 全文检索**：迁移 `0007_fts_search.sql`；独立 `articles_fts` 表 + trigram tokenizer + INSERT/UPDATE/DELETE 触发器；BM25 排名 + snippet 高亮；短查询（<3 chars）自动降级 LIKE。
- **阅读状态与收藏**：articles 表新增 `reading_status`（unread/reading/read）和 `is_favorite` 字段；Repository 层新增更新方法。
- **SwiftUI 详情页增强**：文章详情支持标记已读、收藏切换、阅读进度。
- **测试**：后端 389 通过（Phase 5 新增 22 个）；Swift 64 通过；阅读状态 DTO 手动 Decodable（Swift 6 auto-synthesis 跳过 let + 默认值）。

---

## [0.5.0] - 2026-11-17

Phase 4（事件聚合与智能情报分析）。版本 `0.5.0`，`schema_version=6`。

### Added

- **实体规范化**：`entities` / `entity_aliases` / `article_entities`；组织法律后缀、全半角、中英文括号别名归一；同名不自动跨类型合并；歧义提及进入复核。
- **事件聚类**：`Backend/event_intelligence/` 纯算法包；L1 内容哈希、L2 实体/关键词/标题/摘要/时间/分类/来源加权；L3 本地 Ollama 仅判断含糊候选；算法版本 `event-cluster-v1`。
- **事件生命周期与时间线**：candidate/active/evolving/dormant/closed/merged/archived；closed 仅人工；时间线区分发生/发布/识别时间。
- **事件关系**：related_to / follows / same_topic 自动候选；caused_by / part_of / contradicts 仅人工带证据；算法版本 `event-relation-v1`。
- **可解释评分与排行榜**：importance/heat/freshness/coverage/confidence 五项独立；算法版本 `event-score-v1`；快照版本化、每事件保留 50 个；排行榜五种口径。
- **数据库**：迁移 `0006_event_intelligence.sql` 新增 13 张表，索引与 CHECK 约束覆盖关键不变量，未修改 0001–0005。
- **API**：`/api/v1/entities`、`/events`（含 unmerge）、`/event-clusters`、`/rankings`、`/event-scores/recompute`。
- **SwiftUI 事件中心**：侧栏“事件中心”；列表筛选/排序/分页；详情含概览、评分解释、时间线、文章、实体、相关事件；人工重命名/改状态/合并/撤销合并/拆分/加移文章/确认忽略关系。
- **测试**：后端 367 项通过（Phase 0–4 全量）；新增 `Backend/tests/events/` 质量数据集与回归用例（含第二次聚类、冲突标记、分块合并撤销、过期评分等）；Swift 64 项通过；性能脚本 `Backend/scripts/perf_event_intelligence.py` 覆盖首次与第二次增量运行。
- **文档**：`PHASE4_CONTRACT.md`、`PHASE4_DATABASE.md`、`PHASE4_API.md`、`PHASE4_CLUSTERING.md`、`PHASE4_SCORING.md`、`PHASE4_ADR.md`、`PHASE4_USER_GUIDE.md`、`PHASE4_HANDOVER_AUDIT.md`、`PHASE4_QA_REPORT.md`、`PHASE4_ACCEPTANCE.md`。

### Fixed

- 实体名末尾合法右括号被误删，导致 `星河科技（Galaxy Tech）` 无法提取英文别名。
- 事件详情 API 读取 `EntityRecord.articles` 缺失字段导致 500。
- 大量相似事件共享泛化关键词时，候选事件未排序即截断，正确事件被挤出窗口（基准 210 事件 → 30 事件），新增回归测试。
- 不同季度财报（Q3/Q4）因标题+关键词相似被误合并；冲突 event 实体现在降权 0.6。
- 跨语言与实体缺失文章不再静默拆分，进入人工复核队列。

### QA 修复（独立 QA 复测后关闭）

- **Critical**：第二次及以后增量/全量聚类在 `_event_features` 触发 `list |= set` 的 `TypeError`，导致新文章无法入事件；已修复并新增回归。
- **High**：无 event 实体时 Q3/Q4、裁员/招聘被误合并，新增冲突标记守卫。
- **High**：大事件合并审计 JSON 被截断导致 unmerge 失败；改为分块存储并新增 300 篇合并撤销回归。
- **High**：UI“文章数”排序 422；后端新增 `order=articles`。
- **High**：UI“发展中”人工状态 422；从人工状态选择器移除 `evolving`。
- **High**：合并后无法从 UI 进入已合并事件；状态筛选新增“已合并”。
- **Medium**：pending 歧义不计入置信度；heat 使用全时段来源数；过期评分不随时间衰减；移除文章残留时间线；别名增删与自动状态变化缺审计；LLM 调用位于只读事务；排行榜 500 条窗口。
- **Low**：专用错误码与中文消息、关系证据上限、retry 的 retry、聚类开关、决策表保留策略、prompt `<candidates>` 中和、排行榜条目与失败提示。

### Verified

- 聚类质量：Precision 1.0000、Recall 0.8333、F1 0.9091、误合并率 0、漏合并率 0.1667、人工复核比例 0.0833（修复后复测一致）。
- 性能（临时库，16 GiB）：首次 300 篇 → 30 事件、2.64 s；第二次新增 150 篇 → 仍 30 事件且全部归属、1.51 s；事件列表 0.55 ms，时间线 0.14 ms，排行榜 1.31 ms，DB 2.92 MiB，峰值 RSS 43.1 MiB。
- 本地模型调用仅 `qwen3.5:4b-mlx`（可选 L3）；Embedding 仍未下载、未启用；云端零出站。
- Schema 保持 6，未修改 0006；用户数据库未重建、未迁移。

## [0.4.0] - 2026-11-16

Phase 3（本地 AI 分析）。版本 `0.4.0`，`schema_version=5`。

### Added

- **本地 Provider**：`ai_engine/provider.py` 固定 `http://127.0.0.1:11434`，禁用环境代理；`*-cloud` 与 `remote_host` 非空模型在发请求前阻断；每次请求显式传 `num_ctx`，返回真实模型 digest、耗时、tok/s。
- **分析流水线**：`article-analysis-v1` Prompt、输入控制字符清理与分隔符转义、6000 字符截断、Pydantic 严格校验、最多 3 次尝试、失败不落半成品。
- **数据库**：迁移 `0005_ai_analysis.sql` 新增 `ai_model_registry`、`ai_runs`、`ai_run_items`、`article_ai_analysis`、`article_embeddings`；DB 层拒绝 `-cloud` 模型名。
- **任务队列**：单并发、暂停/恢复/取消/重试、重启恢复（`interrupted`）、Ollama 不可用降级。
- **API**：`/api/v1/ai/status`、`/ai/models`、`/ai/runs`（含 pause/resume/cancel/retry）、`/articles/{id}/analysis`、`/articles/{id}/analyze`。
- **SwiftUI**：侧栏新增“AI 分析”（状态、模型白名单、运行与逐篇结果、控制按钮）；文章详情显示最新分析并支持触发分析。
- **文档**：`PHASE3_CONTRACT.md`、`PHASE3_DATABASE.md`、`PHASE3_API.md`、`PHASE3_AI_ENGINE.md`、`PHASE3_LIVE_VERIFICATION.md`、`PHASE3_QA_REPORT.md`、`PHASE3_ACCEPTANCE.md`、`PHASE3_USER_GUIDE.md`。
- **验证**：后端 271 项、Swift 59 项、集成 89 项；真实 Ollama 分析 3 篇（3.2–12.3 s/篇，约 28.4–28.7 tok/s），Prompt Injection 未越权，云端模型零出站。

### Notes

- 本机仅 `qwen3.5:4b-mlx` 可用；`qwen3:1.7b`/`gemma3:4b` 仅登记为未启用候选。
- Embedding 未下载、未启用（AI-01 未确认），`article_embeddings` 保持空表。
- SEC-01 已关闭（2026-11-17）：Ollama 完全退出并重启后仅监听 `127.0.0.1:11434`，`OLLAMA_HOST` 不再为 `0.0.0.0`。

## [0.3.0] - 2026-11-16

Phase 2（多渠道信息采集）：`net_guard` 安全网络层、RSS/Atom 采集、文章与去重、采集任务调度/重试/取消/恢复、来源健康、文章/任务/健康/采集状态 API、SwiftUI 五页、迁移 `0004`。详见 [Docs/PHASE2_ACCEPTANCE.md](Docs/PHASE2_ACCEPTANCE.md)。

## [Unreleased]

### Added

- **Phase 1 信息源管理（真实功能）**：`/api/v1/sources` 与 `/api/v1/source-categories` 的 CRUD、启停、分页/筛选/排序；SwiftUI 侧栏界面（信息源、分类、运行状态），含加载/空/错误/离线状态与字段级错误提示。
- **数据库**：迁移 `0002_source_categories.sql`、`0003_sources.sql`（`schema_version=3`），部分唯一索引、软删除、外键与 CHECK 约束；Repository 层与 `read_session()` 只读快照。
- **备份/恢复**：`database/backup.py` + `Scripts/backup_db.py` / `restore_db.py`；在线备份、`integrity_check`、元数据、7+4 保留、恢复前安全备份与失败回滚。
- **安全**：静态 URL 守卫（拒绝 localhost/私网/链路本地/元数据/数字主机/IPv4-mapped）、64 KiB 请求体上限、磁盘不足 507 降级。
- `Docs/PHASE1_PRECHECK.md`：Phase 1 Stage 1.0 前置审查（Phase 0 基线核验、磁盘/Python/Ollama 审计、范围冲突、五个 Subagent 独立意见、G1 判定）。
- `Docs/PYTHON_COMPATIBILITY.md`：Python 3.14.8 与依赖兼容性审计。
- `Docs/AI_PROVIDER_SECURITY_POLICY.md`：AI Provider 安全边界政策（本地优先、禁止 `-cloud`、可追溯）。
- `Docs/MACOS_COMPATIBILITY.md`：macOS 14 最低支持策略、现有 API 静态审计与实机验证方案。
- Phase 1 设计文档：`PHASE1_ADR.md`、`PHASE1_DATA_MODEL.md`、`PHASE1_ER_DIAGRAM.md`、`PHASE1_DATABASE_DESIGN.md`、`PHASE1_API_DESIGN.md`、`PHASE1_SOURCE_ADAPTER_DESIGN.md`、`PHASE1_DESIGN_REVIEW.md`。
- `Docs/PHASE1_USER_GUIDE.md`：Phase 1 用户操作手册，覆盖启动/退出、信息源与分类管理、搜索筛选、备份恢复、故障排查、数据位置与安全注意事项。

### Changed

- 按用户 C1–C6 裁决修订阶段状态：`DEVELOPMENT_ROADMAP.md` 中 Phase 0 由 PARTIAL 改为 **PASSED**，Phase 1 标记为 **Stage 1.1 设计**；`ARCHITECTURE.md` 头部阶段状态同步；`PHASE_ACCEPTANCE.md` 增加阶段状态索引（历史验收过程不变）。
- `TECHNICAL_DECISIONS.md` 索引登记 ADR-0012…0016（正文见 `PHASE1_ADR.md`），并关闭 DOC-02/DOC-03。
- `README.md` 按 Phase 1 实际实现重写功能清单、运行/测试命令、备份恢复、目录结构与未实现项；版本号与 `Backend/core/version.py`、`App/project.yml` 的 `0.2.0` 对齐。

### Notes

- 本版本包含 Phase 1 的信息源/分类管理、SQLite 迁移 `0002`/`0003`、在线备份与可回滚恢复、SwiftUI 管理界面。
- 仍**不包含** RSS/Atom 实际采集、文章入库/去重、FTS5 全文检索、AI 摘要/评分/事件；`fetch_interval_minutes` 与 `enabled` 当前只保存配置，不触发抓取。
- 阶段状态：Phase 0 为 **PASSED**；Phase 1 为 **PASS WITH CONDITIONS**（2026-11-16），独立 QA 缺陷全部关闭，`PHASE1_ACCEPTANCE.md`、`DEVELOPMENT_ROADMAP.md`、`ARCHITECTURE.md` 已同步。
- 未关闭风险：磁盘空间（DISK-01，完整 ≥20 GiB 恢复演练 BLOCKED）、macOS 14 未实机验证（MAC-01，发布门禁）、Ollama 监听收敛待执行（OLL-01）、Phase 2 采集前必须实现 DNS 侧网络守卫。

## [0.1.0] - 2026-11-16

Phase 0（环境审计与工程初始化）的工程骨架。**不包含任何业务功能**：无采集、无正文提取、无摘要/分类/评分、无事件与 RAG、无业务数据表。阶段验收结论由 architect 基于 qa-security 证据发布；Phase 0 最终结论为 PASS（验收基提交 `ad1c403`，见 `Docs/PHASE_ACCEPTANCE.md`）。

### Added

**Git 与文档基线**
- 初始化 Git 仓库，建立两个基线提交：`4f77379`（文档、`.trae/agents/` 7 个 Agent 配置、`.gitignore`）与 `a27e430`（Phase 0 实现）。
- 审计与契约文档：`Docs/PROJECT_BASELINE.md`、`Docs/ENVIRONMENT_AUDIT.md`、`Docs/LOCAL_AI_AUDIT.md`、`Docs/ARCHITECTURE.md`、`Docs/API_CONTRACT.md`、`Docs/DATABASE_BASELINE.md`。
- Phase 0 验收与依据文档：`Docs/TEST_REPORT.md`、`Docs/SECURITY_REVIEW.md`、`Docs/TECHNICAL_DECISIONS.md`（ADR-0001…0011）、`Docs/DEVELOPMENT_ROADMAP.md`、`Docs/PHASE_ACCEPTANCE.md`（结论 PARTIAL，待 architect 复核）。
- 根目录 `README.md` 与 `CHANGELOG.md`。

**macOS App（Swift 6 / SwiftUI，XcodeGen）**
- `App/project.yml`：部署目标 macOS 14.0、`SWIFT_STRICT_CONCURRENCY=complete`、Debug 免签名构建；`.xcodeproj` 为生成物且不入库。
- Sidecar 子进程管理（`SidecarSupervisor`）：参数数组传递（不使用 shell 拼接）、工作目录为仓库根、`stdin` 置空、stdout/stderr 独立管道、子进程退出事件流。
- Token 生成（`SidecarToken`）：`SecRandomCopyBytes` 生成 32 字节，编码为 43 字符无 padding base64url，仅保存在内存。
- 握手解析（`HandshakeParser`）：校验 `PIH_SIDECAR_READY` 前缀、4096 字节上限、UTF-8、JSON 字段、`port` 范围、`pid` 与子进程一致、`service=pih-backend`、SemVer MAJOR 兼容；10 秒超时。
- 健康检查（`APIClient`）：仅 `GET http://127.0.0.1:<port>/health`，Bearer Token，2 秒超时，校验 `service`/`version`/`status`/`database.status` 与 `X-Request-ID`；`/docs` 等未使用。
- 状态机（`SidecarState`）：7 个真实状态 `idle / starting / ready / degraded / offline / failed / stopping`，每个状态由真实进程或 HTTP 响应驱动。
- 轮询与降级：每 5 秒健康检查；连续 3 次失败转 `offline` 并停止轮询；HTTP 401 立即转 `failed` 且不再用同一 Token 重试；子进程意外退出转 `failed`。
- 停止路径：SIGTERM → 3 秒 → SIGKILL；App 退出时同步终止子进程。
- stderr 尾部环形缓冲：最多 40 行、每行 800 字符，写入时即把 Token 替换为 `<redacted-token>` 后展示。
- 最小状态界面 `StatusView`：展示状态、PID、端口、后端版本、数据库状态、`schema_version`、数据目录类型、运行时长、服务端时间、最近检查时间、连续失败次数、`X-Request-ID` 与错误详情；提供“启动 / 停止 / 立即检查”。

**FastAPI Sidecar（Python，仅本地）**
- 启动顺序：校验环境 → 初始化数据库（失败不阻断启动）→ 绑定 `127.0.0.1:PIH_PORT` → ASGI startup → stdout 输出单行握手。
- 随机端口：先 `bind(("127.0.0.1", 0))` 取真实端口，再把已绑定 socket 交给 uvicorn，避免“选端口再绑定”竞态。
- Bearer 认证：纯 ASGI 中间件，认证先于路由；`hmac.compare_digest` 常量时间比较；缺失/格式错误/错误 Token 统一返回 401 `{"error":{"code":"unauthorized",...}}`。
- `GET /health`：返回 `status/service/version/timestamp/uptime_seconds/database`；数据库异常时为 HTTP 200 + `status=degraded`，不返回 503/500；不返回 Token、PID、绝对路径或主机名。
- 关闭 `/docs`、`/redoc`、`/openapi.json`；不添加 CORS。
- 响应头：服务端生成 UUIDv4 `X-Request-ID`、`Cache-Control: no-store`、`application/json; charset=utf-8`。
- 结构化日志：stderr 单行 JSON（`ts/level/event/request_id` 及事件字段），uvicorn 日志统一投影为同格式；访问日志关闭；敏感字段名（token/authorization/secret/password/cookie）主动丢弃。
- 生命周期：SIGTERM/SIGINT 优雅退出并以退出码 0 结束，3 秒强制退出兜底；父进程看门狗在启动时先校验父进程、此后每 2 秒检查 `getppid()`，父进程消失后优雅退出；stdout 仅保留握手行。
- 退出码：`0` 正常、`2` 配置错误、`3` 端口绑定失败、`4` 致命错误。

**SQLite 数据层与迁移**
- 默认数据目录 `~/Library/Application Support/PersonalIntelligenceHub/`，数据库文件 `pih.sqlite3`；`PIH_DATA_DIR` 仅接受绝对路径，拒绝源码树与 `.app` Bundle 内部路径。
- 权限：新建数据目录 0700、数据库文件 0600、进程 `umask 077`。
- 连接与 PRAGMA：短连接、无连接池、`isolation_level=None`、`foreign_keys=ON`、`busy_timeout=5000`（`/health` 探测用 500ms）、`synchronous=NORMAL`、初始化时启用并校验 WAL。
- 迁移运行器：`schema_migrations` 由运行器引导；文件命名 `NNNN_snake_case.sql`；每个文件单事务、失败整体回滚；SHA-256 校验和不匹配即报错、不自动修复；禁止对更高版本数据库降级；不使用会隐式提交的 `executescript()`。
- `0001_init.sql`：仅创建基础设施表 `app_meta`；Phase 0 无任何业务表。
- 事务语义：`session()` 以 `BEGIN IMMEDIATE` 包裹，正常退出 COMMIT，异常 ROLLBACK 并重新抛出；提供 `get_meta` / `set_meta`。
- `initialize()` 与 `health_check()` 均不抛异常：失败以稳定错误码（如 `database_unavailable`、`database_schema_error`、`database_migration_failed`）报告。

**脚本**
- `Scripts/build_app.sh`：`xcodegen generate` + `xcodebuild`（Debug，`build/DerivedData`），构建后校验 `.app` 存在并输出 `APP_PATH`。
- `Scripts/run_app.sh`：启动已构建的 App，找不到产物时给出明确错误。
- `Scripts/run_backend.sh`：开发期手动启动 Sidecar；要求外部注入 `PIH_SIDECAR_TOKEN`，脚本不生成、不打印 Token。

**测试**
- 后端 pytest 测试套件（`Backend/tests/backend/`、`Backend/tests/data/`），覆盖认证、`/health`、统一错误、日志、进程生命周期、启动环境校验、数据库与迁移。
- 本地实测（2026-11-16，Python 3.14.8）：`57 passed in 9.66s`（命令：`cd Backend && .venv/bin/python -m pytest tests -q`）。
- Swift 单元测试 target `App/PersonalIntelligenceHubTests/`（XCTest，`bundle.unit-test`，3 个文件共 35 项）：`HandshakeParserTests` 23、`HealthModelsTests` 8、`SidecarTokenTests` 4，覆盖握手首行解析的成功与失败分支、`/health` 完整/degraded 响应解码与错误信封、Token 的 43 字符 base64url、随机性与解码后 32 字节。
- Swift 测试本地实测（2026-11-16）：`Executed 35 tests, with 0 failures`、`** TEST SUCCEEDED **`。命令：先 `cd App && xcodegen generate`，再 `xcodebuild test -project "App/PersonalIntelligenceHub.xcodeproj" -scheme PersonalIntelligenceHub -configuration Debug -destination 'platform=macOS' -derivedDataPath build/DerivedData`。
- `Tests/phase0_integration_check.sh`：真实子进程 + 真实 HTTP 的 Phase 0 集成检查 68 项（协议、生命周期、数据库、安全边界），每次使用一次性 Token 与临时数据目录；本地实测 `PASS=68 FAIL=0`、`ALL CHECKS PASSED`。
- 计数口径：后端 57、Swift 35、集成 68 三项互不重复（合计 160）；`Docs/TEST_REPORT.md` 的 177 项另含前端检查 8 项与安全静态检查 9 项。

### Changed

- 依 `Docs/PROJECT_BASELINE.md` §6 的裁决：后端采用扁平结构 `Backend/{api,core,database}`（不使用 `Backend/app/` 示例结构）；接口契约位于 `Docs/API_CONTRACT.md`，Phase 0 不创建 `Docs/contracts/`。
- Python 运行时固定为本机 `Backend/.venv`（3.14.8），不污染系统 Python；`pyproject.toml` 声明 `requires-python >= 3.12`。
- Xcode 工程改为 XcodeGen 生成，`App/PersonalIntelligenceHub.xcodeproj` 纳入 `.gitignore`。

### Fixed

- 父进程看门狗启动竞态（P2，`Backend/main.py`）：若父进程在 watchdog 线程启动前退出，`getppid()` 已为 1，原比较永不成立，Sidecar 会成为 ppid=1 的孤儿进程（违反 `API_CONTRACT.md` §9.2）。现在线程启动时若 `parent_pid <= 1` 立即记录 `parent_lost` 并优雅退出，循环中 `getppid() == 1` 同样视为父进程丢失。集成脚本的启动竞态用例由 WARN 变为 PASS，后端仍为 `57 passed`。
- 入口路径未标准化（P3，`App/PersonalIntelligenceHub/Services/BackendConfiguration.swift`）：`PIHDevBackendEntry` 现在按 `standardizedFileURL` 规范化，错误信息中不再出现 `..` 片段。解释器路径 `PIHDevBackendPython` **刻意保持原样**——标准化会解析 venv 内的符号链接从而丢失虚拟环境，该约束已写入源码注释。

### Security

- Token 不进入命令行参数、URL、Cookie、请求体、日志、错误响应、UI 或任何文件；Sidecar 读取后立即从 `os.environ` 移除。
- Sidecar 仅监听 `127.0.0.1`，端口随机；无 CORS；未授权请求在路由前即返回统一 401，不回显收到的凭据。
- App 展示的 stderr 尾部在写入阶段即时脱敏 Token；日志层丢弃敏感字段。
- `X-Request-ID`、`Cache-Control: no-store` 等响应头默认生效。
- `.gitignore` 排除 `.env*`、`*.sqlite3*`、模型文件、`.venv/`、构建产物。
- 明确约束：不得调用本机 4 个 `-cloud` 代理模型（会把内容发送至 ollama.com）。

### Known Issues

- 磁盘可用约 11 GiB（数据卷已用 95%），构建与后续模型下载存在空间风险（`Docs/ENVIRONMENT_AUDIT.md` R1）。
- Python 3.14.8 属较新版本，第三方生态兼容性未大规模验证（R2）。
- 最低支持 macOS 14.0 已在构建配置中声明，但本机仅有 macOS 27.2，**未实机验证**（R3）。
- 本机存在 4 个 `-cloud` 模型，误用会导致数据出网；Phase 0 代码未做模型白名单校验（Phase 3 才引入 Provider 层）。
- Embedding 模型缺失，语义去重/检索尚不可用（`Docs/LOCAL_AI_AUDIT.md` §5）。
- Phase 0 验收在 **0.1.0 发布时为 PARTIAL**（`Docs/PHASE_ACCEPTANCE.md` §5 早期状态）：测试与安全证据齐全，关闭项为验收文档补齐与交付物提交固化。该状态已于 2026-11-16 复核为 **PASS**（见 Unreleased 与 `PHASE_ACCEPTANCE.md` 阶段状态索引），历史过程保留不改写。
