# PIH Sidecar API 通信契约（Phase 0）

- 文档版本：1.0
- 日期：2026-11-16
- 适用范围：macOS App 与本地 FastAPI Sidecar 之间的进程生命周期、握手、认证、`/health`、错误、日志与版本协商
- 状态：Phase 0 契约已冻结（实现必须逐条满足）
- 关联文档：[ARCHITECTURE.md](./ARCHITECTURE.md)、[DATABASE_BASELINE.md](./DATABASE_BASELINE.md)

> 本文件是 Sidecar 通信的唯一权威契约。任何字段名、端口、环境变量、超时或错误码变更，必须先由 architect 更新本文件并形成 ADR，再修改前后端实现。
> 当前权威位置为 `Docs/API_CONTRACT.md`；若后续迁入 `Docs/contracts/`，需 architect 记录 ADR 并同步全部引用。
> 计划书第 14.2 节中的 `API_REFERENCE.md` 为后期整合文档名，不得据此改变本契约内容。

---

## 1. 常量与术语

| 常量 | 值 | 说明 |
|---|---|---|
| 服务名 | `pih-backend` | 握手与 `/health` 中必须一致 |
| 服务版本 | `0.2.0` | Phase 1；SemVer（Phase 0 为 `0.1.0`） |
| 监听地址 | `127.0.0.1` | 禁止其他地址 |
| 默认端口 | `0` | 由内核分配随机端口 |
| Token 环境变量 | `PIH_SIDECAR_TOKEN` | 唯一传递通道 |
| 数据目录环境变量 | `PIH_DATA_DIR` | 可选；默认不注入 |
| 端口环境变量 | `PIH_PORT` | 可选；默认 `0` |
| 握手前缀 | `PIH_SIDECAR_READY` | 前缀后跟一个空格 |
| 握手超时 | `10` 秒 | 从 spawn 计时 |
| 健康检查超时 | `2` 秒 | 连接 + 响应总时长 |
| 健康轮询间隔 | `5` 秒 | 就绪后 |
| 强制退出等待 | `3` 秒 | SIGTERM 后 |
| 健康检查鉴权头 | `Authorization: Bearer <token>` | 仅请求头，不入 URL |
| 请求追踪头 | `X-Request-ID` | 服务端生成 |

---

## 2. 启动方式

### 2.1 启动模型

App 以**子进程**方式启动 Sidecar，并完全拥有其生命周期：

- Sidecar 不由 launchd、用户手工终端或系统服务管理器启动（开发调试除外）。
- App 负责生成 Token、组装环境变量、启动进程、读取握手、健康检查、重启与退出。
- Sidecar 不读取任何配置文件中的 Token；Token 只来自环境变量。

### 2.2 Phase 0 开发期启动配置

| 项目 | 值 |
|---|---|
| 解释器 | `<repo>/Backend/.venv/bin/python` |
| 入口 | `<repo>/Backend/main.py` |
| 工作目录 | 仓库根目录 |
| 参数 | 仅入口路径；**不得**包含 Token、端口、数据目录等敏感/易变参数 |
| 路径注入 | 由 `App/project.yml` 生成的 DEBUG 配置注入（建议 Info.plist 键 `PIHDevBackendPython`、`PIHDevBackendEntry`），不得包含 Token |
| 发布版 | 打包为 App Bundle 内可执行入口；具体打包方式在 Phase 7 前由 ADR 决定，但不得改变本契约的环境变量/stdout/握手协议 |

> 开发期路径键仅用于 DEBUG 构建。Release 构建若找不到内置 Sidecar，必须展示真实启动失败，不得回退到系统 Python 或静默使用固定端口。

### 2.3 环境变量

| 变量 | 必填 | 默认值 | 校验规则 | 非法时行为 |
|---|---|---|---|---|
| `PIH_SIDECAR_TOKEN` | 是 | 无 | 非空；长度为 43 的 base64url 字符串（无 padding） | stderr 记录 `startup_failed`（不含 Token）→ exit 2，无握手 |
| `PIH_PORT` | 否 | `0` | 整数 `0–65535`；生产/默认必须为 `0` | exit 2，无握手 |
| `PIH_DATA_DIR` | 否 | `~/Library/Application Support/PersonalIntelligenceHub` | 绝对路径；不得指向 App Bundle 或源码目录 | exit 2，无握手 |
| `PYTHONUNBUFFERED` | 否 | 开发期由 App 设为 `1` | `0/1` | 不影响契约；握手必须显式 flush |

