import SwiftUI

/// 文章浏览：关键词/来源/分类/状态筛选，发布时间或采集时间排序，分页加载。
/// Phase 7.0：更大的标题、清晰的未读状态、关键词高亮与统一工具栏。
struct ArticlesScreen: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var store: ArticlesStore

    @State private var searchTask: Task<Void, Never>?

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider().overlay(PIHColor.hairline)
            content
        }
        .frame(minWidth: 760, minHeight: 560)
        .background(PIHColor.canvas)
        .task {
            // Navigation may happen long after the store was bound; always
            // refresh from the real API when this screen appears.
            await store.reload()
        }
        .onDisappear { searchTask?.cancel() }
    }

    // MARK: - Toolbar

    private var toolbar: some View {
        PIHPageToolbar {
            HStack(spacing: PIHSpacing.control) {
                PageHeader(
                    "文章",
                    subtitle: store.hasLoaded ? "共 \(store.total) 篇 · 按\(store.order.label)排序" : "尚未加载"
                )

                Spacer(minLength: 12)

                SearchField(placeholder: "搜索标题或摘要", text: $store.searchText, width: 250)
                    .onChange(of: store.searchText) { _, _ in
                        scheduleSearch()
                    }

                filterMenu
                sortMenu

                Button {
                    Task { await store.reload() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(PIHFont.captionMedium)
                }
                .help("刷新")
                .disabled(store.isLoading)
            }
        }
    }

    private var filterMenu: some View {
        Menu {
            Picker("来源", selection: $store.sourceFilter) {
                Text("全部来源").tag(String?.none)
                ForEach(store.filterSources) { source in
                    Text(source.name).tag(Optional(source.id))
                }
            }
            Picker("分类", selection: $store.categoryFilter) {
                Text("全部分类").tag(String?.none)
                ForEach(store.filterCategories) { category in
                    Text(category.name).tag(Optional(category.id))
                }
            }
            Picker("文章状态", selection: $store.statusFilter) {
                ForEach(ArticleStatusFilter.allCases) { filter in
                    Text(filter.label).tag(filter)
                }
            }
            Picker("阅读状态", selection: $store.readingFilter) {
                Text("全部阅读状态").tag(ReadingStatus?.none)
                ForEach(ReadingStatus.allCases) { status in
                    Text(status.label).tag(Optional(status))
                }
            }
            if let message = store.filterOptionsError {
                Divider()
                Text("筛选选项加载失败：\(message)")
            }
        } label: {
            Label("筛选", systemImage: "line.3.horizontal.decrease.circle")
                .font(PIHFont.caption)
        }
        .pihToolbarMenu()
        .onChange(of: store.sourceFilter) { _, _ in reloadForFilters() }
        .onChange(of: store.categoryFilter) { _, _ in reloadForFilters() }
        .onChange(of: store.statusFilter) { _, _ in reloadForFilters() }
        .onChange(of: store.readingFilter) { _, _ in reloadForFilters() }
    }

    private var sortMenu: some View {
        Menu {
            Picker("排序字段", selection: $store.order) {
                ForEach(ArticleOrder.allCases) { order in
                    Text(order.label).tag(order)
                }
            }
            Picker("方向", selection: $store.direction) {
                ForEach(SortDirection.allCases) { direction in
                    Text(direction.shortLabel).tag(direction)
                }
            }
        } label: {
            Label("排序", systemImage: "arrow.up.arrow.down")
                .font(PIHFont.caption)
        }
        .pihToolbarMenu()
        .onChange(of: store.order) { _, _ in reloadForFilters() }
        .onChange(of: store.direction) { _, _ in reloadForFilters() }
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        if !model.isDataReady {
            EmptyPanel(
                icon: "bolt.horizontal.circle",
                title: "本地服务未就绪",
                message: "文章浏览需要 Sidecar 正常运行。当前状态：\(model.state.title)。",
                actionTitle: "启动 Sidecar",
                action: { model.start() }
            )
        } else if store.isLoading && !store.hasLoaded {
            LoadingStateView(message: "正在加载文章…")
        } else if let message = store.errorMessage, store.articles.isEmpty {
            EmptyPanel(
                icon: "exclamationmark.triangle",
                title: "文章加载失败",
                message: message,
                actionTitle: "重试",
                action: { Task { await store.reload() } }
            )
        } else if store.articles.isEmpty {
            EmptyPanel(
                icon: hasActiveQuery ? "text.magnifyingglass" : "newspaper",
                title: hasActiveQuery ? "没有匹配的文章" : "还没有文章",
                message: hasActiveQuery
                    ? "尝试清空搜索词，或调整来源、分类、文章状态与阅读状态筛选。"
                    : "文章由真实采集任务写入本地 SQLite。请先到「采集任务」触发一次采集。",
                actionTitle: nil,
                action: nil
            )
        } else {
            HSplitView {
                listPane
                ArticleDetailView(store: store)
                    .frame(minWidth: 360, maxWidth: .infinity, maxHeight: .infinity)
            }        }
    }

    private var listPane: some View {
        List(selection: $store.selectedArticleID) {
            if let message = store.errorMessage {
                Section {
                    ErrorBanner(
                        message: message,
                        requestID: store.errorRequestID,
                        onRetry: { Task { await store.reload() } },
                        onDismiss: { store.clearListError() }
                    )
                    .listRowSeparator(.hidden)
                }
            }
            ForEach(store.articles) { article in
                ArticleRow(article: article, query: store.searchText)
                    .tag(article.id)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: 3, leading: 8, bottom: 3, trailing: 8))
            }
            if store.canLoadMore {
                HStack {
                    Spacer()
                    Button {
                        Task { await store.loadMore() }
                    } label: {
                        if store.isLoading {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("加载更多（已显示 \(store.articles.count) / \(store.total)）")
                                .font(PIHFont.caption)
                        }
                    }
                    .disabled(store.isLoading)
                    Spacer()
                }
                .padding(.vertical, 10)
                .listRowSeparator(.hidden)
            }
        }
        .listStyle(.inset)
        .scrollContentBackground(.hidden)
        .background(PIHColor.canvas)
        .frame(minWidth: 260, idealWidth: 320, maxWidth: 400, maxHeight: .infinity)
    }

    // MARK: - Helpers

    private var hasActiveQuery: Bool {
        !store.searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || store.sourceFilter != nil
            || store.categoryFilter != nil
            || store.statusFilter != .active
            || store.readingFilter != nil
    }

    private func scheduleSearch() {
        searchTask?.cancel()
        searchTask = Task {
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled else { return }
            await store.applyFiltersAndReload()
        }
    }

    private func reloadForFilters() {
        Task { await store.applyFiltersAndReload() }
    }
}

