import Foundation

/// 契约常量（Phase 0–2）。字段名、超时与协议值均以 Docs/API_CONTRACT.md、
/// Docs/PHASE2_CONTRACT.md 为准。
enum PIHConstants {
    static let serviceName = "pih-backend"
    static let supportedBackendMajor = 0

    /// 当前 Sidecar 契约版本（与 `Backend/core/version.py`、App 版本统一）。
    /// 握手兼容性仍按 SemVer MAJOR 判断；该常量用于界面契约展示与单测断言。
    static let expectedServiceVersion = "0.14.0"

    static let handshakePrefix = "PIH_SIDECAR_READY"
    static let maxHandshakeLineBytes = 4096
    static let handshakeTimeout: Duration = .seconds(10)

    static let healthTimeout: TimeInterval = 2
    static let apiTimeout: TimeInterval = 8
    static let pollInterval: Duration = .seconds(5)
    static let offlineFailureThreshold = 3

    static let terminationGracePeriod: Duration = .seconds(3)
    static let terminationGraceSeconds: TimeInterval = 3

    static let tokenEnvironmentKey = "PIH_SIDECAR_TOKEN"
    static let portEnvironmentKey = "PIH_PORT"
    static let unbufferedEnvironmentKey = "PYTHONUNBUFFERED"
    /// Release 包内的 Python 不得写 `__pycache__`，否则运行一次就会破坏 App Bundle
    /// 的密封资源签名（Phase 7.2.1 实测：codesign --verify 报 sealed resource 缺失）。
    static let noBytecodeEnvironmentKey = "PYTHONDONTWRITEBYTECODE"
    static let dataDirectoryEnvironmentKey = "PIH_DATA_DIR"

    static let maxStderrLines = 40
    static let maxStderrLineCharacters = 800
}
