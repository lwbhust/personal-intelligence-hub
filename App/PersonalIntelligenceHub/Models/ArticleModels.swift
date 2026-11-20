import Foundation

/// Phase 2 文章读模型。字段与 `Docs/PHASE2_CONTRACT.md` §3.1 一致。
/// 所有后端可空字段均为 Optional；`status`/`contentState` 保持 String，
/// 由 UI 映射为展示枚举，未知值不会导致解码失败。
struct ArticleSummaryDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let sourceId: String
    let sourceName: String?
    let categoryId: String?
    let categoryName: String?
    let title: String
    let author: String?
    let summary: String?
    let canonicalUrl: String?
    let contentState: String
    let publishedAt: String?
    let fetchedAt: String
    let status: String
    let createdAt: String
    let updatedAt: String
    var readingStatus: String
    var isFavorite: Bool
    var lastReadAt: String?
    var readCount: Int

    // convertFromSnakeCase (set globally) maps JSON "reading_status" → "readingStatus".
    enum CodingKeys: String, CodingKey {
        case id, sourceId, sourceName, categoryId, categoryName,
             title, author, summary, canonicalUrl, contentState,
             publishedAt, fetchedAt, status, createdAt, updatedAt,
             readingStatus, isFavorite, lastReadAt, readCount
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        sourceId = try c.decode(String.self, forKey: .sourceId)
        sourceName = try c.decodeIfPresent(String.self, forKey: .sourceName)
        categoryId = try c.decodeIfPresent(String.self, forKey: .categoryId)
        categoryName = try c.decodeIfPresent(String.self, forKey: .categoryName)
        title = try c.decode(String.self, forKey: .title)
        author = try c.decodeIfPresent(String.self, forKey: .author)
        summary = try c.decodeIfPresent(String.self, forKey: .summary)
        canonicalUrl = try c.decodeIfPresent(String.self, forKey: .canonicalUrl)
        contentState = try c.decode(String.self, forKey: .contentState)
        publishedAt = try c.decodeIfPresent(String.self, forKey: .publishedAt)
        fetchedAt = try c.decode(String.self, forKey: .fetchedAt)
        status = try c.decode(String.self, forKey: .status)
        createdAt = try c.decode(String.self, forKey: .createdAt)
        updatedAt = try c.decode(String.self, forKey: .updatedAt)
        // Phase 5: decodeIfPresent + defaults for legacy payloads.
        readingStatus = try c.decodeIfPresent(String.self, forKey: .readingStatus) ?? "unread"
        isFavorite = try c.decodeIfPresent(Bool.self, forKey: .isFavorite) ?? false
        lastReadAt = try c.decodeIfPresent(String.self, forKey: .lastReadAt)
        readCount = try c.decodeIfPresent(Int.self, forKey: .readCount) ?? 0
    }

    init(from detail: ArticleDetailDTO) {
        self.id = detail.id
        self.sourceId = detail.sourceId
        self.sourceName = detail.sourceName
        self.categoryId = detail.categoryId
        self.categoryName = detail.categoryName
        self.title = detail.title
        self.author = detail.author
        self.summary = detail.summary
        self.canonicalUrl = detail.canonicalUrl
        self.contentState = detail.contentState
        self.publishedAt = detail.publishedAt
        self.fetchedAt = detail.fetchedAt
        self.status = detail.status
        self.createdAt = detail.createdAt
        self.updatedAt = detail.updatedAt
        self.readingStatus = detail.readingStatus
        self.isFavorite = detail.isFavorite
        self.lastReadAt = detail.lastReadAt
        self.readCount = detail.readCount
    }
}

struct ArticleDetailDTO: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let sourceId: String
    let sourceName: String?
    let categoryId: String?
    let categoryName: String?
    let title: String
    let author: String?
    let summary: String?
    let canonicalUrl: String?
    let contentState: String
    let publishedAt: String?
    let fetchedAt: String
    let status: String
    let createdAt: String
    let updatedAt: String
    let externalId: String?
    let originalUrl: String?
    let contentText: String?
    let sourceUpdatedAt: String?
    let contentHash: String
    var contentFetchedAt: String?
    var readingStatus: String
    var isFavorite: Bool
    var lastReadAt: String?
    var readCount: Int

    enum CodingKeys: String, CodingKey {
        case id, sourceId, sourceName, categoryId, categoryName,
             title, author, summary, canonicalUrl, contentState,
             publishedAt, fetchedAt, status, createdAt, updatedAt,
             externalId, originalUrl, contentText, sourceUpdatedAt, contentHash,
             contentFetchedAt, readingStatus, isFavorite, lastReadAt, readCount
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        sourceId = try c.decode(String.self, forKey: .sourceId)
        sourceName = try c.decodeIfPresent(String.self, forKey: .sourceName)
        categoryId = try c.decodeIfPresent(String.self, forKey: .categoryId)
        categoryName = try c.decodeIfPresent(String.self, forKey: .categoryName)
        title = try c.decode(String.self, forKey: .title)
        author = try c.decodeIfPresent(String.self, forKey: .author)
        summary = try c.decodeIfPresent(String.self, forKey: .summary)
        canonicalUrl = try c.decodeIfPresent(String.self, forKey: .canonicalUrl)
        contentState = try c.decode(String.self, forKey: .contentState)
        publishedAt = try c.decodeIfPresent(String.self, forKey: .publishedAt)
        fetchedAt = try c.decode(String.self, forKey: .fetchedAt)
        status = try c.decode(String.self, forKey: .status)
        createdAt = try c.decode(String.self, forKey: .createdAt)
        updatedAt = try c.decode(String.self, forKey: .updatedAt)
        externalId = try c.decodeIfPresent(String.self, forKey: .externalId)
        originalUrl = try c.decodeIfPresent(String.self, forKey: .originalUrl)
        contentText = try c.decodeIfPresent(String.self, forKey: .contentText)
        sourceUpdatedAt = try c.decodeIfPresent(String.self, forKey: .sourceUpdatedAt)
        contentHash = try c.decode(String.self, forKey: .contentHash)
        contentFetchedAt = try c.decodeIfPresent(String.self, forKey: .contentFetchedAt)
        readingStatus = try c.decodeIfPresent(String.self, forKey: .readingStatus) ?? "unread"
        isFavorite = try c.decodeIfPresent(Bool.self, forKey: .isFavorite) ?? false
        lastReadAt = try c.decodeIfPresent(String.self, forKey: .lastReadAt)
        readCount = try c.decodeIfPresent(Int.self, forKey: .readCount) ?? 0
    }
}

