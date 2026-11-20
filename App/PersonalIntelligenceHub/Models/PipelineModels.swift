import Foundation
import SwiftUI

/// Phase 7.2 自动化管道模型。所有字段来自 `/api/v1/pipeline/*` 真实响应；
/// 未返回的数值不补零、不推测。未知状态保持原始字符串由视图决定展示。

struct PipelineAutomationDTO: Decodable, Hashable, Sendable {
    let enabled: Bool
    let paused: Bool
    let aiEnabled: Bool
    let entityEnabled: Bool
    let eventEnabled: Bool
    let scoringEnabled: Bool
}

struct PipelineSettingsDTO: Decodable, Hashable, Sendable {
    let automationEnabled: Bool
    let paused: Bool
    let aiEnabled: Bool
    let entityEnabled: Bool
    let eventEnabled: Bool
    let scoringEnabled: Bool
    let batchSize: Int
    let maxAttempts: Int
    let aiIntervalSeconds: Int
    let updatedAt: String
}

/// 设置更新请求体。只编码显式提供的字段，避免误把 nil 当成 false 写回。
struct PipelineSettingsUpdate: Encodable, Sendable {
    var automationEnabled: Bool?
    var paused: Bool?
    var aiEnabled: Bool?
    var entityEnabled: Bool?
    var eventEnabled: Bool?
    var scoringEnabled: Bool?
    var batchSize: Int?
    var maxAttempts: Int?
    var aiIntervalSeconds: Int?

    enum CodingKeys: String, CodingKey {
        case automationEnabled = "automation_enabled"
        case paused
        case aiEnabled = "ai_enabled"
        case entityEnabled = "entity_enabled"
        case eventEnabled = "event_enabled"
        case scoringEnabled = "scoring_enabled"
        case batchSize = "batch_size"
        case maxAttempts = "max_attempts"
        case aiIntervalSeconds = "ai_interval_seconds"
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeIfPresent(automationEnabled, forKey: .automationEnabled)
        try container.encodeIfPresent(paused, forKey: .paused)
        try container.encodeIfPresent(aiEnabled, forKey: .aiEnabled)
        try container.encodeIfPresent(entityEnabled, forKey: .entityEnabled)
        try container.encodeIfPresent(eventEnabled, forKey: .eventEnabled)
        try container.encodeIfPresent(scoringEnabled, forKey: .scoringEnabled)
        try container.encodeIfPresent(batchSize, forKey: .batchSize)
        try container.encodeIfPresent(maxAttempts, forKey: .maxAttempts)
        try container.encodeIfPresent(aiIntervalSeconds, forKey: .aiIntervalSeconds)
    }
}

struct PipelineCountsDTO: Decodable, Hashable, Sendable {
    let total: Int
    let pending: Int
    let running: Int
    let retryWait: Int
    let succeeded: Int
    let failed: Int
    let skipped: Int
    let cancelled: Int
}

struct PipelineQueueDTO: Decodable, Hashable, Sendable {
    let waiting: Int
    let retryWait: Int
    let running: Int
}

struct PipelineActivityErrorDTO: Decodable, Hashable, Sendable {
    let errorCode: String?
    let errorMessage: String?
    let at: String?
}

struct PipelineActivityDTO: Decodable, Hashable, Sendable {
    let lastCompletedAt: String?
    let lastSucceededAt: String?
    let lastError: PipelineActivityErrorDTO?
}

struct PipelineTodayDTO: Decodable, Hashable, Sendable {
    let succeeded: Int
    let failed: Int
    let skipped: Int
}

struct PipelineRuntimeDTO: Decodable, Hashable, Sendable {
    let workerAlive: Bool
    let lastSweepAt: String?
    let lastSweepDurationMs: Int?
    let lastSweepError: String?
    let lastRecoveredTasks: Int
}

struct PipelineOverviewDTO: Decodable, Hashable, Sendable {
    let automation: PipelineAutomationDTO
    let settings: PipelineSettingsDTO
    let counts: PipelineCountsDTO
    let queue: PipelineQueueDTO
    let stageCounts: [String: Int]
    let activity: PipelineActivityDTO
    let today: PipelineTodayDTO
    let runtime: PipelineRuntimeDTO
    let taxonomyVersion: String
    let scoreVersion: String
}

