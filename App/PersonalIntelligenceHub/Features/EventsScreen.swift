import SwiftUI

/// 事件中心：事件列表、详情、时间线、实体、关联事件、评分解释与人工校正。
/// 所有内容来自真实 Sidecar API；空态、错误态与加载态均为真实状态。
/// Phase 7.0：统一设计系统、放大标题与正文、收敛工具栏与筛选区。
struct EventsScreen: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var store: EventStore

    @State private var useLLM = false
    @State private var showRename = false
    @State private var renameText = ""
    @State private var showStatusEditor = false
    @State private var newStatus = "active"
    @State private var statusReason = ""
    @State private var showMerge = false
    @State private var mergeTarget = ""
    @State private var mergeReason = ""
    @State private var showSplit = false
    @State private var splitSelection: Set<String> = []
    @State private var splitTitle = ""
    @State private var showAddArticle = false
    @State private var pendingRemove: EventArticleDTO?
    @State private var showUnmergeConfirm = false
    @State private var showAllTimeline = false

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(PIHColor.hairline)
            filterBar
            Divider().overlay(PIHColor.hairline)
            banners
            rankingStrip
            content
        }
        .background(PIHColor.canvas)
        .task { if !store.hasLoaded { await store.reload() } }
        .onChange(of: store.order) { _, _ in Task { await store.reload() } }
        .onChange(of: store.window) { _, _ in Task { await store.reload() } }
        .onChange(of: store.statusFilter) { _, _ in Task { await store.reload() } }
        .onChange(of: store.categoryFilter) { _, _ in Task { await store.reload() } }
        .onChange(of: store.rankingKind) { _, _ in Task { await store.refreshRankings() } }
        .sheet(isPresented: $showRename) { renameSheet }
        .sheet(isPresented: $showStatusEditor) { statusSheet }
        .sheet(isPresented: $showMerge) { mergeSheet }
        .sheet(isPresented: $showSplit) { splitSheet }
        .sheet(isPresented: $showAddArticle) { addArticleSheet }
        .confirmationDialog(
            "撤销合并会把文章与时间线节点移回本事件；事件关系不会自动恢复。",
            isPresented: $showUnmergeConfirm,
            titleVisibility: .visible
        ) {
            Button("撤销合并", role: .destructive) { Task { await store.unmerge() } }
            Button("取消", role: .cancel) {}
        }
        .confirmationDialog(
            pendingRemove == nil ? "" : "将从事件中移出《\(pendingRemove?.title ?? "")》",
            isPresented: Binding(
                get: { pendingRemove != nil },
                set: { if !$0 { pendingRemove = nil } }
            ),
            titleVisibility: .visible
        ) {
            Button("移出事件", role: .destructive) {
                let article = pendingRemove
                pendingRemove = nil
                if let article {
                    Task { await store.removeArticle(article.articleId) }
                }
            }
            Button("取消", role: .cancel) { pendingRemove = nil }
        }
    }

    // MARK: - Header & filters

    private var header: some View {
        PIHPageToolbar {
            PageHeader("事件", subtitle: subtitle) {
                HStack(spacing: PIHSpacing.control) {
                    Menu {
                        Toggle("本地模型辅助判断", isOn: $useLLM)
                        Divider()
                        Button("增量聚类（仅未分配文章）") {
                            Task { await store.runClustering(scope: "incremental", limit: 200, useLLM: useLLM) }
                        }
                        Button("全量重聚类（不改人工边界）") {
                            Task { await store.runClustering(scope: "full", limit: 200, useLLM: useLLM) }
                        }
                        Divider()
                        Button("重算过期评分（超过 24 小时）") {
                            Task { await store.recomputeScores() }
                        }
                    } label: {
                        Label("维护", systemImage: "wrench.and.screwdriver")
                            .font(PIHFont.caption)
                    }
                    .pihToolbarMenu()
                    .disabled(store.isBusy)
                    .help("自动聚合默认开启；这里仅在需要手动修正时使用，不会上传数据")

                    if store.isLoading || store.isBusy {
                        ProgressView().controlSize(.small)
                    }

                    Button {
                        Task { await store.reload() }
                    } label: {
                        Label("刷新", systemImage: "arrow.clockwise")
                            .font(PIHFont.caption)
                    }
                    .disabled(store.isLoading)
                }
            }
        }
    }

    private var subtitle: String {
        guard store.hasLoaded else { return "尚未加载" }
        var text = "共 \(store.total) 个事件"
        if let status = store.clusterStatus {
            text += " · \(status.runningRunId == nil ? "聚类空闲" : "聚类进行中")"
            if !status.algorithmVersion.isEmpty {
                text += " · \(status.algorithmVersion)"
            }
        }
        return text
    }

    private var filterBar: some View {
        HStack(spacing: PIHSpacing.control) {
            SearchField(placeholder: "搜索事件标题或摘要", text: $store.keyword, width: 230)
                .onSubmit { Task { await store.reload() } }

            Picker("排序", selection: $store.order) {
                Text("综合重要性").tag("importance")
                Text("最近更新").tag("recent")
                Text("热度").tag("heat")
                Text("文章数").tag("articles")
            }
            .frame(width: 148)

            Picker("时间", selection: $store.window) {
                Text("全部时间").tag("all")
                Text("近 24 小时").tag("24h")
                Text("近 7 天").tag("7d")
                Text("近 30 天").tag("30d")
            }
            .frame(width: 140)

            Picker("状态", selection: $store.statusFilter) {
                Text("全部状态").tag(String?.none)
                Text("活跃").tag(String?.some("active"))
                Text("发展中").tag(String?.some("evolving"))
                Text("休眠").tag(String?.some("dormant"))
                Text("候选").tag(String?.some("candidate"))
                Text("已结束").tag(String?.some("closed"))
                Text("已归档").tag(String?.some("archived"))
                Text("已合并").tag(String?.some("merged"))
            }
            .frame(width: 140)

            Picker("分类", selection: $store.categoryFilter) {
                Text("全部分类").tag(String?.none)
                ForEach(["科技", "财经", "政治", "国际", "社会", "健康", "教育", "文化", "体育", "其他"], id: \.self) { name in
                    Text(name).tag(String?.some(name))
                }
            }
            .frame(width: 128)

            Spacer(minLength: 8)

            Text("已加载 \(store.events.count) / \(store.total)")
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, PIHSpacing.page)
        .padding(.vertical, 12)
    }

    @ViewBuilder
    private var banners: some View {
        if let message = store.errorMessage {
            ErrorBanner(
                message: message,
                requestID: nil,
                onRetry: { Task { await store.reload() } },
                onDismiss: { store.clearError() }
            )
            .padding(.horizontal, PIHSpacing.page)
            .padding(.top, 12)
        }
        if let message = store.actionMessage {
            NoticeBanner(
                icon: "checkmark.circle",
                tint: .green,
                message: message,
                onDismiss: { store.clearActionMessage() }
            )
            .padding(.horizontal, PIHSpacing.page)
            .padding(.top, 12)
        }
    }

    // MARK: - Ranking strip

    @ViewBuilder
    private var rankingStrip: some View {
        HStack(spacing: PIHSpacing.control) {
            HStack(spacing: 6) {
                Image(systemName: "trophy")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
                Text("榜单")
                    .font(PIHFont.captionMedium)
                    .foregroundStyle(.secondary)
            }
            Picker("榜单", selection: $store.rankingKind) {
                Text("重要").tag("importance")
                Text("最新").tag("recent")
                Text("热度上升").tag("heat")
                Text("持续发展").tag("emerging")
                Text("高置信").tag("confidence")
            }
            .labelsHidden()
            .frame(width: 110)

            if store.rankings.isEmpty {
                Text("暂无排行数据")
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(store.rankings.prefix(10)) { item in
                            rankingChip(item)
                        }
                    }
                }
                Text("前 \(store.rankings.count)/\(store.rankingTotal)")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                    .fixedSize()
            }
        }
        .padding(.horizontal, PIHSpacing.page)
        .padding(.vertical, 10)
        .background(PIHColor.canvas)
    }

    private func rankingChip(_ item: RankingItemDTO) -> some View {
        Button {
            Task { await store.select(item.event.id) }
        } label: {
            HStack(spacing: 6) {
                Text("#\(item.rank)")
                    .font(PIHFont.meta.weight(.semibold))
                    .foregroundStyle(Color.accentColor)
                Text(item.event.title)
                    .font(PIHFont.meta)
                    .lineLimit(1)
                Text(String(format: "%.1f", item.score))
                    .font(PIHFont.meta)
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(PIHColor.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(PIHColor.hairline, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .help(item.event.title)
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        if !store.hasLoaded && store.isLoading {
            LoadingStateView(message: "正在读取事件数据…")
        } else if !store.hasLoaded {
            EmptyPanel(
                icon: "rectangle.3.group",
                title: "无法读取事件",
                message: store.errorMessage ?? "Sidecar 未就绪。",
                actionTitle: "重试",
                action: { Task { await store.reload() } }
            )
        } else {
            HSplitView {
                eventList
                    .frame(minWidth: 320, idealWidth: 380, maxWidth: 460)
                detailPane
                    .frame(minWidth: 520)
            }
        }
    }

    private var eventList: some View {
        VStack(spacing: 0) {
            if store.events.isEmpty {
                EmptyPanel(
                    icon: "sparkles.rectangle.stack",
                    title: "还没有事件",
                    message: "运行聚类任务后，相关文章会被组织成事件。",
                    actionTitle: "运行增量聚类",
                    action: {
                        Task { await store.runClustering(scope: "incremental", limit: 200, useLLM: false) }
                    }
                )
            } else {
                ScrollView {
                    LazyVStack(spacing: 4) {
                        ForEach(store.events) { event in
                            eventRow(event)
                                .task { await store.loadMoreIfNeeded(current: event.id) }
                        }
                        if store.isLoadingMore {
                            ProgressView().controlSize(.small).padding(10)
                        }
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)
                }
                Divider().overlay(PIHColor.hairline)
                HStack {
                    Text("共 \(store.total) 个事件，已加载 \(store.events.count)")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                    Spacer()
                    if store.hasMore {
                        Button("加载更多") { Task { await store.loadMore() } }
                            .buttonStyle(.link)
                            .font(PIHFont.caption)
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
            }
        }
        .background(PIHColor.canvas)
    }

    private func eventRow(_ event: EventSummaryDTO) -> some View {
        Button {
            Task { await store.select(event.id) }
        } label: {
            VStack(alignment: .leading, spacing: 7) {
                HStack(alignment: .top, spacing: 6) {
                    Text(event.title)
                        .font(PIHFont.bodySemibold)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 4)
                    StatusPill(text: eventStatusLabel(event.status), tint: eventStatusTint(event.status))
                }
                HStack(spacing: 12) {
                    Label("\(event.articleCount) 篇", systemImage: "doc.text")
                    Label("\(event.sourceCount) 源", systemImage: "antenna.radiowaves.left.and.right")
                    if let scores = event.currentScores {
                        Label(String(format: "综合 %.0f", scores.totalScore), systemImage: "chart.bar")
                    }
                    if event.isManual {
                        Text("人工")
                            .foregroundStyle(.purple)
                    }
                    Spacer(minLength: 0)
                }
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
                HStack(spacing: 8) {
                    Text(event.category)
                    Text("更新 \(displayTimestamp(event.lastPublishedAt ?? event.lastSeenAt))")
                    Spacer()
                }
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 11)
            .pihRowBackground(isSelected: store.selectedEventID == event.id)
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "\(event.title)，状态 \(eventStatusLabel(event.status))，\(event.articleCount) 篇文章，\(event.sourceCount) 个来源"
        )
    }

    // MARK: - Detail pane

    @ViewBuilder
    private var detailPane: some View {
        if let event = store.selectedEvent {
            ScrollView {
                VStack(alignment: .leading, spacing: PIHSpacing.cardGap) {
                    overviewCard(event)
                    scoreSection(event)
                    timelineSection(event)
                    articlesSection(event)
                    entitiesSection
                    relationsSection(event)
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 22)
            }
            .overlay(alignment: .topTrailing) {
                if store.isLoadingDetail {
                    ProgressView().controlSize(.small).padding(14)
                }
            }
            .background(PIHColor.canvas)
        } else if store.isLoadingDetail {
            LoadingStateView(message: "正在读取事件详情…")
        } else {
            EmptyPanel(
                icon: "sidebar.left",
                title: "选择一个事件",
                message: "左侧事件列表展示真实聚类结果；选择后查看时间线、文章、实体、关联与评分解释。",
                actionTitle: nil,
                action: nil
            )
        }
    }

    private func overviewCard(_ event: EventDetailDTO) -> some View {
        card {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 10) {
                    Text(event.title)
                        .font(.system(size: 24, weight: .semibold))
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 6) {
                        StatusPill(text: eventStatusLabel(event.status), tint: eventStatusTint(event.status))
                        StatusPill(text: event.category, tint: .blue)
                        if event.isManual {
                            StatusPill(text: "人工维护", tint: .purple)
                        }
                        if let reason = event.statusReason {
                            Text(reason)
                                .font(PIHFont.meta)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                Spacer()
                Menu {
                    Button("重命名…") {
                        renameText = event.title
                        showRename = true
                    }
                    Button("修改状态…") {
                        newStatus = event.status == "merged" ? "active" : event.status
                        statusReason = event.statusReason ?? ""
                        showStatusEditor = true
                    }
                    Button("合并到其他事件…") {
                        mergeTarget = ""
                        mergeReason = ""
                        showMerge = true
                    }
                    Button("拆分选中文章…") {
                        splitSelection = []
                        splitTitle = ""
                        showSplit = true
                    }
                    Button("添加文章…") {
                        showAddArticle = true
                        Task { await store.loadPickerArticles() }
                    }
                    if event.status == "merged" {
                        Divider()
                        Button("撤销合并…") { showUnmergeConfirm = true }
                    }
                } label: {
                    Label("校正", systemImage: "slider.horizontal.3")
                        .font(PIHFont.caption)
                }
                .pihToolbarMenu()
                .disabled(store.isBusy)
            }

            if let summary = event.summary, !summary.isEmpty {
                Text(summary)
                    .font(PIHFont.body)
                    .foregroundStyle(.secondary)
                    .lineSpacing(4)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Grid(alignment: .leading, horizontalSpacing: 28, verticalSpacing: 10) {
                GridRow {
                    metric("首次发现", displayTimestamp(event.firstSeenAt))
                    metric("最近更新", displayTimestamp(event.lastSeenAt))
                    metric("文章 / 来源", "\(event.articleCount) / \(event.sourceCount)")
                }
                GridRow {
                    metric("首次发布", displayTimestamp(event.firstPublishedAt))
                    metric("最新发布", displayTimestamp(event.lastPublishedAt))
                    metric("算法版本", event.algorithmVersion)
                }
            }

            if let occurred = event.occurredAt {
                Text("事件发生时间：\(displayTimestamp(occurred))（有明确证据）")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            } else {
                Text("事件发生时间：未确认（不以文章发布时间代替）")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func metric(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
            Text(value)
                .font(PIHFont.caption)
                .foregroundStyle(.primary)
        }
    }

    // MARK: - Scores

    private func scoreSection(_ event: EventDetailDTO) -> some View {
        card {
            CardHeader("评分解释", icon: "gauge") {
                if let scores = event.currentScores {
                    HStack(spacing: 8) {
                        Text(scores.algorithmVersion)
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                        Text(String(format: "综合 %.1f", scores.totalScore))
                            .font(PIHFont.bodySemibold)
                    }
                }
            }
            if let snapshot = store.scores.first(where: { $0.isCurrent }) {
                scoreContent(snapshot)
            } else if let summary = event.currentScores {
                Text("当前快照：重要性 \(summary.importanceScore, specifier: "%.1f") · 热度 \(summary.heatScore, specifier: "%.1f") · 时效 \(summary.freshnessScore, specifier: "%.1f") · 覆盖 \(summary.coverageScore, specifier: "%.1f") · 置信 \(summary.confidenceScore, specifier: "%.1f")")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text("尚未计算评分。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func scoreContent(_ snapshot: EventScoreSnapshotDTO) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            ScoreBar(label: "重要性", value: snapshot.importanceScore, tint: .red)
            ScoreBar(label: "热度", value: snapshot.heatScore, tint: .orange)
            ScoreBar(label: "时效性", value: snapshot.freshnessScore, tint: .blue)
            ScoreBar(label: "覆盖程度", value: snapshot.coverageScore, tint: .green)
            ScoreBar(label: "置信度", value: snapshot.confidenceScore, tint: .purple)

            Text(snapshot.explanation.formula)
                .font(PIHFont.metaMono)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
            ForEach(snapshot.explanation.components, id: \.name) { component in
                Text("· \(component.name)：\(component.reason)")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            let inputs = snapshot.inputs
            Text("参与计算：\(intValue(inputs["article_count"])) 篇 / 去重内容 \(intValue(inputs["unique_content_count"])) / 独立来源 \(intValue(inputs["unique_source_count"])) / 近 72h \(intValue(inputs["recent_72h_articles"]))")
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
            Text("来源主观权重 credibility_score 不参与客观事件评分。")
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
        }
    }

    // MARK: - Timeline

    private func timelineSection(_ event: EventDetailDTO) -> some View {
        card {
            CardHeader("事件时间线", icon: "timeline.selection") {
                Text("\(store.timeline.count) 个节点")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            if store.timeline.isEmpty {
                Text("暂无时间线节点。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            } else {
                let visible = showAllTimeline ? store.timeline : Array(store.timeline.prefix(12))
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(visible) { item in
                        HStack(alignment: .top, spacing: 10) {
                            Circle()
                                .fill(item.isKey ? Color.accentColor : Color.secondary.opacity(0.4))
                                .frame(width: 8, height: 8)
                                .padding(.top, 6)
                            VStack(alignment: .leading, spacing: 4) {
                                HStack(spacing: 6) {
                                    Text(item.title)
                                        .font(PIHFont.bodyMedium)
                                        .fontWeight(item.isKey ? .semibold : .regular)
                                    StatusPill(text: eventTimelineKindLabel(item.kind), tint: item.isKey ? .accentColor : .secondary)
                                }
                                if let description = item.description, !description.isEmpty {
                                    Text(description)
                                        .font(PIHFont.caption)
                                        .foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                HStack(spacing: 10) {
                                    if let occurred = item.occurredAt {
                                        Text("发生 \(displayTimestamp(occurred))")
                                    } else if let published = item.publishedAt {
                                        Text("发布 \(displayTimestamp(published))")
                                    } else {
                                        Text("识别 \(displayTimestamp(item.recognizedAt))")
                                    }
                                    if let title = item.articleTitle {
                                        Text("来源：\(title)").lineLimit(1)
                                    }
                                }
                                .font(PIHFont.meta)
                                .foregroundStyle(.tertiary)
                            }
                            Spacer()
                        }
                    }
                }
                if store.timeline.count > 12 {
                    Button(showAllTimeline ? "收起" : "展开全部 \(store.timeline.count) 个节点") {
                        showAllTimeline.toggle()
                    }
                    .buttonStyle(.link)
                    .font(PIHFont.caption)
                }
            }
        }
    }

    // MARK: - Articles

    private func articlesSection(_ event: EventDetailDTO) -> some View {
        card {
            CardHeader("关联文章", icon: "doc.on.doc") {
                Text("\(store.detailArticles.count) 篇")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            if store.detailArticles.isEmpty {
                Text("暂无关联文章。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(store.detailArticles) { article in
                        VStack(alignment: .leading, spacing: 5) {
                            Text(article.title)
                                .font(PIHFont.bodyMedium)
                                .lineLimit(2)
                                .fixedSize(horizontal: false, vertical: true)
                            HStack(spacing: 8) {
                                Text(article.sourceName ?? "未知来源")
                                Text(displayTimestamp(article.publishedAt))
                                StatusPill(text: eventArticleRoleLabel(article.role), tint: .secondary)
                            }
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                            if let aiSummary = article.aiSummary ?? article.summary, !aiSummary.isEmpty {
                                Text(aiSummary)
                                    .font(PIHFont.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(3)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            HStack(spacing: 12) {
                                if let urlString = article.canonicalUrl ?? article.originalUrl,
                                   let url = URL(string: urlString) {
                                    Link("打开原文", destination: url)
                                        .font(PIHFont.meta)
                                }
                                Button("从事件移出") { pendingRemove = article }
                                    .buttonStyle(.link)
                                    .font(PIHFont.meta)
                            }
                        }
                    }
                }
            }
        }
    }

    // MARK: - Entities

    private var entitiesSection: some View {
        card {
            CardHeader("相关实体", icon: "tag") {
                Text("\(store.detailEntities.count) 个")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            if store.detailEntities.isEmpty {
                Text("暂无实体。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 9) {
                    ForEach(store.detailEntities) { entity in
                        HStack(spacing: 8) {
                            StatusPill(
                                text: eventEntityTypeLabel(entity.entityType),
                                tint: entityTypeTint(entity.entityType)
                            )
                            Text(entity.canonicalName)
                                .font(PIHFont.body)
                            Text(eventEntityRoleLabel(entity.role))
                                .font(PIHFont.meta)
                                .foregroundStyle(.secondary)
                            Text("\(entity.articleCount) 篇")
                                .font(PIHFont.meta)
                                .foregroundStyle(.tertiary)
                            Spacer()
                        }
                    }
                }
            }
        }
    }

    // MARK: - Relations

    private func relationsSection(_ event: EventDetailDTO) -> some View {
        card {
            CardHeader("相关事件", icon: "arrow.triangle.branch") {
                Text("\(store.detailRelations.count) 条")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            if store.detailRelations.isEmpty {
                Text("暂无事件关联。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(store.detailRelations) { relation in
                        let otherTitle = relation.sourceEventId == event.id
                            ? relation.targetEventTitle : relation.sourceEventTitle
                        VStack(alignment: .leading, spacing: 5) {
                            HStack(spacing: 6) {
                                StatusPill(text: eventRelationLabel(relation.relationType), tint: .teal)
                                Text(otherTitle ?? "未知事件")
                                    .font(PIHFont.body)
                                    .lineLimit(2)
                                Spacer()
                                Text(String(format: "%.0f%%", relation.confidence * 100))
                                    .font(PIHFont.meta)
                                    .foregroundStyle(.secondary)
                                if relation.status == "candidate" {
                                    Button("确认") {
                                        Task { await store.setRelationStatus(relation, status: "confirmed") }
                                    }
                                    .buttonStyle(.link)
                                    .font(PIHFont.meta)
                                    Button("忽略") {
                                        Task { await store.setRelationStatus(relation, status: "rejected") }
                                    }
                                    .buttonStyle(.link)
                                    .font(PIHFont.meta)
                                } else {
                                    StatusPill(
                                        text: relation.status == "confirmed" ? "已确认" : (relation.status == "rejected" ? "已忽略" : "候选"),
                                        tint: relation.status == "confirmed" ? .green : .secondary
                                    )
                                }
                            }
                            if let rationale = relation.rationale, !rationale.isEmpty {
                                Text(rationale)
                                    .font(PIHFont.meta)
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            Text("证据 \(relation.evidenceArticles.count) 篇 · \(relation.actor == "manual" ? "人工" : relation.algorithmVersion)")
                                .font(PIHFont.meta)
                                .foregroundStyle(.tertiary)
                        }
                    }
                }
            }
        }
    }

    // MARK: - Sheets

    private var renameSheet: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("重命名事件")
                .font(PIHFont.subsectionTitle)
            TextField("事件标题", text: $renameText)
                .textFieldStyle(.roundedBorder)
            HStack {
                Spacer()
                Button("取消") { showRename = false }
                Button("保存") {
                    showRename = false
                    Task { await store.rename(renameText) }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(renameText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(22)
        .frame(width: 460)
    }

    private var statusSheet: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("修改事件状态")
                .font(PIHFont.subsectionTitle)
            Picker("状态", selection: $newStatus) {
                Text("活跃").tag("active")
                Text("休眠").tag("dormant")
                Text("已结束").tag("closed")
                Text("已归档").tag("archived")
            }
            Text("发展中（evolving）由聚类自动推进，人工只能设置活跃/休眠/已结束/已归档。")
                .font(PIHFont.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            TextField("状态说明（写入审计）", text: $statusReason)
                .textFieldStyle(.roundedBorder)
            HStack {
                Spacer()
                Button("取消") { showStatusEditor = false }
                Button("保存") {
                    let status = newStatus
                    let reason = statusReason
                    showStatusEditor = false
                    Task { await store.changeStatus(status, reason: reason) }
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(22)
        .frame(width: 460)
    }

    private var mergeSheet: some View {
        let candidates = store.events.filter {
            $0.id != store.selectedEventID && $0.status != "merged"
        }
        return VStack(alignment: .leading, spacing: 14) {
            Text("合并到其他事件")
                .font(PIHFont.subsectionTitle)
            Text("合并后本事件变为已合并状态，可随时撤销。")
                .font(PIHFont.caption)
                .foregroundStyle(.secondary)
            if candidates.isEmpty {
                Text("没有可合并的目标事件。")
                    .font(PIHFont.body)
                    .foregroundStyle(.secondary)
            } else {
                Picker("目标事件", selection: $mergeTarget) {
                    Text("请选择").tag("")
                    ForEach(candidates) { event in
                        Text("\(event.title) · \(event.articleCount) 篇").tag(event.id)
                    }
                }
            }
            TextField("合并原因（可选）", text: $mergeReason)
                .textFieldStyle(.roundedBorder)
            HStack {
                Spacer()
                Button("取消") { showMerge = false }
                Button("合并") {
                    let target = mergeTarget
                    let reason = mergeReason.isEmpty ? nil : mergeReason
                    showMerge = false
                    Task { await store.merge(into: target, reason: reason) }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(mergeTarget.isEmpty)
            }
        }
        .padding(22)
        .frame(width: 500)
    }

    private var splitSheet: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("拆分选中文章")
                .font(PIHFont.subsectionTitle)
            Text("选中的文章会组成一个新的独立事件；源事件至少保留一篇。")
                .font(PIHFont.caption)
                .foregroundStyle(.secondary)
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(store.detailArticles) { article in
                        Toggle(isOn: Binding(
                            get: { splitSelection.contains(article.articleId) },
                            set: { selected in
                                if selected {
                                    splitSelection.insert(article.articleId)
                                } else {
                                    splitSelection.remove(article.articleId)
                                }
                            }
                        )) {
                            Text(article.title)
                                .font(PIHFont.body)
                                .lineLimit(2)
                        }
                    }
                }
            }
            .frame(maxHeight: 260)
            TextField("新事件标题（可选）", text: $splitTitle)
                .textFieldStyle(.roundedBorder)
            HStack {
                Spacer()
                Text("已选 \(splitSelection.count) 篇")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
                Button("取消") { showSplit = false }
                Button("拆分") {
                    let ids = Array(splitSelection)
                    let title = splitTitle.trimmingCharacters(in: .whitespacesAndNewlines)
                    showSplit = false
                    Task { await store.split(articleIDs: ids, title: title.isEmpty ? nil : title) }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(splitSelection.isEmpty || splitSelection.count >= store.detailArticles.count)
            }
        }
        .padding(22)
        .frame(width: 540)
    }

    private var addArticleSheet: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("添加文章到事件")
                .font(PIHFont.subsectionTitle)
            Text("仅显示最近 50 篇未属于本事件的文章。")
                .font(PIHFont.caption)
                .foregroundStyle(.secondary)
            if store.pickerArticles.isEmpty {
                Text("没有可添加的文章。")
                    .font(PIHFont.body)
                    .foregroundStyle(.secondary)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(store.pickerArticles) { article in
                            HStack {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(article.title)
                                        .font(PIHFont.body)
                                        .lineLimit(2)
                                    Text("\(article.sourceName ?? "未知来源") · \(displayTimestamp(article.publishedAt))")
                                        .font(PIHFont.meta)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button("加入") {
                                    showAddArticle = false
                                    Task { await store.addArticle(article.id, role: "follow_up") }
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                    }
                }
                .frame(maxHeight: 320)
            }
            HStack {
                Spacer()
                Button("关闭") { showAddArticle = false }
            }
        }
        .padding(22)
        .frame(width: 580)
    }

    // MARK: - Building blocks

    private func card<Content: View>(@ViewBuilder content: @escaping () -> Content) -> some View {
        PIHCard(padding: 18, spacing: 12, content: content)
    }

    private func intValue(_ value: AIJSONValue?) -> String {
        switch value {
        case .integer(let number): return String(number)
        case .number(let number): return String(Int(number))
        default: return "—"
        }
    }
}

// MARK: - Helpers

private struct ScoreBar: View {
    let label: String
    let value: Double
    let tint: Color

    var body: some View {
        HStack(spacing: 10) {
            Text(label)
                .font(PIHFont.caption)
                .foregroundStyle(.secondary)
                .frame(width: 62, alignment: .leading)
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule().fill(tint.opacity(0.14))
                    Capsule()
                        .fill(tint)
                        .frame(width: max(3, proxy.size.width * min(max(value, 0), 100) / 100))
                }
            }
            .frame(height: 8)
            Text(String(format: "%.1f", value))
                .font(PIHFont.meta)
                .monospacedDigit()
                .frame(width: 36, alignment: .trailing)
        }
    }
}

private func eventStatusTint(_ raw: String) -> Color {
    switch raw {
    case "candidate": return .secondary
    case "active": return .green
    case "evolving": return .blue
    case "dormant": return .orange
    case "closed": return .gray
    case "merged": return .purple
    case "archived": return .secondary
    default: return .secondary
    }
}

private func entityTypeTint(_ raw: String) -> Color {
    switch raw {
    case "person": return .blue
    case "organization", "company": return .orange
    case "location": return .green
    case "product": return .teal
    case "event": return .purple
    default: return .secondary
    }
}
