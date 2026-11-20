import Foundation

/// Phase 3 本地 AI 分析读模型。字段与 `Docs/PHASE3_API.md` 一致。
struct AIEmbeddingStatusDTO: Decodable, Hashable, Sendable {
    let enabled: Bool
    let reason: String?
}

struct AIStatusDTO: Decodable, Sendable {
    let enabled: Bool
    let providerKind: String
    let baseUrl: String
    let available: Bool
    let version: String?
    let errorCode: String?
    let defaultModel: String?
    let enabledModels: [String]
    let installedModels: [String]
    let cloudModelsBlocked: Int
    let concurrency: Int
    let queueDepth: Int
    let runningRunId: String?
    let embedding: AIEmbeddingStatusDTO
    let checkedAt: String
}

struct AIModelDTO: Decodable, Identifiable, Sendable {
    let modelName: String
    let enabled: Bool
    let roles: [String]
    let numCtx: Int
    let digest: String?
    let sizeBytes: Int?
    let parameterSize: String?
    let quantization: String?
    let maxContext: Int?
    let installed: Bool
    let remote: Bool
    let lastCheckedAt: String?

    var id: String { modelName }
}

struct AIModelPage: Decodable, Sendable {
    let items: [AIModelDTO]
    let total: Int
}

struct AIRunItemDTO: Decodable, Identifiable, Sendable {
    let id: String
    let runId: String
    let articleId: String
    let articleTitle: String?
    let status: String
    let attempts: Int
    let errorCode: String?
    let errorMessage: String?
    let startedAt: String?
    let finishedAt: String?
    let durationMs: Int?
}

struct AIRunDTO: Decodable, Identifiable, Sendable {
    let id: String
    let triggerType: String
    let scope: String
    let status: String
    let requestedCount: Int
    let processedCount: Int
    let succeededCount: Int
    let failedCount: Int
    let skippedCount: Int
    let modelName: String?
    let errorMessage: String?
    let cancelRequested: Bool
    let pauseRequested: Bool
    let startedAt: String?
    let finishedAt: String?
    let durationMs: Int?
    let createdAt: String
    let updatedAt: String
    let items: [AIRunItemDTO]
}

struct AIRunPage: Decodable, Sendable {
    let items: [AIRunDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

struct AIEntityDTO: Decodable, Hashable, Sendable {
    let name: String
    let type: String
}

struct AIAnalysisDTO: Decodable, Identifiable, Sendable {
    let id: String
    let analysisType: String
    let category: String
    let summary: String
    let keywords: [String]
    let entities: [AIEntityDTO]
    let confidence: Double
    let modelName: String
    let modelDigest: String?
    let promptVersion: String
    let params: [String: AIJSONValue]
    let inputChars: Int
    let durationMs: Int
    let contentHash: String
    let createdAt: String
}

struct ArticleAnalysisDTO: Decodable, Sendable {
    let articleId: String
    let items: [AIAnalysisDTO]
}

/// `params` 的值类型不固定，用轻量枚举避免 `[String: Any]` 破坏 Sendable。
enum AIJSONValue: Decodable, Hashable, Sendable {
    case string(String)
    case number(Double)
    case integer(Int)
    case bool(Bool)
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .integer(value)
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
        case .integer(let value): return String(value)
        case .number(let value): return String(value)
        case .bool(let value): return value ? "true" : "false"
        case .null: return "—"
        }
    }
}

enum AIRunStatus: String, Sendable {
    case pending
    case running
    case paused
    case succeeded
    case partiallySucceeded = "partially_succeeded"
    case failed
    case cancelled

    var label: String {
        switch self {
        case .pending: return "排队中"
        case .running: return "分析中"
        case .paused: return "已暂停"
        case .succeeded: return "已完成"
        case .partiallySucceeded: return "部分完成"
        case .failed: return "失败"
        case .cancelled: return "已取消"
        }
    }

    var isActive: Bool {
        self == .pending || self == .running || self == .paused
    }
}

func aiRunStatusLabel(_ raw: String) -> String {
    AIRunStatus(rawValue: raw)?.label ?? raw
}

func aiItemStatusLabel(_ raw: String) -> String {
    switch raw {
    case "pending": return "等待"
    case "running": return "分析中"
    case "succeeded": return "成功"
    case "failed": return "失败"
    case "skipped": return "跳过"
    case "cancelled": return "已取消"
    default: return raw
    }
}

func aiErrorLabel(_ code: String?) -> String {
    guard let code, !code.isEmpty else { return "—" }
    switch code {
    case "model_unavailable": return "本地模型不可用"
    case "model_not_allowed": return "模型不在白名单"
    case "cloud_model_blocked": return "云端模型已阻断"
    case "provider_endpoint_rejected": return "Provider 地址被拒绝"
    case "provider_timeout": return "模型请求超时"
    case "provider_unreachable": return "无法连接本地 Ollama"
    case "provider_http_error": return "本地模型返回错误"
    case "response_too_large": return "模型响应过大"
    case "invalid_response": return "模型响应格式异常"
    case "prompt_too_long": return "文章头部异常超长"
    case "schema_invalid": return "输出结构校验失败"
    case "invalid_json": return "模型输出不是 JSON"
    case "article_not_analyzable": return "文章没有可分析文本"
    case "interrupted": return "任务被中断"
    case "internal_error": return "内部错误"
    default: return code
    }
}