struct ArticlePage: Decodable, Sendable {
    let items: [ArticleSummaryDTO]
    let total: Int
    let limit: Int
    let offset: Int
}

/// 按需抓取正文的返回结果。`status` 为 fetched / cached / failed。
struct ArticleContentFetchResultDTO: Decodable, Sendable {
    let status: String
    let chars: Int
    let url: String?
    let errorCode: String?
    let errorMessage: String?
}

struct ArticleContentFetchResponseDTO: Decodable, Sendable {
    let article: ArticleDetailDTO
    let fetch: ArticleContentFetchResultDTO
}

/// 正文完整性展示。数据库值保持契约中的 snake_case。
enum ArticleContentState: String, CaseIterable, Identifiable, Sendable {
    case full
    case summaryOnly = "summary_only"
    case unavailable

    var id: String { rawValue }

    var label: String {
        switch self {
        case .full: return "完整正文"
        case .summaryOnly: return "仅摘要"
        case .unavailable: return "无正文"
        }
    }
}

enum ArticleStatusFilter: String, CaseIterable, Identifiable, Sendable {
    case active
    case archived

    var id: String { rawValue }

    var label: String {
        switch self {
        case .active: return "有效文章"
        case .archived: return "已归档"
        }
    }
}

/// 文章列表排序字段（与 API `order` 参数取值一致）。
enum ArticleOrder: String, CaseIterable, Identifiable, Sendable {
    case publishedAt = "published_at"
    case fetchedAt = "fetched_at"
    case createdAt = "created_at"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .publishedAt: return "发布时间"
        case .fetchedAt: return "采集时间"
        case .createdAt: return "入库时间"
        }
    }
}

enum SortDirection: String, CaseIterable, Identifiable, Sendable {
    case desc
    case asc

    var id: String { rawValue }

    var label: String {
        switch self {
        case .desc: return "降序"
        case .asc: return "升序"
        }
    }

    var shortLabel: String {
        switch self {
        case .desc: return "最新在前"
        case .asc: return "最早在前"
        }
    }
}

/// 服务端 UTC ISO8601 时间的展示转换。
/// 优先按带毫秒的 ISO8601 解析，失败再按秒级解析；仍失败时原样返回字符串，
/// 保证异常数据不会让界面崩溃。
enum PIHDateFormat {
    static func date(from value: String?) -> Date? {
        guard let value else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if let date = try? Date(trimmed, strategy: Date.ISO8601FormatStyle(includingFractionalSeconds: true)) {
            return date
        }
        if let date = try? Date(trimmed, strategy: Date.ISO8601FormatStyle()) {
            return date
        }
        return nil
    }

    static func display(_ value: String?, empty: String = "—") -> String {
        guard let value else { return empty }
        return display(value)
    }

    static func display(_ value: String) -> String {
        guard let date = date(from: value) else {
            return value
        }
        return date.formatted(.dateTime.year().month().day().hour().minute())
    }

    static func displayDetailed(_ value: String?, empty: String = "—") -> String {
        guard let value else { return empty }
        guard let date = date(from: value) else {
            return value
        }
        return date.formatted(.dateTime.year().month().day().hour().minute().second())
    }
}

// MARK: - Phase 5: Reading & Search

enum ReadingStatus: String, CaseIterable, Identifiable, Sendable {
    case unread, reading, read, later

    var id: String { rawValue }

    var label: String {
        switch self {
        case .unread: return "未读"
        case .reading: return "阅读中"
        case .read: return "已读"
        case .later: return "稍后阅读"
        }
    }
}

struct FtsSearchItem: Decodable, Identifiable, Sendable {
    let articleId: String
    let title: String
    let summary: String?
    let snippet: String
    let rank: Double
    let sourceName: String?
    let categoryName: String?
    let publishedAt: String?
    let fetchedAt: String
    let readingStatus: String
    let isFavorite: Bool

    var id: String { articleId }

    /// FTS5 返回的 snippet 带 `<mark>` 标记；界面用本地高亮替代，避免显示原始标签。
    var plainSnippet: String {
        snippet
            .replacingOccurrences(of: "<mark>", with: "")
            .replacingOccurrences(of: "</mark>", with: "")
    }
}

struct FtsSearchResponse: Decodable, Sendable {
    let items: [FtsSearchItem]
    let total: Int
    let limit: Int
    let offset: Int
    let query: String
}

enum PIHDuration {
    static func display(_ milliseconds: Int?) -> String {
        guard let milliseconds else { return "—" }
        if milliseconds < 1000 {
            return "\(milliseconds) ms"
        }
        let seconds = Double(milliseconds) / 1000
        return String(format: "%.1f s", seconds)
    }
}
