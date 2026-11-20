import Combine
import Foundation

/// UI 状态机与 Sidecar 生命周期编排。所有 UI 状态仅在主线程写入。
@MainActor
final class SidecarViewModel: ObservableObject {
    @Published private(set) var state: SidecarState = .idle
    @Published private(set) var processID: Int32?
    @Published private(set) var processRunning = false
    @Published private(set) var port: Int?
    @Published private(set) var handshakeVersion: String?
    @Published private(set) var backendVersion: String?
    @Published private(set) var serverTimestamp: String?
    @Published private(set) var databaseStatus: String?
    @Published private(set) var databaseCode: String?
    @Published private(set) var schemaVersion: Int?
    @Published private(set) var pathKind: String?
    @Published private(set) var buildCommit: String?
    @Published private(set) var buildTime: String?
    @Published private(set) var uptimeSeconds: Double?
    @Published private(set) var lastCheckAt: Date?
    @Published private(set) var lastSuccessAt: Date?
    @Published private(set) var consecutiveFailures = 0
    @Published private(set) var healthWarning: String?
    @Published private(set) var errorMessage: String?
    @Published private(set) var requestID: String?
    @Published private(set) var stderrTail: [String] = []
    @Published private(set) var isChecking = false
    @Published private(set) var statusDetail: String?

    private let supervisor = SidecarSupervisor()
    private var apiClient: APIClient?
    private var pollTask: Task<Void, Never>?
    private var startTask: Task<Void, Never>?
    private var exitObserver: Task<Void, Never>?
    private var generation = UUID()
    private var autoStarted = false

    init() {
        exitObserver = Task { [weak self] in
            guard let self else { return }
            for await info in self.supervisor.events {
                await self.handleProcessExit(info)
            }
        }
    }

    // MARK: - Button availability

    var canStart: Bool {
        state == .idle || state == .offline || state == .failed
    }

    var canStop: Bool {
        processRunning && state != .stopping
    }

    var canCheck: Bool {
        apiClient != nil && !isChecking && state != .failed && state != .stopping && state != .idle
    }

    /// Phase 1 业务界面使用的客户端；仅在握手成功后存在。
    var apiClientForFeatures: APIClient? {
        apiClient
    }

    /// Sidecar 可用（含数据库降级）时才允许调用业务 API。
    var isDataReady: Bool {
        state == .ready || state == .degraded
    }

    // MARK: - Commands

    /// XCTest 以 App 作为 TEST_HOST 时会真正启动应用主流程。若此时自动拉起
    /// 开发版 Sidecar，它会以默认数据目录运行并对用户真实数据库执行迁移。
    /// 测试宿主必须完全不触碰生产数据库，因此这里直接跳过自动启动。
    static var isRunningUnderXCTest: Bool {
        ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
            || NSClassFromString("XCTestCase") != nil
    }

    func autoStartIfNeeded() {
        guard !autoStarted else { return }
        autoStarted = true
        if Self.isRunningUnderXCTest {
            state = .idle
            statusDetail = "检测到 XCTest 测试宿主，已跳过 Sidecar 自动启动（不触碰生产数据库）"
            Log.app.info("XCTest host detected; sidecar auto-start skipped")
            return
        }
        start()
    }

    func start() {
        guard state != .starting, state != .stopping else { return }
        let generation = UUID()
        self.generation = generation
        startTask = Task { await self.startSession(generation: generation) }
    }

    func stop() {
        guard state != .stopping else { return }
        generation = UUID()
        Task { await self.stopSession() }
    }

    func checkNow() {
        guard canCheck else { return }
        Task { await self.performHealthCheck() }
    }

    /// App 退出路径：同步终止子进程，避免僵尸/孤儿进程。
    func shutdownSynchronously() {
        generation = UUID()
        pollTask?.cancel()
        pollTask = nil
        startTask?.cancel()
        startTask = nil
        exitObserver?.cancel()
        exitObserver = nil
        apiClient = nil
        supervisor.terminator.terminateSynchronously()
    }

    // MARK: - Start / stop

    private func startSession(generation: UUID) async {
        stopPolling()
        processID = nil
        processRunning = false
        apiClient = nil
        state = .starting
        statusDetail = "正在准备启动 Sidecar…"

        if await supervisor.isRunning() {
            statusDetail = "正在停止旧的 Sidecar 进程…"
            await supervisor.stop()
        }
        guard generation == self.generation else { return }

        resetSessionState()
        state = .starting
        statusDetail = "正在启动 Sidecar…"

        do {
            let config = try BackendConfiguration.load()
            statusDetail = "已拉起进程，等待握手（10 秒超时）…"

            let session = try await supervisor.start(config: config)
            guard generation == self.generation else {
                await supervisor.stop()
                return
            }

            processID = session.pid
            processRunning = true
            port = session.port
            handshakeVersion = session.handshakeVersion
            apiClient = APIClient(
                port: session.port,
                token: session.token,
                expectedVersion: session.handshakeVersion
            )
            statusDetail = "握手成功：PID \(session.pid)，端口 \(session.port)。正在执行首次健康检查…"

            ensurePolling()
            await performHealthCheck()

            if generation == self.generation, state == .starting {
                statusDetail = "握手成功，等待首次健康检查（已安排每 5 秒重试）"
            } else if generation == self.generation {
                statusDetail = nil
            }
        } catch let error as SidecarStartError {
            guard generation == self.generation else { return }
            stopPolling()
            apiClient = nil
            processRunning = false
            processID = nil
            port = nil
            handshakeVersion = nil
            state = .failed
            errorMessage = error.message
            stderrTail = error.stderrTail
            statusDetail = "Sidecar 启动失败"
        } catch let error as BackendConfigurationError {
            guard generation == self.generation else { return }
            stopPolling()
            apiClient = nil
            processRunning = false
            state = .failed
            errorMessage = error.errorDescription ?? "后端配置无效"
            statusDetail = "Sidecar 启动失败"
        } catch {
            guard generation == self.generation else { return }
            stopPolling()
            apiClient = nil
            processRunning = false
            state = .failed
            errorMessage = "启动失败：\(error.localizedDescription)"
            statusDetail = nil
        }
    }

