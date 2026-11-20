# PIH Python 依赖兼容性报告（Phase 1 前置）

- 文档版本：1.0
- 日期：2026-11-16
- 对应阶段任务：Stage 1.0.2 Python 依赖兼容性审计
- 审计对象：`Backend/pyproject.toml`、`Backend/.venv` 全部直接与关键间接依赖、Phase 2 计划新增依赖（Phase 1 不新增依赖）
- 方法：本机 `pip list` / `*.dist-info/WHEEL` / `Requires-Python` 元数据 + PyPI JSON API 元数据 + 现有测试真实执行
- 关联文档：[PHASE1_PRECHECK.md](./PHASE1_PRECHECK.md)、[ARCHITECTURE.md](./ARCHITECTURE.md)、[TECHNICAL_DECISIONS.md](./TECHNICAL_DECISIONS.md)（ADR-0001）

---

## 1. 结论

| 结论项 | 结果 |
|---|---|
| 当前 Python 版本 | **3.14.8**（Homebrew `python@3.14`）；`Backend/.venv` 同为 3.14.8 |
| 3.14 是否为稳定受支持版本 | 是。3.14 于 2025-10-07 发布，EOL 2030-10-31，当前最新补丁 3.14.10 |
| 是否存在阻断性兼容问题 | **无**。Phase 0 全部 57 项后端测试、68 项集成检查在 3.14.8 上真实通过 |
| 是否需要源码编译 | **不需要**。现有依赖中仅 `pydantic_core` 为二进制，且已有 `cp314-macosx_11_0_arm64` 预编译 wheel |
| Phase 2 计划新增依赖是否有 3.14 兼容版本 | **有**。`feedparser 6.0.14`、`defusedxml 0.7.1` 均为纯 Python；`httpx 0.28.1` 已在 venv |
| 最低支持 Python 版本 | `pyproject.toml` 声明 `>=3.12`；**实际仅在 3.14.8 上验证** |
| 是否需要增加 3.12/3.13 验证环境 | 当前**不需要**；Phase 7 发布前若对外声明 3.12+，须补验证或收紧声明 |
| 是否修改现有运行环境 | **否**。不升级、不降级、不重建 venv |

总体判定：**PASS（带记录项）**。ADR-0001 中「Python 3.14 缺少生态支持」的风险，在本机实际依赖集合上已不成立，降级为低风险；但不得据此声称「3.12 已验证」。

---

## 2. 当前环境

```text
$ python3 --version
Python 3.14.8
$ which python3
/opt/homebrew/bin/python3
$ Backend/.venv/bin/python --version
Python 3.14.8
$ Backend/.venv/bin/python -c "import sqlite3; print(sqlite3.sqlite_version)"
3.53.4
$ Backend/.venv/bin/python -c "import sqlite3; con=sqlite3.connect(':memory:'); \
    print(con.execute(\"select sqlite_compileoption_used('ENABLE_FTS5')\").fetchone())"
(1,)
```

本机可用解释器：`python3.14`（3.14.8）、`python3.11`（3.11.12）、`/usr/bin/python3`（3.9.6）。**未安装 3.12 / 3.13。**

Python 3.14 版本线状态（`endoflife.date` API 实测）：

| cycle | 发布日期 | EOL | 最新补丁 |
|---|---|---|---|
| 3.15 | 2026-10-09 | 2031-10-31 | 3.15.2 |
| **3.14** | **2025-10-07** | **2030-10-31** | **3.14.10** |
| 3.13 | 2024-10-07 | 2029-10-31 | 3.13.18 |
| 3.12 | 2023-10-02 | 2028-10-31 | 3.12.16 |

本机 3.14.8 落后当前补丁 2 个版本（3.14.9/3.14.10），属正常滞后，不构成风险；升级需用户授权且必须重跑全套测试。

---

## 3. 现有依赖清单（`Backend/.venv`，共 23 包）

`pyproject.toml` 直接依赖：

| 包 | 锁定版本 | Requires-Python | wheel 类型 | 结论 |
|---|---|---|---|---|
| fastapi | 0.163.1 | >=3.11 | py3-none-any | 兼容 |
| uvicorn | 0.54.0 | >=3.10 | py3-none-any | 兼容 |

可选 dev 依赖：

| 包 | 锁定版本 | Requires-Python | wheel 类型 | 结论 |
|---|---|---|---|---|
| pytest | 9.2.0 | — | py3-none-any | 兼容（57 项真实运行） |
| httpx | 0.28.1 | >=3.8 | py3-none-any | 兼容 |

关键间接依赖：

| 包 | 版本 | Requires-Python | wheel 类型 | 结论 |
|---|---|---|---|---|
| starlette | 1.10.0 | >=3.11 | py3-none-any | 兼容 |
| pydantic | 2.14.3 | >=3.10 | py3-none-any | 兼容 |
| **pydantic_core** | **2.50.4** | >=3.10 | **cp314-cp314-macosx_11_0_arm64** | 兼容（有 3.14 arm64 预编译 wheel） |
| anyio | 4.16.0 | >=3.10 | py3-none-any | 兼容 |
| h11 / httpcore / certifi / idna / click / typing_extensions / typing-inspection / annotated-types / annotated-doc / packaging / pluggy / iniconfig / Pygments / opentelemetry-api | 见 `pip list` | 均满足 3.14 | py3-none-any | 兼容 |

