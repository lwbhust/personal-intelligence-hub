# PIH macOS 兼容性策略（Phase 1 前置）

- 文档版本：1.0
- 日期：2026-11-16
- 对应决策：用户 C4（保留 macOS 14 最低支持目标）
- 关联文档：[PHASE1_PRECHECK.md](./PHASE1_PRECHECK.md)、[ARCHITECTURE.md](./ARCHITECTURE.md)、[PHASE1_ADR.md](./PHASE1_ADR.md)（ADR-0013）
- 结论：**最低支持 macOS 14.0 保持不变；当前环境无法实机验证，列为发布门禁（MAC-01）**

---

## 1. 当前状态（如实标注）

| 项目 | 实测 | 说明 |
|---|---|---|
| 本机 macOS | 27.2（Build 26B123） | 远高于 14.0 |
| Xcode | 27.2（27B52） | 仅此一个版本 |
| macOS SDK | 27.2 | `xcodebuild -showsdks` 仅有 27.2 |
| 部署目标 | `MACOSX_DEPLOYMENT_TARGET = 14.0` | `App/project.yml` 显式声明 |
| Swift | 6.4.2，`SWIFT_STRICT_CONCURRENCY=complete` | — |
| macOS 14.x 运行环境 | **不存在** | 无旧 SDK、无虚拟机、无实机 |
| macOS 14 实机/虚拟机验证 | **未验证** | 不得以任何文档或静态检查声称已验证 |

---

## 2. 静态审计（本轮实际执行）

### 2.1 方法

1. 确认部署目标：`App/project.yml` 的 `options.deploymentTarget.macOS` 与 target 级 `deploymentTarget` 均为 `"14.0"`。
2. 依赖 Swift 编译器的可用性检查：在部署目标 14.0 下，使用高于 14.0 且未加 `@available`/`#available` 保护的符号会**编译失败**。本轮 `xcodebuild test` 与 `build_app.sh` 均成功，说明不存在无保护的高版本符号调用。
3. 枚举全部 `import` 与敏感 API：
   - `import AppKit / Combine / Darwin / Foundation / os / Security / SwiftUI`
   - 全仓库 `@available` / `#available`：**0 处**（说明代码没有按版本分支，也意味着未使用需要版本分支的 API）。
4. 逐项核对符号的最低系统版本（Apple 文档口径）。

### 2.2 结果

| 符号 / 能力 | 使用位置 | 最低 macOS | 与 14.0 兼容 |
|---|---|---|---|
| `Process` / `Pipe` / `FileHandle` | `SidecarSupervisor.swift`、`PipeReadBoxes.swift` | 10.0+ | 是 |
| `SecRandomCopyBytes` | `SidecarToken.swift` | 10.0+ | 是 |
| `URLSessionConfiguration.ephemeral` | `APIClient.swift` | 10.0+ | 是 |
| `Task` / `Task.sleep(for:)` / `AsyncStream` | `SidecarViewModel.swift`、`SidecarSupervisor.swift` | 10.15 / 13.0 | 是 |
| `@MainActor` / `Sendable` | 多处 | Swift 5.5+ | 是 |
| `os.Logger` | `Core/Log.swift` | 11.0 | 是 |
| `WindowGroup` / `.defaultSize` / `.windowResizability` | `PersonalIntelligenceHubApp.swift` | 11.0 / 13.0 / 13.0 | 是 |
| `Grid` | `StatusView.swift` | 13.0 | 是 |
| `NavigationSplitView` / `.navigationSplitViewColumnWidth` | `RootView.swift` | 13.0 | 是 |
| `TextField(axis:)` | `SourceEditorView.swift`、`CategoryEditorView.swift` | 13.0 | 是 |
| `onChange(of:) { old, new in }`（两参数版本） | `SourcesScreen.swift` | 14.0 | 是（部署目标即 14.0） |
| `Date.formatted(...)` | `StatusView.swift` | 12.0 | 是 |

未使用：`@Observable`/Observation、`ContentUnavailableView`、Swift Charts、SwiftData、`onGeometryChange`、`containerRelativeFrame`、`scrollTargetBehavior`、`meshGradient`、`glassEffect` 等更高版本能力。

### 2.3 静态审计的边界（必须明确）

静态审计只能证明：

- 不存在「部署目标 14.0 下不可用」的符号调用；
- 不存在需要版本分支的 API。

静态审计**不能**证明：

