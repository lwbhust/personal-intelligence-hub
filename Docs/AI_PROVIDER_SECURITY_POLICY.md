# PIH AI Provider 安全边界政策（Phase 1 前置）

- 文档版本：1.0
- 日期：2026-11-16
- 对应阶段任务：Stage 1.0.3 Ollama 安全边界审查
- 适用范围：Phase 1 及以后所有可能接触本地模型/云模型的代码、配置与验收
- 关联文档：[PHASE1_PRECHECK.md](./PHASE1_PRECHECK.md)、[LOCAL_AI_AUDIT.md](./LOCAL_AI_AUDIT.md)、[ARCHITECTURE.md](./ARCHITECTURE.md) §8–§10、[TECHNICAL_DECISIONS.md](./TECHNICAL_DECISIONS.md)（ADR-0010）
- 状态：**政策已定，Phase 1 不实现任何 AI 能力**

---

## 1. 本轮实测现状（2026-11-16 16:01 CST）

```text
$ lsof -nP -iTCP:11434 -sTCP:LISTEN
COMMAND  PID USER  FD  TYPE  DEVICE SIZE/OFF NODE NAME
ollama  1137  lwb   4u IPv6  …      0t0      TCP *:11434 (LISTEN)

$ curl -s http://127.0.0.1:11434/api/version
{"version":"0.40.15"}
```

| 模型 | 大小 | 类型 | remote_host |
|---|---|---|---|
| qwen3.5:4b-mlx | 3.97 GB | 本地 | — |
| qwen3:1.7b | 1.36 GB | 本地 | — |
| gemma3:4b | 3.34 GB | 本地 | — |
| gpt-oss:20b-cloud | 381 B（仅清单） | 云端代理 | `https://ollama.com:443` |
| gpt-oss:120b-cloud | 384 B（仅清单） | 云端代理 | `https://ollama.com:443` |
| deepseek-v3.1:671b-cloud | 405 B（仅清单） | 云端代理 | `https://ollama.com:443` |
| qwen3-coder:480b-cloud | 382 B（仅清单） | 云端代理 | `https://ollama.com:443` |

历史审计记录（`LOCAL_AI_AUDIT.md` §2.3）：服务端环境存在 `OLLAMA_HOST=0.0.0.0`、`OLLAMA_NO_CLOUD=0`、`OLLAMA_CONTEXT_LENGTH=32768`。

事实结论：

1. Ollama 监听**所有网卡**，同网段设备可无认证调用本地推理（SEC-01）。
2. 云端通道处于开启状态，4 个 `-cloud` 模型可直接把内容发往 `ollama.com`（SEC-02 / RISK-03）。
3. 默认上下文 32768，未显式传 `num_ctx` 时会显著增加内存占用（16 GiB 机器上有换页风险）。
4. **Phase 0 代码完全不调用 Ollama**；`/health` 契约中不含任何 Ollama 字段。

---

## 2. 核心原则（不可协商）

| # | 原则 | 落地要求 |
|---|---|---|
| P1 | PIH 默认只允许访问本机 Ollama | 只允许 `http://127.0.0.1:11434`；禁止 `0.0.0.0`、局域网 IP、主机名、`localhost` 之外的解析 |
| P2 | 默认禁止自动使用 `-cloud` 模型 | 模型名包含 `-cloud`、或 `/api/tags` 中带 `remote_host` 的条目，一律拒绝 |
| P3 | AI Provider 必须显式配置 | 模型名、`num_ctx`、超时、并发上限只能来自显式配置/注册表；禁止硬编码默认值 |
| P4 | 本地模型不可用时，不允许自动将数据发送至云端 | 本地不可用 → 任务排队或标记失败（`model_unavailable`）；**禁止任何 fallback 到云** |
| P5 | 云端模型必须获得用户明确授权后才允许启用 | 需逐模型、可撤销、留痕的授权记录；无授权时云端路径在代码层不可达 |
| P6 | 任何 AI 请求都必须可追溯 Provider 与模型 | 每次调用记录：provider 类型、模型名、模型 digest、`num_ctx`、参数、Prompt 版本、耗时、时间、`request_id` |

