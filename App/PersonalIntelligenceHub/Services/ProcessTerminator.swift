import Darwin
import Foundation

/// 记录当前 Sidecar 进程，供 applicationWillTerminate 同步清理（阻塞式，最多约 4 秒）。
final class ProcessTerminator: @unchecked Sendable {
    private let lock = NSLock()
    private var process: Process?

    func install(_ process: Process?) {
        lock.lock()
        self.process = process
        lock.unlock()
    }

    var isRunning: Bool {
        lock.lock()
        defer { lock.unlock() }
        return process?.isRunning ?? false
    }

    /// SIGTERM → 等待 3 秒 → SIGKILL → 等待回收。仅用于 App 退出路径。
    func terminateSynchronously() {
        lock.lock()
        let current = process
        lock.unlock()

        guard let current, current.isRunning else { return }

        _ = Darwin.kill(current.processIdentifier, SIGTERM)

        let graceDeadline = Date().addingTimeInterval(PIHConstants.terminationGraceSeconds)
        while current.isRunning && Date() < graceDeadline {
            Thread.sleep(forTimeInterval: 0.05)
        }

        if current.isRunning {
            _ = Darwin.kill(current.processIdentifier, SIGKILL)
        }

        let killDeadline = Date().addingTimeInterval(2)
        while current.isRunning && Date() < killDeadline {
            Thread.sleep(forTimeInterval: 0.02)
        }
    }
}
