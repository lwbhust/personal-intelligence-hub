import Foundation

/// 采集任务条目。`items` 中是真实处理结果；不合成、不补零。
struct CollectionJobItemDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let jobId: String
    let sourceId: String
    let sourceName: String?
    let status: String
    let httpStatus: Int?
    let discoveredCount: Int
    let insertedCount: Int
    let updatedCount: Int
    let duplicateCount: Int
    let errorCount: Int
    let errorCode: String?
    let errorMessage: String?
    let startedAt: String?
    let finishedAt: String?
    let durationMs: Int?
}

/// 采集任务。列表响应中 `items` 恒为 `[]`，详情才包含明细；
/// 这里对 `items` 缺失/为 null 做容错，未知状态值保持 String。
struct CollectionJobDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let triggerType: String
    let scope: String
    let status: String
    let requestedSourceCount: Int
    let processedSourceCount: Int
    let succeededSourceCount: Int
    let failedSourceCount: Int
    let discoveredCount: Int
    let insertedCount: Int
    let updatedCount: Int
    let duplicateCount: Int
    let errorCount: Int
    let errorMessage: String?
    let cancelRequested: Bool
    let startedAt: String?
    let finishedAt: String?
    let durationMs: Int?
    let createdAt: String
    let updatedAt: String
    let items: [CollectionJobItemDTO]

    private enum CodingKeys: String, CodingKey {
        case id
        case triggerType
        case scope
        case status
        case requestedSourceCount
        case processedSourceCount
        case succeededSourceCount
        case failedSourceCount
        case discoveredCount
        case insertedCount
        case updatedCount
        case duplicateCount
        case errorCount
        case errorMessage
        case cancelRequested
        case startedAt
        case finishedAt
        case durationMs
        case createdAt
        case updatedAt
        case items
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        triggerType = try container.decode(String.self, forKey: .triggerType)
        scope = try container.decode(String.self, forKey: .scope)
        status = try container.decode(String.self, forKey: .status)
        requestedSourceCount = try container.decode(Int.self, forKey: .requestedSourceCount)
        processedSourceCount = try container.decode(Int.self, forKey: .processedSourceCount)
        succeededSourceCount = try container.decode(Int.self, forKey: .succeededSourceCount)
        failedSourceCount = try container.decode(Int.self, forKey: .failedSourceCount)
        discoveredCount = try container.decode(Int.self, forKey: .discoveredCount)
        insertedCount = try container.decode(Int.self, forKey: .insertedCount)
        updatedCount = try container.decode(Int.self, forKey: .updatedCount)
        duplicateCount = try container.decode(Int.self, forKey: .duplicateCount)
        errorCount = try container.decode(Int.self, forKey: .errorCount)
        errorMessage = try container.decodeIfPresent(String.self, forKey: .errorMessage)
        cancelRequested = try container.decode(Bool.self, forKey: .cancelRequested)
        startedAt = try container.decodeIfPresent(String.self, forKey: .startedAt)
        finishedAt = try container.decodeIfPresent(String.self, forKey: .finishedAt)
        durationMs = try container.decodeIfPresent(Int.self, forKey: .durationMs)
        createdAt = try container.decode(String.self, forKey: .createdAt)
        updatedAt = try container.decode(String.self, forKey: .updatedAt)
        items = try container.decodeIfPresent([CollectionJobItemDTO].self, forKey: .items) ?? []
    }
}