补充规则：

- App 默认**不设置** `PIH_DATA_DIR`，让后端使用默认目录；仅当用户显式自定义数据目录时才注入。`/health` 的 `path_kind` 据此取值（见第 6 章）。
- App 不向子进程传递任何 Token 的副本文件、临时文件或命令行参数。
- Sidecar 读取 `PIH_SIDECAR_TOKEN` 后建议立即从 `os.environ` 移除，减少后续意外继承；该动作不改变“同用户进程可能读取初始环境”的残余风险。

### 2.4 启动步骤（必须顺序一致）

1. App 生成 32 字节 Token（见第 5 章），保存在内存。
2. App 组装环境变量：`PIH_SIDECAR_TOKEN`、`PIH_PORT=0`、（可选）`PIH_DATA_DIR`、`PYTHONUNBUFFERED=1`。
3. App 启动子进程，记录 PID，并开始 10 秒握手计时。
4. Sidecar 校验环境变量；非法则记录 stderr 并 exit 2，不输出握手。
5. Sidecar 创建数据目录（若不存在），打开 SQLite，设置 PRAGMA，执行 Migration。**数据库失败不阻止启动**，仅影响 `/health` 结果。
6. Sidecar 绑定 `127.0.0.1:PIH_PORT`。当 `PIH_PORT=0` 时由内核分配端口。
7. uvicorn/ASGI 应用完成 startup。
8. Sidecar 向 stdout 输出 **一行** 握手并立即 flush。
9. App 在 10 秒内读取 stdout 首行，解析并校验。
10. App 使用握手端口执行首次 `GET /health`（2 秒超时），确定 `ready`/`degraded`/`failed`。

时序硬约束：握手必须在 socket 已绑定且 ASGI startup 完成之后输出，保证 App 收到握手后可立即请求 `/health`；总启动预算 10 秒。

---

## 3. 随机端口生成与发现

### 3.1 端口生成

- 默认 `PIH_PORT=0`，由内核在 `127.0.0.1` 上分配空闲端口。
- 推荐实现：先创建 socket 并 `bind(("127.0.0.1", 0))`，读取 `getsockname()[1]`，再把已绑定 socket 交给 uvicorn，避免“选端口→再绑定”的竞态。
- 不得使用固定端口；`PIH_PORT` 非 0 仅用于本地测试与故障注入。

### 3.2 端口发现

- **唯一发现方式**是 stdout 握手行。
- 禁止通过端口文件、固定端口探测、`lsof` 扫描、系统偏好设置或环境变量回传端口。
- 一个 Sidecar 进程只输出一次握手；不得重复输出。

---

## 4. 握手协议

### 4.1 格式

stdout 首行，UTF-8，单行，以 `\n` 结束，写完立即 flush：

```text
PIH_SIDECAR_READY {"port": 53124, "pid": 51234, "service": "pih-backend", "version": "0.1.0"}
```

要求：

- 前缀固定为 `PIH_SIDECAR_READY`，其后紧接**一个空格**，再跟 JSON 对象。
- JSON 必须为对象；不得包含换行；建议紧凑输出；键顺序不敏感。
- 单行长度不得超过 4096 字节。
- 握手内容不得包含 Token、数据目录、环境变量、主机名或用户信息。
- App 必须忽略未知键；必须校验下列已知字段。

### 4.2 字段定义

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `port` | integer | `1–65535` | 实际监听端口 |
| `pid` | integer | `> 0` | Sidecar 进程 PID；必须等于 App 观察到的子进程 PID，用于防端口串话 |
| `service` | string | 固定 `pih-backend` | 服务标识；不匹配视为启动失败 |
| `version` | string | SemVer；Phase 1 为 `0.2.0`（Phase 0 为 `0.1.0`） | 必须与 `/health` 的 `version` 一致 |

### 4.3 App 解析与失败处理