- macOS 14 上的真实布局、渲染、字体与窗口行为；
- 系统行为差异（进程管理、`getppid`、信号、App Nap、沙盒/隐私提示）；
- 旧系统上的链接与运行时异常；
- 用户实际操作路径（启动、编辑、删除、错误态）在 14 上的表现。

**因此：静态审计 ≠ 实机兼容性验证。**

---

## 3. macOS 14 验证方案（发布门禁）

### 3.1 候选途径

| 方案 | 可行性 | 成本 | 结论 |
|---|---|---|---|
| A. Apple Silicon 虚拟机（UTM / VMware Fusion / Parallels，macOS 14 客户机） | Apple Silicon 支持 macOS 虚拟化；需 14.x IPSW 或安装镜像 | 约 40–60 GB 磁盘 + 数小时 | **推荐**（不新增硬件） |
| B. 独立 Mac 实机（macOS 14） | 最真实 | 需设备 | 条件允许时优先 |
| C. CI 托管 macOS 14 runner（如 GitHub Actions `macos-14`） | 可跑构建 + 单元测试 | 需 CI 账号；无法验证 UI 交互 | 作为构建/单测补充，不能替代 UI 验证 |
| D. 不验证，发布时声明仅支持当前系统 | 零成本 | 违反产品目标 | **不采用**（用户 C4 明确保留 14） |

> 当前磁盘可用 8.6 GiB，**不具备**创建 macOS 14 虚拟机（约需 40–60 GB）的条件。因此方案 A 需先满足磁盘门槛（DISK-01），或改用方案 B/C。

### 3.2 验证清单（在 14.x 环境执行）

1. `bash Scripts/build_app.sh` → `BUILD SUCCEEDED`，`MACOSX_DEPLOYMENT_TARGET` 仍为 14.0。
2. `xcodebuild test` → 35 tests / 0 failures（或届时的最新用例数）。
3. App 启动 → Sidecar 拉起 → 握手 → `/health` 200 → 退出后无残留（对照 `API_CONTRACT.md` §4/§6/§9）。
4. 失败态：后端入口缺失/不可写数据目录 → 真实失败或 degraded，不伪装成功。
5. UI：窗口缩放、浅色/深色、空态/错误态/加载态、VoiceOver 基础可达性。
6. Phase 1 新增：信息源列表、新增/编辑、启停、删除确认、分类管理。
7. 记录：macOS 版本、机型/虚拟化平台、构建号、截图、命令输出。

### 3.3 门禁定义

| 项 | 规则 |
|---|---|
| 何时必须完成 | Phase 7 发布前；Phase 1–6 允许在 27.2 上开发，但不得声称已兼容 14 |
| 未完成时的发布限制 | 不得发布声明「支持 macOS 14+」；只能在说明中标注「仅在 macOS 27.2 验证」 |
| 记录位置 | 本节 + `PHASE1_PRECHECK.md` 未验证项 + 阶段验收报告 |
| 责任 | macos-developer 执行，qa-security 独立复核，architect 在验收中确认 |

---

## 4. 风险

| 编号 | 级别 | 风险 | 缓解 |
|---|---|---|---|
| MAC-01 | P2 | macOS 14 未实机验证 | 建立 14.x 虚拟/实机环境；发布门禁 |
| MAC-02 | P3 | 部署目标与 SDK 跨 13 个大版本，编译器可用性检查无法覆盖行为差异 | 14.x 上做完整交互验证 |
| MAC-03 | P2 | 虚拟机方案需 40–60 GB，当前磁盘不足 | 先解决 DISK-01；或使用外部设备/CI |

---

## 5. 本轮实际执行的审计命令

```bash
sw_vers
xcodebuild -version
xcrun --show-sdk-version
grep -n "deploymentTarget\|MACOSX_DEPLOYMENT_TARGET" App/project.yml
grep -rn "@available\|#available" App/PersonalIntelligenceHub App/PersonalIntelligenceHubTests
grep -rh "^import" App/PersonalIntelligenceHub | sort -u
grep -rnE "OSAllocatedUnfairLock|@Observable|ContentUnavailableView|onGeometryChange|containerRelativeFrame|scrollTargetBehavior|meshGradient|glassEffect|SwiftData|@Model|Chart\(" App/PersonalIntelligenceHub
xcodebuild test -project App/PersonalIntelligenceHub.xcodeproj -scheme PersonalIntelligenceHub \
  -configuration Debug -destination 'platform=macOS' -derivedDataPath build/DerivedData
```
