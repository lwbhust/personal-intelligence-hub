import Foundation

/// Phase 1 API 读模型。字段与 `Docs/PHASE1_API_DESIGN.md` 一致。
struct SourceCategoryDTO: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let name: String
    let description: String?
    let sortOrder: Int
    let sourceCount: Int
    let createdAt: String
    let updatedAt: String
}

struct CategoryRef: Codable, Hashable, Sendable {
    let id: String
    let name: String
}

struct SourceDTO: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let name: String
    let sourceType: String
    let url: String
    let homepageUrl: String?
    let description: String?
    let language: String?
    let country: String?
    let priority: Int
    let credibilityScore: Int?
    let fetchIntervalMinutes: Int
    let maxEntriesPerFetch: Int?
    let enabled: Bool
    let healthStatus: String
    let lastFetchAt: String?
    let lastSuccessAt: String?
    let lastErrorAt: String?
    let lastErrorCode: String?
    let lastErrorMessage: String?
    let category: CategoryRef?
    let articleCount: Int
    let adapterVerification: String?
    let createdAt: String
    let updatedAt: String
}

struct SourcePage: Codable, Sendable {
    let items: [SourceDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

struct SourceAdapterDTO: Codable, Sendable {
    let sourceId: String
    let adapterType: String
    let entryUrl: String
    let listUrls: [String]
    let linkPattern: String?
    let maxPages: Int
    let rateLimitSeconds: Int
    let maxEntriesPerRun: Int
    let fetchFullText: Bool
    let configVersion: String
    let lastVerifiedAt: String?
    let lastVerification: String
    let createdAt: String
    let updatedAt: String
}

struct AdapterDryRunEntryDTO: Codable, Sendable {
    let title: String
    let link: String?
    let publishedAt: String?
    let summaryChars: Int
    let contentChars: Int
    let contentState: String
}

struct AdapterDryRunDTO: Codable, Sendable {
    let sourceId: String
    let adapterType: String
    let httpStatus: Int?
    let durationMs: Int
    let suggestion: String
    let entries: [AdapterDryRunEntryDTO]
    let errors: [String]
}

struct AdapterDraft {
    var enabled = false
    var listURLsText = ""
    var linkPattern = ""
    var maxPages = 1
    var rateLimitSeconds = 5
    var maxEntriesPerRun = 12
    var fetchFullText = false
    var lastVerification = "unknown"

    init() {}

    init(record: SourceAdapterDTO) {
        enabled = true
        listURLsText = record.listUrls.joined(separator: "\n")
        linkPattern = record.linkPattern ?? ""
        maxPages = record.maxPages
        rateLimitSeconds = record.rateLimitSeconds
        maxEntriesPerRun = record.maxEntriesPerRun
        fetchFullText = record.fetchFullText
        lastVerification = record.lastVerification
    }

    var listURLs: [String] {
        listURLsText
            .split(whereSeparator: { $0 == "\n" || $0 == "\r" })
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    func payload() throws -> Data {
        let body: [String: Any] = [
            "adapter_type": "html_list",
            "list_urls": listURLs,
            "link_pattern": linkPattern.trimmingCharacters(in: .whitespacesAndNewlines),
            "max_pages": maxPages,
            "rate_limit_seconds": rateLimitSeconds,
            "max_entries_per_run": maxEntriesPerRun,
            "fetch_full_text": fetchFullText,
        ]
        return try JSONSerialization.data(withJSONObject: body)
    }
}

/// 类型展示文案。数据库值保持契约中的 snake_case。
enum SourceType: String, CaseIterable, Identifiable, Sendable {
    case rss
    case atom
    case website
    case officialAnnouncement = "official_announcement"
    case api

    var id: String { rawValue }

    var label: String {
        switch self {
        case .rss: return "RSS"
        case .atom: return "Atom"
        case .website: return "网站"
        case .officialAnnouncement: return "官方公告"
        case .api: return "API"
        }
    }
}

/// 表单草稿。所有后端可空字段用空字符串表示“未填写”，保存时显式转为 null。
struct SourceDraft: Identifiable {
    var id = UUID()
    var sourceID: String?
    var name = ""
    var sourceType: SourceType = .rss
    var url = ""
    var homepageURL = ""
    var categoryID: String?
    var description = ""
    var language = ""
    var country = ""
    var priority = 0
    var credibility = ""
    var interval = 60
    var maxEntries = ""
    var enabled = true

    var isEditing: Bool { sourceID != nil }

    init() {}

    init(source: SourceDTO) {
        sourceID = source.id
        name = source.name
        sourceType = SourceType(rawValue: source.sourceType) ?? .rss
        url = source.url
        homepageURL = source.homepageUrl ?? ""
        categoryID = source.category?.id
        description = source.description ?? ""
        language = source.language ?? ""
        country = source.country ?? ""
        priority = source.priority
        credibility = source.credibilityScore.map(String.init) ?? ""
        interval = source.fetchIntervalMinutes
        maxEntries = source.maxEntriesPerFetch.map(String.init) ?? ""
        enabled = source.enabled
    }

    /// 全字段 PATCH：空值显式写 null，避免“省略即不变”导致无法清空。
    func payload() throws -> Data {
        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedURL = url.trimmingCharacters(in: .whitespacesAndNewlines)
        let body: [String: Any] = [
            "name": trimmedName,
            "source_type": sourceType.rawValue,
            "url": trimmedURL,
            "homepage_url": optional(homepageURL),
            "category_id": categoryID ?? NSNull(),
            "description": optional(description),
            "language": optional(language),
            "country": optional(country.isEmpty ? "" : country.uppercased()),
            "priority": priority,
            "credibility_score": credibility.isEmpty ? NSNull() : (Int(credibility) ?? NSNull()),
            "fetch_interval_minutes": interval,
            "max_entries_per_fetch": maxEntries.isEmpty
                ? NSNull()
                : (Int(maxEntries) ?? NSNull()),
            "enabled": enabled,
        ]
        return try JSONSerialization.data(withJSONObject: body)
    }

    private func optional(_ value: String) -> Any {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? NSNull() : trimmed
    }
}

struct CategoryDraft: Identifiable {
    var id = UUID()
    var categoryID: String?
    var name = ""
    var description = ""
    var sortOrder = 0

    var isEditing: Bool { categoryID != nil }

    init() {}

    init(category: SourceCategoryDTO) {
        categoryID = category.id
        name = category.name
        description = category.description ?? ""
        sortOrder = category.sortOrder
    }

    func payload() throws -> Data {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let body: [String: Any] = [
            "name": trimmed,
            "description": description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? NSNull()
                : description,
            "sort_order": sortOrder,
        ]
        return try JSONSerialization.data(withJSONObject: body)
    }
}

enum SourceTypeFilter: String, CaseIterable, Identifiable, Sendable {
    case all
    case rss
    case atom
    case website
    case officialAnnouncement = "official_announcement"
    case api

    var id: String { rawValue }

    var label: String {
        if self == .all { return "全部类型" }
        return SourceType(rawValue: rawValue)?.label ?? rawValue
    }
}

enum EnabledFilter: String, CaseIterable, Identifiable, Sendable {
    case all
    case enabled
    case disabled

    var id: String { rawValue }

    var label: String {
        switch self {
        case .all: return "全部状态"
        case .enabled: return "已启用"
        case .disabled: return "已停用"
        }
    }
}