| 情况 | 处理 |
|---|---|
| 子进程在握手前退出 | 立即按退出码/信号判定启动失败，展示 stderr 尾部（过滤敏感信息），不等待满 10 秒 |
| 10 秒内未读到首行 | SIGTERM → 3 秒 → SIGKILL；展示启动超时与 stderr 尾部（过滤敏感信息） |
| 首行超过 4096 字节仍无换行 | 视为协议错误，终止子进程 |
| 前缀不匹配 / JSON 解析失败 | 视为协议错误，终止子进程，展示具体原因 |
| `service` 不匹配 / `port` 越界 / `pid` 不一致 | 视为启动失败，终止子进程 |
| 版本 MAJOR 不兼容 | 视为启动失败，提示版本不匹配 |

App 不得在握手失败后猜测端口、复用旧端口或连接其他本地服务。

---

## 5. Token 生成、传递与验证

### 5.1 生成

- App 每次启动生成 32 字节高熵随机数（`SecRandomCopyBytes` 或等效 CSPRNG）。
- 编码为 base64url（RFC 4648 §5），去除 `=` padding，得到 43 字符、256 位熵的 Token。
- 每次启动重新生成；不缓存、不复用。

### 5.2 传递与存储

| 环节 | 规则 |
|---|---|
| App 内存 | 仅保存在内存；不写 UserDefaults、Keychain、文件、剪贴板、UI 文本 |
| 子进程传递 | 仅通过环境变量 `PIH_SIDECAR_TOKEN` |
| Sidecar 内存 | 启动时读取；不落盘；不写入日志；不通过任何 API 返回 |
| 生命周期 | 随进程结束失效；无刷新/轮换接口 |

### 5.3 验证

- 请求头格式：`Authorization: Bearer <token>`。
- Scheme 大小写不敏感；`Bearer` 与 Token 之间必须恰好一个空格。
- Token 比较必须使用常量时间比较（如 `hmac.compare_digest`）。
- 缺失、格式错误、Token 不匹配一律返回相同的 401 响应，不区分原因，不回显收到的值。

### 5.4 禁止

- 禁止把 Token 放入 URL query、Cookie、请求体、日志、错误响应、崩溃上报或 UI。
- 禁止把 Token 作为命令行参数传递（`ps` 可见）。
- 禁止把 Token 写入任何文件，包括临时文件和测试数据文件。

---

## 6. `GET /health`

### 6.1 请求

```http
GET /health HTTP/1.1
Host: 127.0.0.1:53124
Authorization: Bearer <TOKEN>
Accept: application/json
```

- 仅支持 `GET`；无查询参数；请求体被忽略，且不得记录。
- 必须携带 Bearer Token。
- 健康探测必须轻量：只做数据库可用性与 schema 版本检查，不执行全库完整性扫描。

### 6.2 成功响应（`200`，`status=ok`）

```json
{
  "status": "ok",
  "service": "pih-backend",
  "version": "0.2.0",
  "timestamp": "2026-11-16T03:12:45Z",
  "uptime_seconds": 12.34,
  "database": {
    "status": "ok",
    "schema_version": 3,
    "path_kind": "application_support"
  }
}
```

### 6.3 降级响应（`200`，`status=degraded`）

```json
{
  "status": "degraded",
  "service": "pih-backend",
  "version": "0.2.0",
  "timestamp": "2026-11-16T03:12:45Z",
  "uptime_seconds": 12.34,
  "database": {
    "status": "error",
    "code": "database_unavailable",
    "schema_version": null,
    "path_kind": "application_support"
  }
}
```

### 6.4 未授权响应（`401`）

```json
{
  "error": {
    "code": "unauthorized",
    "message": "未授权：访问令牌缺失或无效"
  }
}
```

响应头必须包含服务端生成的 `X-Request-ID`，且响应体不得出现 Token。

### 6.5 字段定义