struct CollectionJobPage: Decodable, Sendable {
    let items: [CollectionJobDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

/// `POST /api/v1/sources/{id}/collect` 的 202 响应；`item` 可能为 null。
struct CollectResponseDTO: Decodable, Sendable {
    let job: CollectionJobDTO
    let item: CollectionJobItemDTO?
}

/// `POST /api/v1/collection-jobs` 请求体：`source_ids=null` 表示全部启用来源。
enum CollectionJobRequest {
    static func allEnabledSources() throws -> Data {
        try JSONSerialization.data(
            withJSONObject: [
                "trigger_type": "manual",
                "source_ids": NSNull(),
            ]
        )
    }
}

/// 任务状态展示映射。未知值直接显示服务端原文。
enum CollectionJobStatus: String, CaseIterable, Identifiable, Sendable {
    case pending
    case running
    case succeeded
    case partiallySucceeded = "partially_succeeded"
    case failed
    case cancelled

    var id: String { rawValue }

    var label: String {
        switch self {
        case .pending: return "等待中"
        case .running: return "采集中"
        case .succeeded: return "成功"
        case .partiallySucceeded: return "部分成功"
        case .failed: return "失败"
        case .cancelled: return "已取消"
        }
    }

    static func resolve(_ raw: String) -> CollectionJobStatus? {
        CollectionJobStatus(rawValue: raw)
    }

    static func label(for raw: String) -> String {
        resolve(raw)?.label ?? raw
    }

    var isActive: Bool {
        self == .pending || self == .running
    }

    var canCancel: Bool {
        isActive
    }

    var canRetry: Bool {
        self == .failed || self == .partiallySucceeded || self == .cancelled
    }
}

/// 任务条目状态（契约含 `skipped`，与任务状态集合不同）。
enum CollectionJobItemStatus: String, CaseIterable, Sendable {
    case pending
    case running
    case succeeded
    case failed
    case skipped
    case cancelled

    var label: String {
        switch self {
        case .pending: return "等待中"
        case .running: return "采集中"
        case .succeeded: return "成功"
        case .failed: return "失败"
        case .skipped: return "已跳过"
        case .cancelled: return "已取消"
        }
    }

    static func resolve(_ raw: String) -> CollectionJobItemStatus? {
        CollectionJobItemStatus(rawValue: raw)
    }

    static func label(for raw: String) -> String {
        resolve(raw)?.label ?? raw
    }
}

enum CollectionJobStatusFilter: String, CaseIterable, Identifiable, Sendable {
    case all
    case pending
    case running
    case succeeded
    case partiallySucceeded = "partially_succeeded"
    case failed
    case cancelled

    var id: String { rawValue }

    var label: String {
        if self == .all { return "全部状态" }
        return CollectionJobStatus(rawValue: rawValue)?.label ?? rawValue
    }

    /// 用于 `GET /api/v1/collection-jobs?status=`；`all` 不传。
    var queryValue: String? {
        self == .all ? nil : rawValue
    }
}

enum CollectionTriggerType {
    static func label(for raw: String) -> String {
        switch raw {
        case "manual": return "手动"
        case "scheduled": return "定时"
        default: return raw
        }
    }
}

enum CollectionScope {
    static func label(for raw: String) -> String {
        switch raw {
        case "single_source": return "单个来源"
        case "all_enabled": return "全部启用来源"
        default: return raw
        }
    }
}

/// `GET /api/v1/collection/status`：采集引擎的实时运行状态。
struct CollectionStatusDTO: Decodable, Sendable {
    let schedulerEnabled: Bool
    let runningJobId: String?
    let maxConcurrency: Int
    let queueDepth: Int
}

/// `GET /api/v1/sources/{id}/health` 返回的健康日志。
struct SourceHealthLogDTO: Decodable, Hashable, Sendable {
    let checkedAt: String
    let status: String
    let httpStatus: Int?
    let latencyMs: Int?
    let errorCode: String?
    let errorMessage: String?
}

struct SourceHealthLogPage: Decodable, Sendable {
    let items: [SourceHealthLogDTO]
    let total: Int
}

enum SourceHealthStatus: String, CaseIterable, Sendable {
    case healthy
    case degraded
    case failing

    var label: String {
        switch self {
        case .healthy: return "健康"
        case .degraded: return "降级"
        case .failing: return "失败"
        }
    }

    static func label(for raw: String) -> String {
        SourceHealthStatus(rawValue: raw)?.label ?? raw
    }
}