补充规则：

- 采集到的网页/RSS/正文一律视为**不可信数据**，只能作为提示词内容，不得作为系统指令执行（Prompt Injection 防护）。
- AI 输出必须经 JSON Schema 校验；校验失败有限重试后标记失败，不得降级为「猜一个结果」。
- AI 不参与任何安全判定（如 URL 白名单、权限判断）。
- 未显式传 `num_ctx` 视为缺陷，不得进入生产路径。

---

## 3. Phase 1 的 AI 边界

Phase 1 **不实现任何 AI 业务能力**，且不得用空壳占位：

| 项目 | Phase 1 是否允许 | 说明 |
|---|---|---|
| 调用 Ollama / 任何模型 | 否 | Phase 1 无 AI 数据流 |
| 新增 `Backend/ai_engine/**`、`ranking_engine/**` | 否 | 属 Phase 3/4；空目录或空类违反 `ARCHITECTURE.md` §6.3 |
| `BaseLLMProvider` 抽象与空实现 | 否 | 接口预留只体现在文档，不写空类 |
| 空路由 `/api/v1/ai/status` | 否 | 未实现的能力不得暴露端点 |
| `Resources/prompts/**`、`model_profiles/**` | 否 | Phase 3 起创建 |
| 未被任何代码引用的「未来常量」模块 | 否 | 同属空壳，禁止 |
| 本政策文档 + 只读审计证据 | **是** | 唯一允许的 AI 相关交付 |
| 把白名单规则写入测试断言 | 否（Phase 1） | 白名单必须依附真实 Provider 才能被测试；提前写即空壳 |
| 在验收清单中登记 Phase 3 进入条件 | **是** | 见第 6 节 |

判断标准：任何 AI 相关文件，若 Phase 1 内无真实调用方，即视为越界交付，必须回退。

---

## 4. Provider 白名单设计（Phase 3 实施，Phase 1 仅冻结规则）

### 4.1 允许集合

```text
provider: ollama-local
base_url: http://127.0.0.1:11434
allowed_models: <显式配置的本地模型名白名单，初始候选>
  - qwen3:1.7b
  - gemma3:4b
  - qwen3.5:4b-mlx
```

### 4.2 拒绝规则（拒绝优先于允许）

1. 模型名匹配 `-cloud` 后缀或包含 `-cloud` → 拒绝。
2. `/api/tags` 返回条目含非空 `remote_host` → 拒绝。
3. `base_url` 主机不是 `127.0.0.1` → 拒绝。
4. 端口不是 `11434`（除非显式配置且经用户确认） → 拒绝。
5. 任何 HTTP 代理变量（`http_proxy`/`https_proxy`/`all_proxy`）作用于本地请求 → 视为配置错误，强制 `no_proxy` 覆盖 `127.0.0.1`。

### 4.3 失败语义

| 场景 | 行为 |
|---|---|
| Ollama 未运行 | 任务标记 `model_unavailable`，排队等待；阅读/搜索不受影响 |
| 模型不在白名单 | 立即失败，记录 `model_not_allowed`，不尝试其他模型 |
| 云端模型被请求 | 立即失败，记录 `cloud_model_blocked`，不发起网络请求 |
| 输出 Schema 校验失败 | 有限重试（≤2 次）后标记失败；不写入半成品分析结果 |

---

## 5. 可追溯性要求

每次 AI 调用必须持久化（Phase 3 的 `ai_runs` / `article_ai_analysis`）：