private struct ArticleRow: View {
    let article: ArticleSummaryDTO
    let query: String

    private var isUnread: Bool {
        (ReadingStatus(rawValue: article.readingStatus) ?? .unread) == .unread
    }

    /// 与阅读页同一套摘要校验：占位摘要（如「点击查看原文」）不在列表出现。
    private var previewSummary: String? {
        ArticleReaderText.meaningfulSummary(article.summary, title: article.title)
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Circle()
                .fill(isUnread ? Color.accentColor : Color.clear)
                .frame(width: 7, height: 7)
                .padding(.top, 8)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 7) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    HighlightedText(text: article.title, query: query)
                        .font(PIHFont.subsectionTitle)
                        .fontWeight(isUnread ? .semibold : .regular)
                        .lineLimit(3)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 6)
                    if article.isFavorite {
                        Image(systemName: "star.fill")
                            .font(PIHFont.iconSmall)
                            .foregroundStyle(.yellow)
                            .accessibilityLabel("已收藏")
                    }
                }

                HStack(spacing: 6) {
                    Text(article.sourceName ?? article.sourceId)
                        .lineLimit(1)
                    if let category = article.categoryName, !category.isEmpty {
                        Text("·")
                            .foregroundStyle(.tertiary)
                        Text(category)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 6)
                    Text(PIHDateFormat.display(article.publishedAt, empty: "时间未知"))
                        .monospacedDigit()
                        .layoutPriority(1)
                        .lineLimit(1)
                }
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)

                if let summary = previewSummary {
                    HighlightedText(text: summary, query: query)
                        .font(PIHFont.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 11)
        .pihRowBackground(isSelected: false)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "\(isUnread ? "未读，" : "")\(article.title)，来源 \(article.sourceName ?? "未知")，发布 "
                + PIHDateFormat.display(article.publishedAt, empty: "时间未知")
                + "，阅读状态 "
                + (ReadingStatus(rawValue: article.readingStatus)?.label ?? article.readingStatus)
        )
    }
}
