# Personal Intelligence Hub（PIH）

一个 **local-first 的 macOS 个人智能信息中台**：自动采集公开信息，在本地完成内容理解、事件聚合、推荐筛选与每日情报，并通过阅读行为持续调整推荐。

客户端是原生 SwiftUI，后端是仅监听 `127.0.0.1` 的 Python FastAPI Sidecar，数据保存在本机 SQLite。默认不依赖任何云端模型或远程服务。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%2014%2B-black.svg)](#系统要求)
[![Swift](https://img.shields.io/badge/Swift-6-orange.svg)](#技术栈)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](#技术栈)

> 当前状态：Phase 8，App/后端 `0.14.0`，数据库 Schema `14`。
> 这是一个可运行的真实项目，不是设计稿；核心链路已在真实 RSS/Atom 来源、本地 Ollama 与真实 SQLite 上验证。

---

## 为什么做这个项目

传统 RSS 阅读器把「采集」交给机器，却把「筛选、理解、整理」留给人。PIH 想解决的是后半段：

- 新文章入库后自动完成 AI 分析、实体提取、事件聚合、评分与推荐刷新；
- 用户每天只需要打开「今日」，看少量真正值得关注的内容；
- 同一件事的多篇报道优先合并为事件，而不是在列表里重复出现；
- 阅读、收藏与「不感兴趣」会真实影响后续推荐；
- 所有数据、模型调用与索引都在本机完成。

---

## 核心能力

| 模块 | 能力 |
|---|---|
| 今日 | 今日新增、值得关注、重点事件、待阅读、最近阅读；自动化异常时一键启用/恢复 |
| 阅读 | 推荐 / 全部 / 稍后阅读 / 收藏 / 历史 / 搜索六视图，统一阅读状态与 Reader |
| 全文搜索 | SQLite FTS5，覆盖标题、摘要与已抓取正文；支持来源、时间、阅读状态、收藏筛选 |
| 事件 | 事件列表、详情、时间线、关联文章、实体、评分、合并/拆分/人工校正 |
| 洞察 | 真实统计、趋势、来源分布、热点事件；带引用的本地 AI 日报/周报 |
| 设置 | 兴趣偏好、信息源、自动化、采集健康、存储说明与高级诊断 |
| 采集 | RSS/Atom 与官方列表页适配器；SSRF/DNS Rebinding 防护、robots.txt、超时与大小限制 |
| 本地 AI | Ollama Provider；摘要、分类、关键词、实体；严格 JSON 校验；`*-cloud` 模型强制阻断 |
| 推荐 | 五维可解释评分：兴趣、事件重要性、新颖性、来源质量、时效；阅读/收藏/反馈参与调整 |
| 正文 | 按需抓取原文正文，失败保留摘要并明确标注内容状态 |

---

## 架构

```text
SwiftUI App (App/)
  └─ PIHSidecarClient（HTTP + Bearer Token）
       └─ FastAPI Sidecar (Backend/, 127.0.0.1 + 随机端口)
            ├─ api/                 路由、鉴权、健康检查
            ├─ services/            采集、AI、事件、推荐、情报编排
            ├─ collectors/          RSS/Atom、HTML 列表适配器、net_guard 安全网络层
            ├─ ai_engine/           Ollama Provider、Prompt、结构化输出校验
            ├─ event_intelligence/  聚类、聚合、评分、排序纯算法
            ├─ database/            Migration + Repository（唯一数据入口）
            └─ scheduler/ Pipeline  任务队列、重试、租约、暂停/恢复
```

设计约束：

- SQLite 是唯一权威业务数据源，前端不直连数据库；
- 所有业务读写经过 Repository，Schema 变更只允许新增 Migration；
- Sidecar 仅绑定 `127.0.0.1`，每次启动生成随机 Bearer Token；
- 不允许数据出网，不允许云端模型，不引入遥测；
- 所有派生数据带算法版本与输入指纹，可解释、可重算。

---

## 系统要求

| 项目 | 要求 |
|---|---|
| macOS | 14.0+ |
| Xcode / Swift | Xcode 16+，Swift 6 |
| XcodeGen | `brew install xcodegen` |
| Python | 3.12+ |
| Ollama | 可选，仅本地使用 |

---

## 快速开始

```bash
git clone https://github.com/lwbhust/personal-intelligence-hub.git
cd personal-intelligence-hub

# 1. 后端依赖（App 在 Debug 模式下会使用该虚拟环境）
python3 -m venv Backend/.venv
Backend/.venv/bin/python -m pip install fastapi uvicorn pydantic feedparser defusedxml
Backend/.venv/bin/python -m pip install pytest httpx   # 开发/测试

# 2. 生成工程并构建 Debug App
brew install xcodegen
./Scripts/build_app.sh

# 3. 启动
open build/DerivedData/Build/Products/Debug/PersonalIntelligenceHub.app
```

首次启动后：

1. 在「设置 → 信息源管理」添加 RSS/Atom 来源，或使用内置来源；
2. 保持「设置 → 自动化设置 → 自动分析新文章」开启；
3. 回到「今日」查看自动生成的推荐与事件；
4. 如需本地 AI，安装并启动 Ollama，在设置中选择本地模型；`*-cloud` 模型会被拒绝。

用户数据默认保存在：

```text
~/Library/Application Support/PersonalIntelligenceHub/
├── pih.sqlite3
└── backups/
```

---

## 测试

```bash
# 后端（真实 SQLite 临时库，无 Mock 业务数据）
cd Backend && ./.venv/bin/python -m pytest -q

# 前端
cd App && xcodebuild test \
  -project PersonalIntelligenceHub.xcodeproj \
  -scheme PersonalIntelligenceHub \
  -configuration Debug \
  -derivedDataPath ../build/DerivedData
```

当前基线：后端 **557 passed**，Swift XCTest **90 passed**。

> 备份恢复测试要求 Sidecar 未运行，否则会按设计拒绝恢复。

---

## 目录结构

```text
App/            SwiftUI 客户端、XcodeGen 工程源、XCTest
Backend/        FastAPI Sidecar、采集、AI、事件、推荐、数据库与 pytest
Scripts/        构建、打包、备份/恢复与验证脚本
Tests/          真实进程集成检查
Docs/           架构、API、数据库、安全策略、路线图与用户指南
```

---

## 文档

- [架构说明](Docs/ARCHITECTURE.md)
- [API 契约](Docs/API_CONTRACT.md)
- [数据库基线](Docs/DATABASE_BASELINE.md)
- [技术决策](Docs/TECHNICAL_DECISIONS.md)
- [AI Provider 安全策略](Docs/AI_PROVIDER_SECURITY_POLICY.md)
- [macOS 兼容性](Docs/MACOS_COMPATIBILITY.md)
- [用户指南](Docs/USER_GUIDE.md)
- [开发路线图](Docs/DEVELOPMENT_ROADMAP.md)

---

## 已知限制

- 跨来源事件合并仍偏保守，歧义候选需要人工确认；
- 正文抓取为按需单篇，不做全量高频抓取；
- 本地小模型可能输出非法分类，系统会记录失败而不是伪造结果；
- 当前仅提供 macOS 原生客户端。

---

## License

[MIT](LICENSE)