| 字段 | 类型 | 必有 | 约束 |
|---|---|---|---|
| `status` | string | 是 | `ok` 或 `degraded` |
| `service` | string | 是 | 固定 `pih-backend` |
| `version` | string | 是 | SemVer；与握手一致 |
| `timestamp` | string | 是 | 请求处理时生成的 UTC RFC3339 时间，必须以 `Z` 结尾；可含小数秒 |
| `uptime_seconds` | number | 是 | 从进程启动起算，非负；使用单调时钟 |
| `database` | object | 是 | 数据库状态对象 |
| `database.status` | string | 是 | `ok` 或 `error` |
| `database.schema_version` | integer \| null | 是 | 已应用迁移的最大 `version`；Phase 0 正常为 `1`；无法读取时为 `null` |
| `database.path_kind` | string | 是 | `application_support`（默认目录）或 `custom`（显式设置 `PIH_DATA_DIR`） |
| `database.code` | string | 否 | 仅当 `database.status=error` 时存在；稳定错误码 |

`database.code` 允许值：

| code | 含义 |
|---|---|
| `database_unavailable` | 无法打开数据库、权限/磁盘 IO 错误、WAL 无法启用 |
| `database_locked` | `busy_timeout` 到期后仍被锁 |
| `database_migration_failed` | 迁移执行失败并已回滚 |
| `database_schema_error` | 校验和不一致、数据库版本高于程序、缺失迁移文件或 schema 不完整 |

补充约束：

- `database.status=error` 时 HTTP 仍为 `200`，**不得**返回 503/500。
- 响应体不得包含 Token、绝对路径、环境变量、主机名、PID、堆栈、SQL。
- 响应体应小于 4 KB。
- App 必须忽略未知字段；不得因新增非破坏性字段而崩溃。

### 6.6 状态码总表

| HTTP | 场景 | 响应体 |
|---|---|---|
| `200` | 健康检查正常或降级 | 第 6.2/6.3 节结构 |
| `401` | 缺少/格式错误/Token 不匹配 | 统一错误体 `unauthorized` |
| `404` | 路径不存在 | 统一错误体 `not_found` |
| `405` | 方法不允许（如 POST /health） | 统一错误体 `method_not_allowed` |
| `422` | 请求校验失败（Phase 0 保留） | 统一错误体 `invalid_request` |
| `500` | 未预期内部错误 | 统一错误体 `internal_error` |

---

## 7. 错误模型

### 7.1 统一结构

```json
{
  "error": {
    "code": "internal_error",
    "message": "服务内部错误"
  }
}
```

- 所有错误（包括框架默认 404/405/422/500）必须经统一异常处理器转换，禁止返回 HTML 或纯文本。
- 鉴权先于路由：无有效 Token 的请求一律返回 401，不区分路径是否存在；通过鉴权后才返回 404/405/422。
- `code` 为稳定英文 snake_case；不得随实现变化。
- `message` 为中文可读说明，不得包含堆栈、SQL、路径或内部实现细节。
- 详细原因只写入 stderr 日志，并通过 `X-Request-ID` 关联。

### 7.2 错误码表

| code | HTTP | 触发条件 | message 示例 |
|---|---|---|---|
| `unauthorized` | 401 | 缺少 `Authorization`、格式错误、Token 不匹配 | `未授权：访问令牌缺失或无效` |
| `not_found` | 404 | 路径不存在 | `请求的资源不存在` |
| `method_not_allowed` | 405 | 方法不被允许 | `请求方法不被允许` |
| `invalid_request` | 422 | 参数/请求体校验失败 | `请求参数无效` |
| `payload_too_large` | 413 | 请求体超过 64 KiB | `请求体过大` |
| `insufficient_storage` | 507 | 可用磁盘低于 1 GiB，拒绝写入 | `存储空间不足，已拒绝写入` |
| `source_not_found` | 404 | 信息源不存在或已软删除 | `信息源不存在` |
| `source_category_not_found` | 404 | 分类不存在或已软删除 | `分类不存在` |
| `source_url_conflict` | 409 | 活动来源 URL 重复 | `该 URL 的信息源已存在` |
| `source_category_name_conflict` | 409 | 活动分类名重复 | `分类名称已存在` |
| `source_category_in_use` | 409 | 删除仍被来源引用的分类 | `该分类仍被信息源引用` |
| `internal_error` | 500 | 未预期异常 | `服务内部错误` |

**`details` 扩展（Phase 1，向后兼容）**：错误对象可包含可选 `details: [{field, reason, message}]`，最多 10 条；只含字段名、稳定 reason 与固定中文说明，**不得回显用户输入**。