| 字段 | 说明 |
|---|---|
| `provider_kind` | 固定 `ollama-local`（未来云端需区分 `ollama-cloud` 并附授权 ID） |
| `model_name` | 实际使用的模型名 |
| `model_digest` | `/api/tags` 返回的 digest，防止模型被替换 |
| `num_ctx` | 显式传入的上下文长度 |
| `prompt_version` | Prompt 模板版本号 |
| `params` | temperature 等关键参数 |
| `duration_ms` / `created_at` / `request_id` | 耗时、时间、与日志关联的请求 ID |
| `authorization_id` | 仅云端调用时存在，指向用户授权记录 |

禁止记录：完整 Prompt 中的用户私密内容（除非用户明确开启调试）、Token、绝对路径。

---

## 6. 门禁与关闭阶段

| 编号 | 事项 | 必须关闭于 | 关闭判据 |
|---|---|---|---|
| SEC-01 | Ollama 监听 `0.0.0.0:11434` | Phase 3 进入前 | 改为 `127.0.0.1`，或用户书面接受风险并限制使用范围 |
| SEC-02 | 无模型白名单，`-cloud` 可被误用 | Phase 3 进入前 | Provider 白名单拒绝 `*-cloud`，有自动化测试证明 |
| RISK-03 | `-cloud` 模型存在 | Phase 3 进入前 | 同 SEC-02 |
| AI-01 | 无 Embedding 模型 | Phase 3 内（需用户确认） | 下载并实测；未确认前语义能力禁用 |
| AI-CTX | `OLLAMA_CONTEXT_LENGTH=32768` | Phase 3 进入前 | Provider 显式传 `num_ctx`，不依赖服务端默认 |

Phase 1 不阻断于上述事项，但**必须在 Phase 1 验收文档中保留这些未关闭项**，不得宣称已解决。

---

## 7. 需用户确认的系统级动作（2026-11-16 裁决更新）

用户 C5 裁决：

- **批准**将 Ollama 监听收敛到 `127.0.0.1`。
- **不批准**删除任何 Cloud 模型。
- 执行前必须先确认是否存在其他局域网调用依赖，并提供修改与回滚方案；若可能影响其他应用，暂停并向用户说明，不得擅自执行。

| 编号 | 动作 | 裁决 | 当前状态 |
|---|---|---|---|
| A1 | 将 `OLLAMA_HOST` 改为 `127.0.0.1:11434` | **已批准，待执行** | 未执行（需先完成第 7.1 节依赖确认） |
| A2 | 设置 `OLLAMA_NO_CLOUD=1` | 未单独批准 | 建议随 A1 一并评估；执行前需用户确认 |
| A3 | 删除 4 个 `-cloud` 模型 | **不批准** | 保持现状 |
| A4 | 下载 Embedding 模型（0.3–1.2 GB） | 未批准 | Phase 3 且磁盘达标后另行申请 |
| A5 | 升级 Python 补丁版本 | 未批准 | 保持 3.14.8 |

### 7.1 执行 A1 前的依赖确认步骤（只读，不修改）

1. 记录当前监听：`lsof -nP -iTCP:11434 -sTCP:LISTEN`（当前为 `*:11434`）。
2. 记录进程环境：`ps eww -p <ollama_pid> | tr ' ' '\n' | grep -i '^OLLAMA'`（当前含 `OLLAMA_HOST=0.0.0.0`、`OLLAMA_NO_CLOUD=0`）。
3. 检查本机是否有非 loopback 连接：`lsof -nP -iTCP:11434 -sTCP:ESTABLISHED`，观察对端地址是否来自局域网。
4. 检查 LaunchAgent/配置来源：`launchctl print gui/$UID | grep -i ollama`、`ls ~/Library/LaunchAgents | grep -i ollama`、Ollama.app 偏好设置。
5. **询问用户**：是否有其他设备/应用（手机、平板、另一台电脑、IDE 插件、本地脚本）通过局域网 IP 访问本机 Ollama。此项无法由命令行可靠推断。
6. 若存在依赖：暂停，向用户说明受影响对象，提供「保留 `0.0.0.0` + 书面接受」或「收敛 + 调整依赖方」两个选项。
7. 若不存在依赖：向用户提交 A1 执行与回滚方案，获得确认后执行。

