import os

/// 统一日志入口。禁止记录 Token、Authorization 头与环境变量转储。
enum Log {
    private static let subsystem = "com.pih.PersonalIntelligenceHub"

    static let app = Logger(subsystem: subsystem, category: "app")
    static let sidecar = Logger(subsystem: subsystem, category: "sidecar")
    static let health = Logger(subsystem: subsystem, category: "health")
}