> `database_*` 是 `/health` 内部的数据库状态码，不是 HTTP 错误码，不改变 HTTP 200。

### 7.3 `X-Request-ID`

- 服务端为每个请求生成 UUID v4（小写、36 字符），并写入响应头 `X-Request-ID`。
- 所有响应（成功与失败）均必须包含；错误响应为强制要求。
- 不采信客户端传入的 `X-Request-ID`，由服务端覆盖生成。
- 同一请求的日志必须包含相同 `request_id`。
- App 在错误视图中展示该 ID，便于与日志对齐。

### 7.4 响应头

| 头 | 要求 |
|---|---|
| `Content-Type` | `application/json; charset=utf-8` |
| `X-Request-ID` | 必有 |
| `Cache-Control` | `no-store` |
| 其他 | 不得包含 Token 或内部路径 |

---

## 8. 超时、重试与前端行为

### 8.1 超时表

| 动作 | 超时 | 超时后行为 |
|---|---|---|
| 读取握手首行 | 10 秒（从 spawn 起） | 终止子进程（SIGTERM→3 秒→SIGKILL），进入 `failed` |
| `GET /health` | 2 秒（连接 + 响应） | 本次检查失败；按连续失败策略处理 |
| 正常停止等待 | 3 秒 | SIGKILL 并等待回收 |
| 健康轮询间隔 | 5 秒 | 定时触发 |
| 父进程看门狗轮询 | 2 秒 | 检测到父进程消失后 1 秒内退出 |

同一时间只允许一个健康检查在途；上一次未结束不得发起下一次，避免请求堆积。

### 8.2 健康检查与状态

| 事件 | App 行为 |
|---|---|
| 握手成功 | 立即执行首次 `/health` |
| `200` + `status=ok` | 进入 `ready` |
| `200` + `status=degraded` | 进入 `degraded`，展示 `database.code` 与 `schema_version` |
| `401` | 视为契约违例；停止轮询；展示认证失败；不重试同一 Token |
| `404/405/5xx` / 非法 JSON | 视为契约违例；进入 `failed`；展示 `X-Request-ID`（如有） |
| 单次超时/连接失败 | 记录失败计数；UI 显示“健康检查失败（重试中）” |
| 连续 3 次失败 | 进入 `offline`，展示最近成功时间与失败次数 |
| 任一次成功 | 重置失败计数并恢复相应状态 |

### 8.3 Sidecar 不可用与异常退出

| 场景 | App 行为 |
|---|---|
| 首次启动失败 | 展示退出码/信号、协议错误、stderr 尾部（已过滤 Token）；提供真实“重试” |
| 运行中进程退出 | 捕获 exit code/signal，立即进入 `offline`/`failed`；不得继续显示 `ready` |
| 自动重启 | 最多 1 次；再次失败需用户操作 |
| 重启 | 必须重新生成 Token、重新启动进程、重新握手；不得复用旧 Token/端口 |
| App 退出 | 停止轮询 → SIGTERM → 等待 3 秒 → SIGKILL → 回收 |

重试必须有界，禁止无限循环重连。

---

## 9. 停止方式

### 9.1 正常停止

1. App 停止健康轮询。
2. App 向 Sidecar 发送 `SIGTERM`。
3. Sidecar 停止接收新请求，完成在途请求，关闭数据库连接，输出停止日志，`exit 0`。
4. App 最多等待 3 秒。
5. 未退出则 `SIGKILL`，并等待进程回收，避免僵尸进程。
6. App 释放 Token 引用（进程退出即失效）。

### 9.2 崩溃兜底

- App 异常退出/被强杀时，Sidecar 通过 `os.getppid()` 看门狗检测父进程消失，在 1 秒内优雅退出（最坏约 3 秒）。
- Sidecar 被 `SIGKILL` 时，下次启动由 SQLite WAL 自动恢复；不得手工删除 WAL/SHM 文件。

### 9.3 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 正常停止（SIGTERM 或父进程消失后的优雅退出） |
| `2` | 配置错误：Token 缺失/非法、`PIH_PORT` 非法、`PIH_DATA_DIR` 非法 |
| `3` | 端口绑定失败 |
| `4` | 其他致命启动错误（不得与数据库降级混淆） |

