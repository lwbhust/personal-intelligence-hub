import SwiftUI

/// 「阅读」：统一文章管理入口。
///
/// 推荐、全部、稍后阅读、收藏、历史与全文搜索共享同一套阅读状态与阅读器。
enum ReadingTab: String, CaseIterable, Identifiable {
    case recommend
    case all
    case later
    case favorites
    case history
    case search

    var id: String { rawValue }

    var title: String {
        switch self {
        case .recommend: return "推荐"
        case .all: return "全部"
        case .later: return "稍后阅读"
        case .favorites: return "收藏"
        case .history: return "历史"
        case .search: return "搜索"
        }
    }

    var icon: String {
        switch self {
        case .recommend: return "sparkles"
        case .all: return "newspaper"
        case .later: return "clock"
        case .favorites: return "star"
        case .history: return "clock.arrow.circlepath"
        case .search: return "magnifyingglass"
        }
    }
}

struct ReadingScreen: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var articlesStore: ArticlesStore
    @ObservedObject var personalization: PersonalizationStore
    let onOpenEvent: (String) -> Void
    @StateObject private var searchStore = ArticleSearchStore()

    @State private var tab: ReadingTab = .recommend

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider().overlay(PIHColor.hairline)
            content
        }
        .frame(minWidth: 760, minHeight: 560)
        .background(PIHColor.canvas)
        .task(id: model.state) {
            searchStore.bind(model.apiClientForFeatures)
            await personalization.loadIfNeeded()
            await applyTab(tab)
        }
        .onChange(of: tab) { _, newValue in
            Task { await applyTab(newValue) }
        }
    }

    // MARK: - Toolbar

    private var toolbar: some View {
        PIHPageToolbar {
            HStack(spacing: PIHSpacing.control) {
                PageHeader("阅读", subtitle: readingSubtitle)
                Spacer(minLength: 12)
                Picker("视图", selection: $tab) {
                    ForEach(ReadingTab.allCases) { item in
                        Label(item.title, systemImage: item.icon).tag(item)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 520)
                Button {
                    Task { await refreshCurrentTab() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(PIHFont.captionMedium)
                }
                .disabled(model.apiClientForFeatures == nil)
                .help("刷新当前列表")
            }
        }
    }

    private var readingSubtitle: String {
        switch tab {
        case .recommend:
            return "按兴趣与事件重要性排序"
        case .all:
            return "共 \(articlesStore.total) 篇文章"
        case .later:
            return "稍后阅读不会改变兴趣权重"
        case .favorites:
            return "收藏会轻微提升相关主题的推荐"
        case .history:
            return "已读文章不会再次进入默认推荐"
        case .search:
            return "全文检索标题、摘要与已抓取正文"
        }
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        if !model.isDataReady {
            EmptyPanel(
                icon: "bolt.horizontal.circle",
                title: "本地服务未就绪",
                message: "阅读中心需要 Sidecar 运行。当前状态：\(model.state.title)。",
                actionTitle: "启动 Sidecar",
                action: { model.start() }
            )
        } else if tab == .search {
            searchContent
        } else {
            HSplitView {
                listPane
                ArticleDetailView(store: articlesStore)
                    .frame(minWidth: 380, maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    private var listPane: some View {
        VStack(spacing: 0) {
            if let message = listError {
                ErrorBanner(
                    message: message,
                    requestID: nil,
                    onRetry: { Task { await refreshCurrentTab() } },
                    onDismiss: { articlesStore.clearListError() }
                )
                .padding(10)
            }
            if showsArticleList {
                articleList
            } else {
                recommendList
            }
        }
        .frame(minWidth: 320, idealWidth: 380, maxWidth: 460, maxHeight: .infinity)
        .background(PIHColor.canvas)
    }

    private var showsArticleList: Bool {
        tab != .recommend
    }

    private var listError: String? {
        showsArticleList ? articlesStore.errorMessage : personalization.errorMessage
    }

    // MARK: - Recommendation list

    @ViewBuilder
    private var recommendList: some View {
        if personalization.isLoading && !personalization.hasLoaded {
            LoadingStateView(message: "正在计算推荐…")
        } else if let feed = personalization.feed {
            let items = Self.flatten(feed: feed)
            if items.isEmpty {
                EmptyPanel(
                    icon: "checkmark.circle",
                    title: "推荐已读完",
                    message: "今天没有更多未读推荐。可以到「全部」或「稍后阅读」继续。",
                    actionTitle: "查看全部文章",
                    action: { tab = .all }
                )
            } else {
                ScrollView {
                    LazyVStack(spacing: 10) {
                        ForEach(items) { item in
                            Button {
                                open(item)
                            } label: {
                                ReadingRecommendationRow(item: item)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(12)
                }
            }
        } else {
            LoadingStateView(message: "正在连接推荐服务…")
        }
    }

    // MARK: - Article list

    @ViewBuilder
    private var articleList: some View {
        if articlesStore.isLoading && !articlesStore.hasLoaded {
            LoadingStateView(message: "正在加载文章…")
        } else if articlesStore.articles.isEmpty {
            EmptyPanel(
                icon: emptyIcon,
                title: emptyTitle,
                message: emptyMessage,
                actionTitle: tab == .recommend ? nil : "查看全部文章",
                action: tab == .recommend ? nil : { tab = .all }
            )
        } else {
            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(articlesStore.articles) { article in
                        Button {
                            articlesStore.selectedArticleID = article.id
                        } label: {
                            ReadingArticleRow(
                                article: article,
                                isSelected: articlesStore.selectedArticleID == article.id
                            )
                        }
                        .buttonStyle(.plain)
                        Divider().overlay(PIHColor.hairline)
                    }
                    if articlesStore.canLoadMore {
                        Button {
                            Task { await articlesStore.loadMore() }
                        } label: {
                            Text("加载更多（\(articlesStore.articles.count) / \(articlesStore.total)）")
                                .font(PIHFont.caption)
                        }
                        .padding(.vertical, 12)
                    }
                }
            }
        }
    }

    private var emptyIcon: String {
        switch tab {
        case .later: return "clock"
        case .favorites: return "star"
        case .history: return "clock.arrow.circlepath"
        default: return "newspaper"
        }
    }

    private var emptyTitle: String {
        switch tab {
        case .later: return "还没有稍后阅读"
        case .favorites: return "还没有收藏"
        case .history: return "还没有阅读记录"
        default: return "没有匹配的文章"
        }
    }

    private var emptyMessage: String {
        switch tab {
        case .later: return "在今日或阅读列表中点击「稍后读」，文章会出现在这里。"
        case .favorites: return "在阅读器中点击星标即可收藏。"
        case .history: return "打开并标记已读的文章会保留在这里。"
        default: return "可调整筛选条件，或到其他视图查看。"
        }
    }

    // MARK: - Search

    private var searchContent: some View {
        VStack(spacing: 0) {
            VStack(spacing: 10) {
                HStack(spacing: 12) {
                    SearchField(placeholder: "搜索标题、摘要与正文", text: $searchStore.query, width: 360)
                    if searchStore.isLoading {
                        ProgressView().controlSize(.small)
                    }
                    if searchStore.hasSearched && !searchStore.isLoading {
                        Text("共 \(searchStore.total) 条")
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                    if searchStore.hasActiveFilters || !searchStore.query.isEmpty {
                        Button("清空条件") { searchStore.reset() }
                            .buttonStyle(.borderless)
                            .controlSize(.small)
                    }
                    Button("搜索") {
                        Task { await searchStore.search() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(searchStore.query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                              && !searchStore.hasActiveFilters)
                }

                HStack(spacing: 10) {
                    Menu {
                        Picker("阅读状态", selection: $searchStore.readingFilter) {
                            Text("全部阅读状态").tag(ReadingStatus?.none)
                            ForEach(ReadingStatus.allCases) { status in
                                Text(status.label).tag(Optional(status))
                            }
                        }
                    } label: {
                        Label(readingFilterLabel, systemImage: "book")
                            .font(PIHFont.caption)
                            .lineLimit(1)
                    }
                    .pihToolbarMenu()

                    Menu {
                        Picker("来源", selection: $searchStore.sourceFilter) {
                            Text("全部来源").tag(String?.none)
                            ForEach(searchStore.sources) { source in
                                Text(source.name).tag(Optional(source.id))
                            }
                        }
                    } label: {
                        Label(selectedSourceName, systemImage: "dot.radiowaves.left.and.right")
                            .font(PIHFont.caption)
                            .lineLimit(1)
                            .frame(maxWidth: 170, alignment: .leading)
                    }
                    .pihToolbarMenu()

                    Menu {
                        Picker("时间", selection: $searchStore.timeWindow) {
                            ForEach(SearchTimeWindow.allCases) { window in
                                Text(window.title).tag(window)
                            }
                        }
                    } label: {
                        Label(searchStore.timeWindow.title, systemImage: "calendar")
                            .font(PIHFont.caption)
                            .lineLimit(1)
                    }
                    .pihToolbarMenu()

                    Toggle("仅收藏", isOn: $searchStore.favoritesOnly)
                        .toggleStyle(.checkbox)

                    if searchStore.hasActiveFilters {
                        Text(activeFilterSummary)
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 0)
                }
            }
            .padding(.horizontal, PIHSpacing.page)
            .padding(.vertical, 12)

            Divider().overlay(PIHColor.hairline)

            HSplitView {
                searchResults
                    .frame(minWidth: 320, idealWidth: 380, maxWidth: 460, maxHeight: .infinity)
                    .background(PIHColor.canvas)
                ArticleDetailView(store: articlesStore)
                    .frame(minWidth: 380, maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task {
            searchStore.bind(model.apiClientForFeatures)
            await searchStore.loadSourcesIfNeeded()
        }
        .onChange(of: searchStore.query) { _, _ in searchStore.scheduleSearch() }
        .onChange(of: searchStore.readingFilter) { _, _ in searchStore.scheduleSearch() }
        .onChange(of: searchStore.favoritesOnly) { _, _ in searchStore.scheduleSearch() }
        .onChange(of: searchStore.sourceFilter) { _, _ in searchStore.scheduleSearch() }
        .onChange(of: searchStore.timeWindow) { _, _ in searchStore.scheduleSearch() }
    }

    private var readingFilterLabel: String {
        searchStore.readingFilter?.label ?? "全部阅读状态"
    }

    private var selectedSourceName: String {
        guard let id = searchStore.sourceFilter else { return "全部来源" }
        return searchStore.sources.first(where: { $0.id == id })?.name ?? "全部来源"
    }

    private var activeFilterSummary: String {
        var parts: [String] = []
        if let readingFilter = searchStore.readingFilter {
            parts.append(readingFilter.label)
        }
        if searchStore.favoritesOnly {
            parts.append("仅收藏")
        }
        if searchStore.sourceFilter != nil {
            parts.append(selectedSourceName)
        }
        if searchStore.timeWindow != .all {
            parts.append(searchStore.timeWindow.title)
        }
        return parts.isEmpty ? "未设置筛选" : "已筛选：" + parts.joined(separator: " · ")
    }

    @ViewBuilder
    private var searchResults: some View {
        if let error = searchStore.errorMessage {
            EmptyPanel(
                icon: "exclamationmark.triangle",
                title: "搜索失败",
                message: error,
                actionTitle: "重试",
                action: { Task { await searchStore.search() } }
            )
        } else if searchStore.hasSearched && searchStore.results.isEmpty {
            EmptyPanel(
                icon: "text.magnifyingglass",
                title: "没有找到匹配内容",
                message: "尝试更短的关键词，或调整来源、时间、阅读状态与收藏筛选。",
                actionTitle: "清空条件",
                action: { searchStore.reset() }
            )
        } else if searchStore.results.isEmpty {
            EmptyPanel(
                icon: "magnifyingglass",
                title: "搜索本地全文",
                message: "输入关键词检索标题、摘要与已抓取的正文，数据来自本地 SQLite。",
                actionTitle: nil,
                action: nil
            )
        } else {
            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(searchStore.results) { item in
                        Button {
                            articlesStore.selectedArticleID = item.articleId
                        } label: {
                            VStack(alignment: .leading, spacing: 6) {
                                HighlightedText(text: item.title, query: searchStore.query)
                                    .font(PIHFont.captionMedium)
                                    .lineLimit(2)
                                HighlightedText(text: item.plainSnippet, query: searchStore.query)
                                    .font(PIHFont.meta)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                                HStack(spacing: 6) {
                                    Text(item.sourceName ?? "未知来源")
                                    Text("·")
                                    Text(PIHDateFormat.display(item.publishedAt))
                                    if item.isFavorite {
                                        Image(systemName: "star.fill")
                                            .foregroundStyle(.yellow)
                                    }
                                }
                                .font(PIHFont.meta)
                                .foregroundStyle(.tertiary)
                            }
                            .padding(.horizontal, 14)
                            .padding(.vertical, 10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .pihRowBackground(isSelected: articlesStore.selectedArticleID == item.articleId)
                        }
                        .buttonStyle(.plain)
                        Divider().overlay(PIHColor.hairline)
                    }
                    Text("共 \(searchStore.total) 条结果")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                        .padding(.vertical, 12)
                }
            }
        }
    }

    // MARK: - Actions

    private func applyTab(_ tab: ReadingTab) async {
        switch tab {
        case .recommend:
            await personalization.loadIfNeeded()
        case .all:
            articlesStore.readingFilter = nil
            articlesStore.favoriteFilter = nil
            await articlesStore.applyFiltersAndReload()
        case .later:
            articlesStore.readingFilter = .later
            articlesStore.favoriteFilter = nil
            await articlesStore.applyFiltersAndReload()
        case .favorites:
            articlesStore.readingFilter = nil
            articlesStore.favoriteFilter = true
            await articlesStore.applyFiltersAndReload()
        case .history:
            articlesStore.readingFilter = .read
            articlesStore.favoriteFilter = nil
            await articlesStore.applyFiltersAndReload()
        case .search:
            break
        }
    }

    private func refreshCurrentTab() async {
        switch tab {
        case .recommend:
            await personalization.refresh()
        case .search:
            await searchStore.search()
        default:
            await applyTab(tab)
        }
    }

    private func open(_ item: FeedItemDTO) {
        if item.targetType == "event" {
            onOpenEvent(item.targetId)
            return
        }
        articlesStore.selectedArticleID = item.targetId
    }

    /// 推荐分区按后端优先级合并，客户端不重新排序。
    static func flatten(feed: PersonalFeedDTO) -> [FeedItemDTO] {
        var seen = Set<String>()
        var items: [FeedItemDTO] = []
        let sections = [
            feed.sections.mustRead,
            feed.sections.eventHighlights,
            feed.sections.coreInterest,
            feed.sections.leads,
        ]
        for section in sections {
            for item in section where !seen.contains(item.id) {
                seen.insert(item.id)
                items.append(item)
            }
        }
        return items
    }
}

// MARK: - Rows

private struct ReadingRecommendationRow: View {
    let item: FeedItemDTO

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 6) {
                LevelPill(level: RecommendationLevel(raw: item.level))
                FeedTargetBadge(item: item)
                Spacer(minLength: 0)
                Text("\(Int(item.score.rounded())) 分")
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
            }
            Text(item.title ?? "（无标题）")
                .font(PIHFont.captionMedium)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            if let summary = item.summary, !summary.isEmpty {
                Text(summary)
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            HStack(spacing: 6) {
                if item.targetType == "event" {
                    Text("\(item.articleCount) 篇报道 · \(item.sourceCount) 个来源")
                } else {
                    Text(item.sourceName ?? "未知来源")
                }
                if let published = item.publishedAt {
                    Text("·")
                    Text(PIHDateFormat.display(published))
                }
                Spacer(minLength: 0)
            }
            .font(PIHFont.meta)
            .foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .pihCard(padding: 0)
    }
}

private struct ReadingArticleRow: View {
    let article: ArticleSummaryDTO
    let isSelected: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Circle()
                .fill(isUnread ? Color.accentColor : Color.clear)
                .frame(width: 7, height: 7)
                .padding(.top, 7)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(article.title)
                        .font(PIHFont.captionMedium)
                        .fontWeight(isUnread ? .semibold : .regular)
                        .lineLimit(3)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 4)
                    if article.isFavorite {
                        Image(systemName: "star.fill")
                            .font(PIHFont.iconSmall)
                            .foregroundStyle(.yellow)
                    }
                }
                HStack(spacing: 6) {
                    Text(article.sourceName ?? "未知来源")
                    Text("·")
                    Text(PIHDateFormat.display(article.publishedAt))
                    Spacer(minLength: 0)
                    Text(ReadingStatus(rawValue: article.readingStatus)?.label ?? article.readingStatus)
                }
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .pihRowBackground(isSelected: isSelected)
    }

    private var isUnread: Bool {
        (ReadingStatus(rawValue: article.readingStatus) ?? .unread) == .unread
    }
}

// MARK: - Search store

/// 搜索的时间范围。只过滤发布时间，不影响排序。
enum SearchTimeWindow: String, CaseIterable, Identifiable {
    case all
    case day
    case week
    case month

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all: return "全部时间"
        case .day: return "近 24 小时"
        case .week: return "近 7 天"
        case .month: return "近 30 天"
        }
    }

    var days: Int? {
        switch self {
        case .all: return nil
        case .day: return 1
        case .week: return 7
        case .month: return 30
        }
    }

    /// 服务端按字符串比较 UTC ISO 时间，必须与数据库格式一致。
    func startTimestamp(now: Date = Date()) -> String? {
        guard let days else { return nil }
        let calendar = Calendar(identifier: .gregorian)
        let start = calendar.date(byAdding: .day, value: -days, to: now) ?? now
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: start)
    }
}

@MainActor
final class ArticleSearchStore: ObservableObject {
    @Published var query = ""
    @Published var readingFilter: ReadingStatus?
    @Published var favoritesOnly = false
    @Published var sourceFilter: String?
    @Published var timeWindow: SearchTimeWindow = .all
    @Published private(set) var sources: [SourceDTO] = []
    @Published private(set) var results: [FtsSearchItem] = []
    @Published private(set) var total = 0
    @Published private(set) var isLoading = false
    @Published private(set) var hasSearched = false
    @Published private(set) var errorMessage: String?

    private weak var client: APIClient?
    private var task: Task<Void, Never>?

    var hasActiveFilters: Bool {
        readingFilter != nil || favoritesOnly || sourceFilter != nil || timeWindow != .all
    }

    func bind(_ client: APIClient?) {
        if client === self.client { return }
        self.client = client
        if client == nil {
            sources = []
            results = []
            total = 0
            hasSearched = false
        }
    }

    func loadSourcesIfNeeded() async {
        guard let client, sources.isEmpty else { return }
        do {
            let page = try await client.fetchSources(
                query: [
                    URLQueryItem(name: "limit", value: "100"),
                    URLQueryItem(name: "offset", value: "0"),
                    URLQueryItem(name: "order", value: "name"),
                    URLQueryItem(name: "direction", value: "asc"),
                    URLQueryItem(name: "enabled", value: "true"),
                ]
            )
            sources = page.items
        } catch {
            // 来源筛选不是搜索的前置条件：失败时保持「全部来源」。
            sources = []
        }
    }

    func scheduleSearch() {
        task?.cancel()
        task = Task {
            try? await Task.sleep(for: .milliseconds(320))
            guard !Task.isCancelled else { return }
            await search()
        }
    }

    func search() async {
        guard let client else { return }
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty || hasActiveFilters else {
            results = []
            total = 0
            hasSearched = false
            return
        }
        isLoading = true
        defer { isLoading = false }
        var items = [
            URLQueryItem(name: "q", value: trimmed),
            URLQueryItem(name: "limit", value: "30"),
            URLQueryItem(name: "offset", value: "0"),
            URLQueryItem(name: "order", value: trimmed.isEmpty ? "published_at" : "rank"),
        ]
        if let readingFilter {
            items.append(URLQueryItem(name: "reading_status", value: readingFilter.rawValue))
        }
        if favoritesOnly {
            items.append(URLQueryItem(name: "is_favorite", value: "true"))
        }
        if let sourceFilter, !sourceFilter.isEmpty {
            items.append(URLQueryItem(name: "source_id", value: sourceFilter))
        }
        if let start = timeWindow.startTimestamp() {
            items.append(URLQueryItem(name: "start_published_at", value: start))
        }
        do {
            let page = try await client.searchArticles(query: items)
            results = page.items
            total = page.total
            hasSearched = true
            errorMessage = nil
        } catch {
            if error is CancellationError { return }
            errorMessage = (error as? APIRequestError)?.message ?? error.localizedDescription
        }
    }

    func reset() {
        query = ""
        readingFilter = nil
        favoritesOnly = false
        sourceFilter = nil
        timeWindow = .all
        results = []
        total = 0
        hasSearched = false
        errorMessage = nil
    }
}
