import Darwin
import Foundation

/// Sidecar 进程与握手/停止的唯一管理者（actor：所有进程操作离开主线程）。
actor SidecarSupervisor {
    nonisolated let terminator = ProcessTerminator()
    nonisolated let events: AsyncStream<ProcessExitInfo>

    private let eventContinuation: AsyncStream<ProcessExitInfo>.Continuation

    private var process: Process?
    private var stdoutPipe: Pipe?
    private var stderrPipe: Pipe?
    private var stderrTailBox: StderrTailBox?

    init() {
        let (stream, continuation) = AsyncStream.makeStream(of: ProcessExitInfo.self)
        self.events = stream
        self.eventContinuation = continuation
    }

    func isRunning() -> Bool {
        process?.isRunning ?? false
    }

    func stderrTail() -> [String] {
        stderrTailBox?.snapshot() ?? []
    }

    // MARK: - Start

    func start(config: SidecarLaunchConfig) async throws -> SidecarSession {
        if let process, process.isRunning {
            throw SidecarStartError(
                reason: "Sidecar 已在运行",
                detail: "PID \(process.processIdentifier)",
                stderrTail: []
            )
        }
        cleanupProcess()
        try validatePaths(config)

        let token: String
        do {
            token = try SidecarToken.generate()
        } catch {
            throw SidecarStartError(
                reason: "无法生成 Sidecar 访问令牌",
                detail: String(describing: error),
                stderrTail: []
            )
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: config.pythonPath)
        process.arguments = [config.entryPath]
        process.currentDirectoryURL = config.workingDirectory

        var environment = ProcessInfo.processInfo.environment
        environment[PIHConstants.tokenEnvironmentKey] = token
        environment[PIHConstants.portEnvironmentKey] = "0"
        environment[PIHConstants.unbufferedEnvironmentKey] = "1"
        environment[PIHConstants.noBytecodeEnvironmentKey] = "1"
        if let dataDirectory = config.dataDirectory, !dataDirectory.isEmpty {
            environment[PIHConstants.dataDirectoryEnvironmentKey] = dataDirectory
        }
        // Release 打包模式需要额外注入 PYTHONPATH（以及未来可能的其他变量）。
        for (key, value) in config.extraEnvironment {
            environment[key] = value
        }
        process.environment = environment

        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe
        process.standardInput = FileHandle.nullDevice

        let lineBox = HandshakeLineBox(maxBytes: PIHConstants.maxHandshakeLineBytes)
        let stderrBox = StderrTailBox(
            secret: token,
            maxLines: PIHConstants.maxStderrLines,
            maxCharacters: PIHConstants.maxStderrLineCharacters
        )

        let stdoutHandle = stdoutPipe.fileHandleForReading
        stdoutHandle.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
                lineBox.markEOF()
            } else {
                lineBox.append(data)
            }
        }

        let stderrHandle = stderrPipe.fileHandleForReading
        stderrHandle.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
            } else {
                stderrBox.append(data)
            }
        }

        do {
            try process.run()
        } catch {
            stdoutHandle.readabilityHandler = nil
            stderrHandle.readabilityHandler = nil
            throw SidecarStartError(
                reason: "无法启动 Sidecar 进程",
                detail: "\(Self.describeRunError(error))；解释器 \(config.pythonPath)",
                stderrTail: stderrBox.snapshot()
            )
        }

        self.process = process
        self.stdoutPipe = stdoutPipe
        self.stderrPipe = stderrPipe
        self.stderrTailBox = stderrBox
        terminator.install(process)

        process.terminationHandler = { [weak self] terminated in
            let info = ProcessExitInfo(
                pid: terminated.processIdentifier,
                exitCode: terminated.terminationStatus,
                wasSignal: terminated.terminationReason == .uncaughtSignal
            )
            Task { await self?.recordExit(info) }
        }

        Log.sidecar.info("Sidecar spawned pid=\(process.processIdentifier)")

        do {
            let handshake = try await awaitHandshake(
                lineBox: lineBox,
                stderrBox: stderrBox,
                process: process
            )
            return SidecarSession(
                pid: process.processIdentifier,
                port: handshake.port,
                handshakeVersion: handshake.version,
                token: token
            )
        } catch {
            await terminate(process)
            // 给 stderr 读取器一点时间排空管道尾部（失败原因需要真实展示）。
            try? await Task.sleep(for: .milliseconds(250))
            let tail = stderrBox.snapshot()
            cleanupProcess()
            if let startError = error as? SidecarStartError {
                Log.sidecar.error("Sidecar start failed: \(startError.reason, privacy: .public)")
                throw SidecarStartError(
                    reason: startError.reason,
                    detail: startError.detail,
                    stderrTail: tail
                )
            }
            throw SidecarStartError(
                reason: "Sidecar 握手失败",
                detail: String(describing: error),
                stderrTail: tail
            )
        }
    }

    // MARK: - Stop

    func stop() async {
        guard let process else {
            cleanupProcess()
            return
        }
        await terminate(process)
        cleanupProcess()
    }

    // MARK: - Handshake

    private func awaitHandshake(
        lineBox: HandshakeLineBox,
        stderrBox: StderrTailBox,
        process: Process
    ) async throws -> SidecarHandshake {
        let deadline = ContinuousClock.now + PIHConstants.handshakeTimeout

        while true {
            let snapshot = lineBox.snapshot()

            if let line = snapshot.line {
                let handshake: SidecarHandshake
                do {
                    handshake = try HandshakeParser.parse(line: line)
                } catch {
                    let reason = (error as? HandshakeError)?.userMessage ?? "握手解析失败：\(error)"
                    throw SidecarStartError(
                        reason: reason,
                        detail: "握手原始行长度 \(line.count) 字节",
                        stderrTail: stderrBox.snapshot()
                    )
                }
                guard handshake.pid == Int(process.processIdentifier) else {
                    throw SidecarStartError(
                        reason: "握手 PID 与子进程 PID 不一致（疑似端口串话）",
                        detail: "握手 pid=\(handshake.pid)，子进程 pid=\(process.processIdentifier)",
                        stderrTail: stderrBox.snapshot()
                    )
                }
                return handshake
            }

            if snapshot.overflowed {
                throw SidecarStartError(
                    reason: "握手协议错误：stdout 首行超过 4096 字节仍未换行",
                    detail: nil,
                    stderrTail: stderrBox.snapshot()
                )
            }

            if snapshot.reachedEOF {
                try? await Task.sleep(for: .milliseconds(80))
                throw exitedBeforeHandshake(process: process, stderrBox: stderrBox, partial: snapshot.hasPartialLine)
            }

            if !process.isRunning {
                try? await Task.sleep(for: .milliseconds(120))
                let late = lineBox.snapshot()
                if let line = late.line,
                   let handshake = try? HandshakeParser.parse(line: line),
                   handshake.pid == Int(process.processIdentifier) {
                    return handshake
                }
                throw exitedBeforeHandshake(process: process, stderrBox: stderrBox, partial: late.hasPartialLine)
            }

            if ContinuousClock.now >= deadline {
                throw SidecarStartError(
                    reason: "启动超时：10 秒内未收到 Sidecar 握手",
                    detail: "即将按 SIGTERM → 3 秒 → SIGKILL 终止子进程",
                    stderrTail: stderrBox.snapshot()
                )
            }

            try? await Task.sleep(for: .milliseconds(25))
        }
    }

    private func exitedBeforeHandshake(
        process: Process,
        stderrBox: StderrTailBox,
        partial: Bool
    ) -> SidecarStartError {
        var detail = Self.describeExit(process)
        if partial {
            detail += "；stdout 收到不完整握手（缺少换行）"
        }
        return SidecarStartError(
            reason: "Sidecar 在输出握手前退出",
            detail: detail,
            stderrTail: stderrBox.snapshot()
        )
    }

    // MARK: - Process helpers

    private func recordExit(_ info: ProcessExitInfo) {
        guard let process, process.processIdentifier == info.pid else { return }
        eventContinuation.yield(info)
    }

    private func terminate(_ process: Process) async {
        guard process.isRunning else { return }

        _ = Darwin.kill(process.processIdentifier, SIGTERM)

        let graceDeadline = ContinuousClock.now + PIHConstants.terminationGracePeriod
        while process.isRunning && ContinuousClock.now < graceDeadline {
            try? await Task.sleep(for: .milliseconds(50))
        }

        if process.isRunning {
            _ = Darwin.kill(process.processIdentifier, SIGKILL)
        }

        let killDeadline = ContinuousClock.now + .seconds(2)
        while process.isRunning && ContinuousClock.now < killDeadline {
            try? await Task.sleep(for: .milliseconds(25))
        }
    }

    private func cleanupProcess() {
        stdoutPipe?.fileHandleForReading.readabilityHandler = nil
        stderrPipe?.fileHandleForReading.readabilityHandler = nil
        stdoutPipe = nil
        stderrPipe = nil
        process = nil
        stderrTailBox = nil
        terminator.install(nil)
    }

    private func validatePaths(_ config: SidecarLaunchConfig) throws {
        let fileManager = FileManager.default
        var isDirectory: ObjCBool = false

        guard fileManager.fileExists(atPath: config.pythonPath, isDirectory: &isDirectory),
              !isDirectory.boolValue else {
            throw SidecarStartError(
                reason: "找不到 Python 解释器",
                detail: config.pythonPath,
                stderrTail: []
            )
        }
        guard fileManager.isExecutableFile(atPath: config.pythonPath) else {
            throw SidecarStartError(
                reason: "Python 解释器不可执行",
                detail: config.pythonPath,
                stderrTail: []
            )
        }
        guard fileManager.fileExists(atPath: config.entryPath) else {
            throw SidecarStartError(
                reason: "找不到后端入口 Backend/main.py",
                detail: config.entryPath,
                stderrTail: []
            )
        }
    }

    private static func describeExit(_ process: Process) -> String {
        if process.terminationReason == .uncaughtSignal {
            return "进程被信号 \(process.terminationStatus) 终止"
        }
        return "进程退出码 \(process.terminationStatus)"
    }

    private static func describeRunError(_ error: Error) -> String {
        let nsError = error as NSError
        return "\(nsError.localizedDescription)（\(nsError.domain) \(nsError.code)）"
    }
}