数据库不可用/迁移失败**不得**导致非零退出；Sidecar 必须继续提供服务并在 `/health` 中报告降级。

---

## 10. 日志规范

### 10.1 格式

- 仅写 **stderr**；每条日志为单行 JSON 对象，UTF-8。
- stdout 在 Phase 0 **只允许**握手行，禁止 banner、调试输出、第三方库打印。
- uvicorn 的 access/error 日志必须配置到 stderr；禁止任何组件向 stdout 写日志。
- 必须包含字段：`ts`、`level`、`event`、`request_id`。

示例：

```json
{"ts":"2026-11-16T03:12:45Z","level":"info","event":"sidecar_ready","request_id":"-","pid":51234,"port":53124}
{"ts":"2026-11-16T03:12:46Z","level":"info","event":"request_completed","request_id":"9f2c3d8e-7b1a-4c5d-8e9f-0a1b2c3d4e5f","method":"GET","path":"/health","status_code":200,"duration_ms":3.2}
```

### 10.2 字段

| 字段 | 类型 | 必有 | 说明 |
|---|---|---|---|
| `ts` | string | 是 | UTC RFC3339，`Z` 结尾 |
| `level` | string | 是 | `debug`/`info`/`warn`/`error` |
| `event` | string | 是 | 稳定 snake_case 事件名 |
| `request_id` | string | 是 | 请求 UUID；非请求事件为 `-` |
| `method` | string | 否 | HTTP 方法 |
| `path` | string | 否 | 路由路径；不得包含查询串（避免泄漏搜索词等） |
| `status_code` | integer | 否 | HTTP 状态码 |
| `duration_ms` | number | 否 | 处理耗时 |
| `error_code` | string | 否 | 稳定错误码 |
| `pid` / `port` | integer | 否 | 仅启动/停止事件 |
| `path_kind` | string | 否 | 不记录绝对路径 |

### 10.3 最少事件集

`sidecar_starting`、`database_ready`、`database_error`、`migration_applied`、`migration_failed`、`sidecar_ready`、`request_completed`、`request_error`、`sidecar_stopping`、`parent_lost`、`startup_failed`。

### 10.4 禁止记录

- Token、`Authorization` 头、Token 的哈希/前缀/后缀。
- 请求体全文（默认不记录任何请求/响应体）。
- 环境变量转储、数据库绝对路径、用户主目录。
- 堆栈不得进入 HTTP 响应；日志中可记录异常类型与 `request_id`，不记录敏感参数值。

---

## 11. 版本策略

### 11.1 版本号

- 采用 SemVer：`MAJOR.MINOR.PATCH`；Phase 0 为 `0.1.0`，Phase 1 为 `0.2.0`（新增 `/api/v1` 业务端点，向后兼容）。
- 握手 `version` 与 `/health` 的 `version` 必须完全一致，来源于同一常量。
- `PATCH`：修复缺陷，不改变协议。
- `MINOR`：新增向后兼容字段/端点。
- `MAJOR`：破坏性协议变更。

### 11.2 兼容规则

- App 必须校验 `service == "pih-backend"`。
- App 必须校验 MAJOR 一致；MAJOR 不一致时拒绝连接并提示升级。
- App 必须忽略未知字段，保证 MINOR 升级兼容。
- 破坏性变更必须：更新本契约 → 写 ADR → 前后端同步发布 → qa-security 做契约回归。

### 11.3 路径版本

- `/health` 为运维端点，不带版本前缀。
- Phase 1 起业务接口统一使用 `/api/v1` 前缀；新增业务端点不得复用 `/health`。

---

## 12. 测试方法与 curl 示例

### 12.1 curl 示例（Token 用 `<TOKEN>` 占位）

```bash
# 正常请求
curl -sS -i \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Accept: application/json" \
  "http://127.0.0.1:<PORT>/health"

# 未授权
curl -sS -i \
  "http://127.0.0.1:<PORT>/health"

# 错误 Token
curl -sS -i \
  -H "Authorization: Bearer wrong-token" \
  "http://127.0.0.1:<PORT>/health"
```

预期：

- 正常：`200`，`status` 为 `ok` 或 `degraded`，含 `X-Request-ID`。
- 未授权/错误 Token：`401`，错误体 `code=unauthorized`，不含 Token。

