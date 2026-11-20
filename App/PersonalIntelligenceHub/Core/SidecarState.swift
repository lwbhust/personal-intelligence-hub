import Foundation
import SwiftUI

/// Sidecar 连接状态机（真实驱动，禁止写死）。
enum SidecarState: String, Sendable, Equatable {
    case idle
    case starting
    case ready
    case degraded
    case offline
    case failed
    case stopping

    var title: String {
        switch self {
        case .idle: return "未启动"
        case .starting: return "启动中"
        case .ready: return "运行正常"
        case .degraded: return "降级运行"
        case .offline: return "离线"
        case .failed: return "启动失败"
        case .stopping: return "正在停止"
        }
    }

    var tint: Color {
        switch self {
        case .idle: return .secondary
        case .starting: return .blue
        case .ready: return .green
        case .degraded: return .orange
        case .offline: return .red
        case .failed: return .red
        case .stopping: return .gray
        }
    }

    var summary: String {
        switch self {
        case .idle:
            return "尚未启动 Sidecar。点击“启动”会真实拉起本地后端进程。"
        case .starting:
            return "已拉起子进程，等待 stdout 握手（10 秒超时）与首次 /health 检查。"
        case .ready:
            return "握手成功，且 /health 返回 status=ok。"
        case .degraded:
            return "服务可用，但后端报告数据库异常（/health status=degraded）。"
        case .offline:
            return "连续 3 次健康检查失败，自动轮询已停止，需要真实重试。"
        case .failed:
            return "启动失败或契约违例，请查看下方错误详情。"
        case .stopping:
            return "正在停止 Sidecar（SIGTERM → 3 秒 → SIGKILL）。"
        }
    }
}