    private func stopSession() async {
        stopPolling()
        state = .stopping
        statusDetail = "正在停止 Sidecar（SIGTERM → 3 秒 → SIGKILL）…"
        apiClient = nil

        await supervisor.stop()

        processRunning = false
        processID = nil
        port = nil
        handshakeVersion = nil
        backendVersion = nil
        serverTimestamp = nil
        databaseStatus = nil
        databaseCode = nil
        schemaVersion = nil
        pathKind = nil
        uptimeSeconds = nil
        healthWarning = nil
        errorMessage = nil
        requestID = nil
        stderrTail = []
        consecutiveFailures = 0
        isChecking = false
        state = .idle
        statusDetail = "Sidecar 已停止"
    }

    private func resetSessionState() {
        processID = nil
        processRunning = false
        port = nil
        apiClient = nil
        handshakeVersion = nil
        backendVersion = nil
        serverTimestamp = nil
        databaseStatus = nil
        databaseCode = nil
        schemaVersion = nil
        pathKind = nil
        uptimeSeconds = nil
        lastCheckAt = nil
        lastSuccessAt = nil
        consecutiveFailures = 0
        healthWarning = nil
        errorMessage = nil
        requestID = nil
        stderrTail = []
        isChecking = false
        statusDetail = nil
    }

    // MARK: - Health

    private func performHealthCheck() async {
        guard let client = apiClient else { return }
        guard state != .failed, state != .stopping, state != .idle else { return }
        guard !isChecking else { return }

        isChecking = true
        lastCheckAt = Date()
        defer { isChecking = false }

        do {
            let outcome = try await client.fetchHealth()
            requestID = outcome.requestID
            backendVersion = outcome.health.version
            serverTimestamp = outcome.health.timestamp
            uptimeSeconds = outcome.health.uptimeSeconds
            databaseStatus = outcome.health.database.status
            databaseCode = outcome.health.database.code
            schemaVersion = outcome.health.database.schemaVersion
            pathKind = outcome.health.database.pathKind
            buildCommit = outcome.health.build?.gitCommit
            buildTime = outcome.health.build?.buildTime
            consecutiveFailures = 0
            lastSuccessAt = Date()
            errorMessage = nil

            if outcome.health.status == "degraded" {
                state = .degraded
                let code = outcome.health.database.code.map { "（\($0)）" } ?? ""
                healthWarning = "后端报告数据库降级\(code)；schema_version=\(schemaVersion.map(String.init) ?? "未知")"
                statusDetail = nil
            } else {
                state = .ready
                healthWarning = nil
                statusDetail = nil
            }

            ensurePolling()
            Log.health.info("health ok status=\(outcome.health.status, privacy: .public)")
        } catch let error as HealthCheckError {
            await handleHealthFailure(error)
        } catch {
            await handleHealthFailure(.transport(reason: APIClient.describe(error)))
        }
    }

    private func handleHealthFailure(_ error: HealthCheckError) async {
        switch error {
        case .unauthorized(let message, let rid):
            requestID = rid
            consecutiveFailures += 1
            stopPolling()
            apiClient = nil
            state = .failed
            errorMessage = "认证失败（HTTP 401）：\(message ?? "未授权")。已停止轮询，不会用同一 Token 重试。"
            statusDetail = nil

        case .contractViolation(let reason, let rid):
            requestID = rid
            consecutiveFailures += 1
            stopPolling()
            state = .failed
            errorMessage = "契约违例：\(reason)"
            statusDetail = nil

        case .transport(let reason):
            consecutiveFailures += 1
            let running = await supervisor.isRunning()
            if !running {
                stopPolling()
                apiClient = nil
                processRunning = false
                state = .failed
                errorMessage = "Sidecar 进程已退出，健康检查无法连接：\(reason)"
                statusDetail = nil
            } else if consecutiveFailures >= PIHConstants.offlineFailureThreshold {
                stopPolling()
                state = .offline
                errorMessage = "连续 \(consecutiveFailures) 次健康检查失败：\(reason)"
                statusDetail = "Sidecar 可能已失去响应；可点击“启动”真实重启。"
            } else {
                healthWarning = "健康检查失败（重试中，第 \(consecutiveFailures) 次）：\(reason)"
            }
        }

        stderrTail = await supervisor.stderrTail()
    }

    private func ensurePolling() {
        guard pollTask == nil else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: PIHConstants.pollInterval)
                guard !Task.isCancelled else { break }
                guard let self else { break }
                await self.performHealthCheck()
            }
        }
    }

    private func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    // MARK: - Process exit

    private func handleProcessExit(_ info: ProcessExitInfo) async {
        guard processID == info.pid, state != .stopping, state != .idle else { return }

        stopPolling()
        apiClient = nil
        processRunning = false
        isChecking = false
        state = .failed
        errorMessage = "Sidecar 进程已退出（\(info.description)）"
        statusDetail = nil

        stderrTail = await supervisor.stderrTail()
        Log.sidecar.error("Sidecar exited pid=\(info.pid) code=\(info.exitCode) signal=\(info.wasSignal)")
    }
}