### 12.2 本地完整验证脚本

该脚本把 Token 保存在 shell 变量与子进程环境中；仅将握手行与 stderr 写入临时文件（不含 Token）。

```bash
cd "/path/to/PersonalIntelligenceHub"

TOKEN="$(python3 - <<'PY'
import base64, os
print(base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode())
PY
)"
TMP_DIR="$(mktemp -d)"
trap 'if [ -n "${SIDE_PID:-}" ]; then kill -TERM "$SIDE_PID" 2>/dev/null; fi; rm -rf "$TMP_DIR"' EXIT

PIH_SIDECAR_TOKEN="$TOKEN" \
PIH_PORT=0 \
PIH_DATA_DIR="$TMP_DIR/data" \
PYTHONUNBUFFERED=1 \
Backend/.venv/bin/python Backend/main.py \
  >"$TMP_DIR/handshake.txt" 2>"$TMP_DIR/stderr.log" &
SIDE_PID=$!

for _ in $(seq 1 100); do
  [ -s "$TMP_DIR/handshake.txt" ] && break
  sleep 0.1
done

head -n 1 "$TMP_DIR/handshake.txt"

PORT="$(python3 - "$TMP_DIR/handshake.txt" <<'PY'
import json, sys
line = open(sys.argv[1], encoding="utf-8").readline().strip()
prefix, payload = line.split(" ", 1)
assert prefix == "PIH_SIDECAR_READY", prefix
print(json.loads(payload)["port"])
PY
)"

curl -sS -i -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/health"
curl -sS -i "http://127.0.0.1:$PORT/health"
```

### 12.3 必须覆盖的验证项

| 验证项 | 方法 | 期望 |
|---|---|---|
| stdout 仅握手 | `wc -l < handshake.txt` | `1` |
| 仅监听 loopback | `lsof -nP -iTCP:$PORT -sTCP:LISTEN` | `127.0.0.1:$PORT`，无 `*`/`0.0.0.0` |
| Token 不泄漏 | 对 `/health` 响应与 stderr 执行 `grep -F "$TOKEN"` | 无输出 |
| 401 | 无 Token / 错 Token | `401` + 统一错误体 |
| 降级 | 使数据目录不可写或迁移失败 | `200` + `status=degraded` |
| 优雅退出 | `kill -TERM $SIDE_PID` | 3 秒内退出，退出码 `0` |
| 进程回收 | `kill -9` App 后观察 Sidecar | 约 3 秒内消失 |

---

## 13. 禁止事项清单

1. 禁止使用固定端口或固定 Token。
2. 禁止将 Token 放入 argv、文件、URL、Cookie、UserDefaults、Keychain、UI、日志或错误响应。
3. 禁止监听 `0.0.0.0`、`::` 或其他非 loopback 地址。
4. 禁止在 stdout 输出握手以外的任何内容。
5. 禁止在 `/health` 返回绝对路径、环境变量、主机名、PID、Token 或数据库内容。
6. 禁止用 `503`/`500` 表示数据库降级；必须 `200 + degraded`。
7. 禁止静默失败、无限重试或把失败状态显示为正常。
8. 禁止使用 mock/静态数据冒充健康状态、版本或数据库可用性。
9. 禁止启用 CORS；Phase 0 禁止开放 `/docs`、`/redoc`、`/openapi.json`。
10. 禁止在错误响应中回显客户端输入、堆栈、SQL 或内部路径。
11. 禁止修改握手字段名、错误码或环境变量名而不更新本契约。
12. 禁止 App 在握手失败后猜测端口或复用旧 Token/端口。

---

## 14. 变更流程

1. 提出变更的 Agent 向 architect 说明动机、兼容性与影响范围。
2. architect 更新本契约；破坏性变更需 ADR 写入 `Docs/TECHNICAL_DECISIONS.md`。
3. backend-developer 与 macos-developer 按同一版本契约实现。
4. qa-security 执行契约回归（握手、认证、`/health` 三种状态、超时、退出、日志脱敏）。
5. 契约与实现不一致时，以本契约为准并回退实现。

---

## 15. Phase 1 业务端点（`/api/v1`）