源码编译检查：

- `site-packages` 顶层无 `.so` / `.dylib` 残留（除 `pydantic_core` 子目录内的扩展模块）。
- 唯一二进制包 `pydantic_core` 的 WHEEL 标签为 `cp314-cp314-macosx_11_0_arm64`，说明原生支持 3.14 + Apple Silicon，**无需从源码编译 Rust**。

---

## 4. Phase 2 计划新增依赖的兼容性

Phase 2 若实现 RSS/Atom 采集（Phase 1 已裁决不采集，见 `PHASE1_ADR.md` ADR-0012），最小新增集合如下：

| 包 | 版本 | 依赖形态 | Python 3.14 支持 | 来源 |
|---|---|---|---|---|
| feedparser | 6.0.14 | `py3-none-any` 纯 Python | `Requires-Python: >=3.10`；classifiers 明确含 `Python :: 3.14` | PyPI JSON API |
| feedparser-sgmllib | >=2,<3 | 纯 Python | 随 feedparser 安装 | PyPI `requires_dist` |
| defusedxml | 0.7.1 | `py3-none-any` 纯 Python | 无版本上限限制，兼容 3.14 | PyPI JSON API |
| httpx | 0.28.1 | 已在 venv | 已实测 | 本机 |

可选（**Phase 1 不建议引入**）：

| 包 | 版本 | 说明 |
|---|---|---|
| lxml | 6.1.3 | 有 `cp314-cp314-macosx_10_15_universal2` wheel，可用；但为 C 扩展，增加体积与供应链面。Phase 1 无必需要求，不引入 |

结论：Phase 2 的全部计划依赖均为**纯 Python 或已有 3.14 原生 wheel**，不存在源码编译、平台架构或 ABI 问题。Phase 1 不新增第三方依赖。

### 4.1 版本锁定要求

- `feedparser`、`defusedxml` 必须写死精确版本（`==`）并纳入 `pyproject.toml`，变更需 architect 批准。
- feedparser 采用宽松解析策略，次版本行为可能变化，禁止使用 `>=` 浮动范围。
- 不在 Phase 1 引入 ORM、向量库、云 SDK（`ARCHITECTURE.md` §8.5）。

---

## 5. 最低支持版本与验证策略

| 问题 | 结论 |
|---|---|
| `requires-python` 声明 | 当前为 `>=3.12` |
| 实际验证版本 | 仅 3.14.8 |
| 是否必须降级到 3.12/3.13 | 否。该 Sidecar 只在本机随 App 运行，Phase 7 前会决定打包方式（可能内置解释器），跨版本支持不是当前必需 |
| 是否需要新增 3.12/3.13 验证环境 | 当前不需要。若 Phase 7 决定对外声明 3.12+ 支持，或需在干净机器安装，必须补 3.12/3.13 的 `pytest` + 集成检查，否则应收紧声明为 `>=3.14` |
| 建议记录 | 在 `TECHNICAL_DECISIONS.md` 的 ADR-0001 补充「2026-11-16 复核：Phase 1 计划依赖均支持 3.14，风险降级为低」 |

---

## 6. 升级/降级判断

| 选项 | 判断 | 理由 |
|---|---|---|
| 升级到 3.14.10 | 暂不执行 | 补丁升级风险低但需重跑全套测试；当前无安全公告驱动，未经用户授权不动运行环境 |
| 升级到 3.15 | 不执行 | 3.15 发布仅 1 个月，生态未充分验证 |
| 降级到 3.13/3.12 | 不执行 | 本机未安装；现有依赖在 3.14 上实测通过；降级需重建 venv 并重跑全部测试，收益不足 |
| 保持 3.14.8 | **采用** | 环境稳定、测试可复现；风险已记录 |

---

## 7. 风险与缓解

| 编号 | 级别 | 风险 | 缓解 |
|---|---|---|---|
| PY-01 | 低 | 声明 `>=3.12` 但仅验证 3.14.8 | Phase 7 前补验证或收紧声明；在 README 标注实际验证版本 |
| PY-02 | 低 | 3.14 补丁落后（3.14.8 vs 3.14.10） | 记录在案；有安全公告或打包需求时再升级并重跑测试 |
| PY-03 | 低 | feedparser 宽松解析行为随版本漂移 | 锁定精确版本；解析器用固定 Fixture 做回归 |
| PY-04 | 信息 | 依赖 CVE 未核对（SEC-06） | Phase 7 发布前做依赖审计与许可证核对 |

---

## 8. 本轮实际执行的命令

```bash
python3 --version
which python3
Backend/.venv/bin/python --version
Backend/.venv/bin/python -m pip list --format=freeze
Backend/.venv/bin/python -c "import sqlite3; print(sqlite3.sqlite_version)"
Backend/.venv/bin/python -c "…sqlite_compileoption_used('ENABLE_FTS5')…"
for d in Backend/.venv/lib/python3.14/site-packages/*.dist-info; do grep -h "^Tag:" "$d/WHEEL"; done
for p in fastapi uvicorn starlette pydantic pydantic_core httpx anyio; do grep -i '^Requires-Python:' …; done
curl -s https://pypi.org/pypi/{feedparser,defusedxml,lxml,httpx}/json
curl -s https://endoflife.date/api/python.json
cd Backend && .venv/bin/python -m pytest tests -q
```