struct PipelineTaskDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let taskType: String
    let articleId: String?
    let eventId: String?
    let stage: String
    let status: String
    let priority: Int
    let attempts: Int
    let maxAttempts: Int
    let nextRetryAt: String?
    let errorCode: String?
    let errorMessage: String?
    let inputSummary: String?
    let outputSummary: String?
    let triggerType: String
    let batchId: String?
    let createdAt: String
    let startedAt: String?
    let completedAt: String?
    let updatedAt: String
    let articleTitle: String?
    let sourceName: String?
}

struct PipelineTaskPageDTO: Decodable, Sendable {
    let items: [PipelineTaskDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

/// 日志 detail 是自由结构；这里只做安全展示，不参与业务判断。
enum PipelineJSONValue: Decodable, Hashable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else {
            self = .null
        }
    }

    var display: String {
        switch self {
        case .string(let value): return value
        case .number(let value):
            return value == value.rounded() ? String(Int(value)) : String(value)
        case .bool(let value): return value ? "true" : "false"
        case .null: return "—"
        }
    }
}

struct PipelineLogDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let taskId: String
    let stage: String?
    let level: String
    let message: String
    let detail: [String: PipelineJSONValue]
    let createdAt: String
}

struct PipelineLogPageDTO: Decodable, Sendable {
    let items: [PipelineLogDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

struct PipelineBackfillPreviewDTO: Decodable, Hashable, Sendable {
    let pendingArticles: Int
    let aiNeeded: Int
    let eventNeeded: Int
    let estimatedAiSeconds: Int
    let estimatedTotalMinutes: Double
    let note: String
}

struct PipelineRunDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let triggerType: String
    let status: String
    let requestedTasks: Int
    let createdTasks: Int
    let processedTasks: Int
    let succeededTasks: Int
    let failedTasks: Int
    let skippedTasks: Int
    let cancelRequested: Bool
    let errorMessage: String?
    let startedAt: String?
    let finishedAt: String?
    let createdAt: String
    let updatedAt: String
}

struct PipelineRunPageDTO: Decodable, Sendable {
    let items: [PipelineRunDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

struct PipelineTaskDetailDTO: Decodable, Sendable {
    let task: PipelineTaskDTO
}

struct PipelineRunDetailDTO: Decodable, Sendable {
    let run: PipelineRunDTO
}

struct PipelineBackfillResultDTO: Decodable, Sendable {
    let run: PipelineRunDTO
    let createdTasks: Int
}

enum PipelineStage {
    static let labels: [String: String] = [
        "quality_check": "内容检查",
        "ai_analysis": "AI 分析",
        "entity_sync": "实体同步",
        "event_match": "事件匹配",
        "event_score": "事件评分",
        "refresh": "数据刷新",
        "done": "已完成",
    ]

    static let order = [
        "quality_check", "ai_analysis", "entity_sync",
        "event_match", "event_score", "refresh", "done",
    ]

    static func label(_ value: String) -> String {
        labels[value] ?? value
    }

    static func index(_ value: String) -> Int {
        order.firstIndex(of: value) ?? 0
    }
}

enum PipelineTaskStatus {
    static func label(_ value: String) -> String {
        switch value {
        case "pending": return "待处理"
        case "ready": return "待执行"
        case "running": return "运行中"
        case "retry_wait": return "等待重试"
        case "succeeded": return "成功"
        case "failed": return "失败"
        case "skipped": return "已跳过"
        case "cancelled": return "已取消"
        default: return value
        }
    }

    static func tint(_ value: String) -> Color {
        switch value {
        case "running": return .blue
        case "succeeded": return .green
        case "failed": return .red
        case "retry_wait": return .orange
        case "cancelled": return .secondary
        case "skipped": return .secondary
        default: return .secondary
        }
    }
}

enum PipelineTrigger {
    static func label(_ value: String) -> String {
        switch value {
        case "auto": return "自动"
        case "manual": return "人工"
        case "backfill": return "历史回填"
        default: return value
        }
    }
}

enum PipelineRunStatus {
    static func label(_ value: String) -> String {
        switch value {
        case "pending": return "未开始"
        case "running": return "进行中"
        case "paused": return "已暂停"
        case "succeeded": return "全部成功"
        case "partially_succeeded": return "部分成功"
        case "failed": return "失败"
        case "cancelled": return "已取消"
        default: return value
        }
    }

    static func tint(_ value: String) -> Color {
        switch value {
        case "running": return .blue
        case "succeeded": return .green
        case "partially_succeeded": return .orange
        case "failed": return .red
        case "cancelled": return .secondary
        default: return .secondary
        }
    }
}