Phase 1 只开放信息源与分类；**不开放**文章、采集、搜索、AI 或备份端点。完整字段与示例见 `Docs/PHASE1_API_DESIGN.md`。

| 方法 | 路径 | 成功 | 说明 |
|---|---|---|---|
| GET | `/api/v1/source-categories` | 200 | 分页列表，`source_count` 为活动来源数 |
| GET | `/api/v1/source-categories/all` | 200 | 全部活动分类（表单选择用） |
| POST | `/api/v1/source-categories` | 201 | 创建分类 |
| GET | `/api/v1/source-categories/{id}` | 200 | 详情 |
| PATCH | `/api/v1/source-categories/{id}` | 200 | 部分更新 |
| DELETE | `/api/v1/source-categories/{id}` | 204 | 软删除；被引用 → 409 |
| GET | `/api/v1/sources` | 200 | 分页 + `q`/类型/分类/未分类/启停过滤 + 排序白名单 |
| POST | `/api/v1/sources` | 201 | 创建来源；服务端校验 URL；不发起网络请求 |
| GET | `/api/v1/sources/{id}` | 200 | 详情 |
| PATCH | `/api/v1/sources/{id}` | 200 | 部分更新（含启停） |
| DELETE | `/api/v1/sources/{id}` | 204 | 软删除，保留历史 |

通用约束：

- 认证、`X-Request-ID`、`Cache-Control: no-store`、统一错误体与 Phase 0 完全一致。
- 分页 `limit` 默认 20、上限 100；`offset` 上限 10000。
- 请求体上限 64 KiB；`POST`/`PATCH` 均适用。
- 删除均为软删除；`deleted_at IS NULL` 唯一性由部分唯一索引保证。
- 备份/恢复为本地运维命令（`Scripts/backup_db.py`、`Scripts/restore_db.py`），不经 HTTP 暴露。

---

## 16. Phase 2 业务端点（`/api/v1`）

文章、采集任务、来源健康与采集引擎状态。完整字段、状态机与错误码见 [PHASE2_API.md](./PHASE2_API.md)。

| 方法 | 路径 | 成功 | 说明 |
|---|---|---|---|
| GET | `/api/v1/articles` | 200 | 文章分页、过滤、排序 |
| GET | `/api/v1/articles/{id}` | 200 | 文章详情（纯文本正文） |
| POST | `/api/v1/sources/{id}/collect` | 202 | 单来源采集 |
| POST/GET | `/api/v1/collection-jobs` | 202/200 | 创建/列出采集任务 |
| GET | `/api/v1/collection-jobs/{id}` | 200 | 任务详情 |
| POST | `/api/v1/collection-jobs/{id}/cancel` `/retry` | 200/202 | 取消/重试 |
| GET | `/api/v1/sources/{id}/health` | 200 | 来源健康日志 |
| GET | `/api/v1/collection/status` | 200 | 采集引擎状态 |

## 17. Phase 3 业务端点（`/api/v1`）

本地 AI 状态、模型白名单、分析运行与文章分析。完整字段、请求体与错误码见 [PHASE3_API.md](./PHASE3_API.md)。

| 方法 | 路径 | 成功 | 说明 |
|---|---|---|---|
| GET | `/api/v1/ai/status` | 200 | Provider 可用性、默认模型、队列、Embedding 状态 |
| GET | `/api/v1/ai/models` | 200 | 模型注册表 + 实时安装/远端标记 |
| POST | `/api/v1/ai/runs` | 202 | 创建分析运行（`selected`/`unanalyzed`） |
| GET | `/api/v1/ai/runs` | 200 | 运行分页列表 |
| GET | `/api/v1/ai/runs/{id}` | 200 | 运行详情 + 逐篇条目 |
| POST | `/api/v1/ai/runs/{id}/pause` `/resume` `/cancel` `/retry` | 200/202 | 运行控制 |
| GET | `/api/v1/articles/{id}/analysis` | 200 | 文章最新分析结果 |
| POST | `/api/v1/articles/{id}/analyze` | 202 | 单篇分析运行 |

AI 端点沿用同一认证、错误体与 `no-store`；Provider 只允许 `http://127.0.0.1:11434`，`*-cloud` 模型在发请求前阻断。
