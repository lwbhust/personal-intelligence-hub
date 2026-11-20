import Foundation

struct SidecarLaunchConfig: Sendable {
    let pythonPath: String
    let entryPath: String
    let workingDirectory: URL
    let dataDirectory: String?
    /// 附加到 Sidecar 进程的环境变量（如 PYTHONPATH）。
    let extraEnvironment: [String: String]
}

struct SidecarSession: Sendable {
    let pid: Int32
    let port: Int
    let handshakeVersion: String
    let token: String
}

struct SidecarStartError: Error, Sendable {
    let reason: String
    let detail: String?
    let stderrTail: [String]

    var message: String {
        if let detail, !detail.isEmpty {
            return "\(reason)（\(detail)）"
        }
        return reason
    }
}

struct ProcessExitInfo: Sendable {
    let pid: Int32
    let exitCode: Int32
    let wasSignal: Bool

    var description: String {
        wasSignal ? "被信号 \(exitCode) 终止" : "退出码 \(exitCode)"
    }
}

enum BackendConfigurationError: Error, LocalizedError, Sendable {
    case missingInfoKey(String)
    case sidecarResourcesMissing
    case homebrewPythonMissing

    var errorDescription: String? {
        switch self {
        case .missingInfoKey(let key):
            return "Info.plist 缺少构建变量 \(key)，无法定位 Sidecar 入口"
        case .sidecarResourcesMissing:
            return "App Bundle 内找不到 Sidecar 运行资源（Resources/sidecar/main.py）。请确认 Release 构建已正确打包。"
        case .homebrewPythonMissing:
            return "Sidecar 运行需要 Homebrew Python 3.14+（/opt/homebrew/bin/python3），但未找到。请先安装 Homebrew 和 Python：brew install python@3.14"
        }
    }
}

enum BackendConfiguration {
    /// Sidecar 在 App Bundle Resources 内的子目录名。
    private static let bundledSidecarDir = "sidecar"

    /// Homebrew Python 路径（当前 macOS arm64 标准位置）。
    private static let homebrewPythonPath = "/opt/homebrew/bin/python3"

    static func load(bundle: Bundle = .main) throws -> SidecarLaunchConfig {
        // 策略 1：优先使用 App Bundle Resources 内打包好的 sidecar（Release 安装版）。
        if let resourcesURL = bundle.resourceURL {
            let sidecarDir = resourcesURL.appendingPathComponent(bundledSidecarDir, isDirectory: true)
            let mainPy = sidecarDir.appendingPathComponent("main.py")
            if FileManager.default.fileExists(atPath: mainPy.path) {
                return try makeBundledConfig(sidecarDir: sidecarDir)
            }
        }

        // 策略 2：Fallback 到 Info.plist 的开发路径（Debug 模式 / Xcode 运行时）。
        return try makeDevConfig(bundle: bundle)
    }

    // MARK: - Bundled (Release)

    private static func makeBundledConfig(sidecarDir: URL) throws -> SidecarLaunchConfig {
        let fm = FileManager.default

        guard fm.fileExists(atPath: homebrewPythonPath) else {
            throw BackendConfigurationError.homebrewPythonMissing
        }

        let entryPath = sidecarDir.appendingPathComponent("main.py").path
        let sitePackagesDir = sidecarDir.appendingPathComponent("site-packages").path

        var pythonPathValue = sitePackagesDir
        // 确保 Bundle 内 sidecar 根目录也在 PYTHONPATH 上（用于直接 import main.py 同级模块）
        pythonPathValue += ":" + sidecarDir.path

        let extraEnv = ["PYTHONPATH": pythonPathValue]

        return SidecarLaunchConfig(
            pythonPath: homebrewPythonPath,
            entryPath: entryPath,
            workingDirectory: sidecarDir,
            dataDirectory: nil,
            extraEnvironment: extraEnv
        )
    }

    // MARK: - Dev (Debug / Xcode)

    private static func makeDevConfig(bundle: Bundle) throws -> SidecarLaunchConfig {
        func value(for key: String) throws -> String {
            guard let raw = bundle.object(forInfoDictionaryKey: key) as? String else {
                throw BackendConfigurationError.missingInfoKey(key)
            }
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else {
                throw BackendConfigurationError.missingInfoKey(key)
            }
            return trimmed
        }

        // Info.plist 使用 $(SRCROOT)/../ 形式：入口路径标准化后错误信息里才不会出现 ".."。
        // 解释器路径必须保持 venv 内的符号链接原样，标准化会解析符号链接从而丢失 venv。
        let pythonPath = try value(for: "PIHDevBackendPython")
        let entryPath = URL(fileURLWithPath: try value(for: "PIHDevBackendEntry")).standardizedFileURL.path
        let entryURL = URL(fileURLWithPath: entryPath)
        // <repo>/Backend/main.py -> <repo>
        let workingDirectory = entryURL.deletingLastPathComponent().deletingLastPathComponent()

        return SidecarLaunchConfig(
            pythonPath: pythonPath,
            entryPath: entryPath,
            workingDirectory: workingDirectory,
            dataDirectory: nil,
            extraEnvironment: [:]
        )
    }
}