### 7.2 修改与回滚方案（待批准后执行）

| 阶段 | 操作 |
|---|---|
| 备份 | 记录当前 `OLLAMA_HOST`、`OLLAMA_NO_CLOUD`、启动方式（Ollama.app 登录项/LaunchAgent/手动） |
| 修改 | 设置 `OLLAMA_HOST=127.0.0.1:11434`（写入用户级 LaunchAgent 或 Ollama.app 设置，**不修改系统级文件**） |
| 重启 | 重启 Ollama 服务（`launchctl kickstart -k` 或退出 Ollama.app 后重开） |
| 验证 | `lsof -nP -iTCP:11434 -sTCP:LISTEN` 必须显示 `127.0.0.1:11434`；`curl 127.0.0.1:11434/api/version` 正常；模型列表仍为 7 个 |
| 回归 | PIH 仍能访问（Phase 3 前无调用，仅确认端口可达） |
| 回滚 | 删除新增的 `OLLAMA_HOST` 配置并重启服务，恢复 `*:11434`；或设置回 `0.0.0.0` |
| 记录 | 在本文与 `PHASE1_ADR.md` ADR-0014 记录执行时间、命令、前后 `lsof` 输出、回滚验证 |

> 本轮**未执行任何修改**。A1 属系统级配置变更，必须按上述步骤获得用户确认后执行。

---

## 7.3 PIH 安全要求（用户 C5 重申，纳入验收）

1. PIH 默认只调用本地模型。
2. 禁止自动切换到 `-cloud` 模型。
3. 本地模型不可用时不得自动向云端发送数据。
4. 云端模型调用必须经过用户明确授权。
5. 模型 Provider 和实际模型必须可追溯。

以上 5 条与第 2 节 P1–P6 一致，Phase 3 验收时必须逐条提供测试证据。

---

## 8. 残余风险（如实记录）

| 编号 | 级别 | 风险 | 说明 |
|---|---|---|---|
| AI-R1 | P2 | 局域网无认证访问本地模型 | 非 PIH 引入，属系统级配置；Phase 3 前关闭 |
| AI-R2 | P2 | `-cloud` 模型可被误用导致数据出网 | Phase 1 无调用路径；Phase 3 前代码层强制白名单 |
| AI-R3 | P3 | 16 GiB 内存 + 32768 上下文易换页 | Phase 3 显式 `num_ctx` + 并发上限 1 |
| AI-R4 | P3 | 无 Embedding 模型 | Phase 3 需用户确认后下载 |
| AI-R5 | 信息 | 未核对模型许可证与分发条款 | Phase 7 前随依赖审计一并处理 |

---

## 9. 验收检查清单（Phase 1 内可执行的验证）

- [x] 已确认产品代码不含任何 Ollama/模型调用（`grep -rniE "ollama|11434" Backend/main.py Backend/api Backend/core Backend/database App/PersonalIntelligenceHub App/Resources App/project.yml` → `NO_HITS`）
- [x] 已确认未创建 `ai_engine/**`、`ranking_engine/**`、`Resources/prompts/**`（`find Backend App` 无该目录）
- [x] 已确认产品代码唯一外部主机为 `http://127.0.0.1:`（`grep -rnoE "https?://[a-zA-Z0-9._:-]+" …` 仅命中 `App/PersonalIntelligenceHub/Services/APIClient.swift`）
- [x] 已记录 Ollama 监听状态、模型清单、`-cloud` 条目（本文件第 1 节）
- [x] 已明确未经用户确认不得修改系统配置（第 7 节）
- [ ] Phase 3 前：白名单测试通过（待 Phase 3）
- [ ] Phase 3 前：`num_ctx` 显式传递（待 Phase 3）

> 方框为勾选状态示意；Phase 1 内只完成前四项，后两项留待 Phase 3。
