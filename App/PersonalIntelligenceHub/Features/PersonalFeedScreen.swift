import SwiftUI

/// Phase 7.3.2 「为我筛选」：编辑式个人情报工作台。
///
/// 页面结构（从高到低）：
/// 1. 页面头部：标题、真实推荐状态、刷新 / 今日精选 / 兴趣画像。
/// 2. 今日导语 + 兴趣主题导航 + 阅读预算入口。
/// 3. 紧凑概览：今日精选、今日必读、预计阅读；采集总量放在次级信息。
/// 4. 今日必读主推荐（无达标内容时给出克制的空状态）。
/// 5. 为你推荐、事件动态、新兴主题、独立新闻线索、折叠的低优先级信息。
///
/// 所有排序、分数、数量与理由都来自 `/api/v1/personalization/feed`；
/// 兴趣筛选仅是客户端对 `matched_interests` 的过滤，不改变后端排序。
struct PersonalFeedScreen: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var store: PersonalizationStore
    let onOpenArticle: (String) -> Void
    let onOpenEvent: (String) -> Void

    @State private var showProfile = false
    @State private var showDigest = false
    @State private var expandedSections: Set<String> = []
    @State private var selectedInterest: String?

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider().overlay(PIHColor.hairline)
            content
        }
        .frame(minWidth: 720, minHeight: 520)
        .background(PIHColor.canvas)
        .task(id: model.state) { await store.loadIfNeeded() }
        .sheet(isPresented: $showProfile) {
            InterestProfileSheet(store: store)
        }
        .sheet(isPresented: $showDigest) {
            DailyDigestSheet(
                store: store,
                onOpenArticle: onOpenArticle,
                onOpenEvent: onOpenEvent
            )
        }
    }

    // MARK: - Toolbar

    private var toolbar: some View {
        PIHPageToolbar {
            HStack(spacing: PIHSpacing.control) {
                PageHeader("为我筛选", subtitle: "PERSONAL INTELLIGENCE FEED")
                Spacer(minLength: 12)

                if let status = statusPill {
                    StatusPill(text: status.text, tint: status.tint)
                }
                if store.isRefreshing || store.isGeneratingDigest {
                    ProgressView().controlSize(.small)
                }

                ViewThatFits(in: .horizontal) {
                    labelledActions
                    iconActions
                }
            }
        }
    }

    private var labelledActions: some View {
        HStack(spacing: 8) {
            refreshButton(labelled: true)
            digestButton(labelled: true)
            profileButton(labelled: true)
        }
    }

    private var iconActions: some View {
        HStack(spacing: 8) {
            refreshButton(labelled: false)
            digestButton(labelled: false)
            profileButton(labelled: false)
        }
    }

    private func refreshButton(labelled: Bool) -> some View {
        Button {
            Task { await store.refresh() }
        } label: {
            if labelled {
                Label("刷新", systemImage: "arrow.clockwise")
            } else {
                Image(systemName: "arrow.clockwise")
            }
        }
        .disabled(store.isRefreshing || !model.isDataReady)
        .help("重新计算并刷新推荐")
        .accessibilityLabel("刷新推荐")
    }

    private func digestButton(labelled: Bool) -> some View {
        Button {
            showDigest = true
            Task { await store.loadTodayDigest() }
        } label: {
            if labelled {
                Label("今日精选", systemImage: "doc.text.image")
            } else {
                Image(systemName: "doc.text.image")
            }
        }
        .disabled(!model.isDataReady || store.isGeneratingDigest)
        .help("打开每日精选")
        .accessibilityLabel("今日精选")
    }

    private func profileButton(labelled: Bool) -> some View {
        Button {
            showProfile = true
        } label: {
            if labelled {
                Label("兴趣画像", systemImage: "slider.horizontal.3")
            } else {
                Image(systemName: "slider.horizontal.3")
            }
        }
        .buttonStyle(.borderedProminent)
        .disabled(!model.isDataReady)
        .help("管理兴趣画像、阅读预算与屏蔽来源")
        .accessibilityLabel("兴趣画像")
    }

    /// 只展示真实存在的运行状态，不伪造「已更新」。
    private var statusPill: (text: String, tint: Color)? {
        if !model.isDataReady { return ("本地服务未就绪", PIHColor.warning) }
        if store.isRefreshing { return ("正在更新", PIHColor.info) }
        guard let feed = store.feed else { return nil }
        if !feed.hasCoreInterest { return ("待配置核心兴趣", PIHColor.warning) }
        return ("推荐已更新 · \(clock(feed.generatedAt))", PIHColor.positive)
    }

    private func clock(_ value: String) -> String {
        guard let date = PIHDateFormat.date(from: value) else { return "未知时间" }
        return date.formatted(.dateTime.hour().minute())
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        if !model.isDataReady {
            EmptyPanel(
                icon: "bolt.horizontal.circle",
                title: "本地服务未就绪",
                message: "「为我筛选」需要本地 Sidecar 运行。当前状态：\(model.state.title)。",
                actionTitle: "启动 Sidecar",
                action: { model.start() }
            )
        } else if store.isLoading && !store.hasLoaded {
            LoadingStateView(message: "正在计算今日推荐…")
        } else if let error = store.errorMessage, store.feed == nil {
            EmptyPanel(
                icon: "exclamationmark.triangle",
                title: "推荐加载失败",
                message: error,
                actionTitle: "重试",
                action: { Task { await store.load() } }
            )
        } else if let feed = store.feed {
            feedContent(feed)
        } else {
            LoadingStateView(message: "正在连接本地推荐服务…")
        }
    }

    private func feedContent(_ feed: PersonalFeedDTO) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: PIHSpacing.section) {
                    intro(feed)
                    overview(feed)

                    if !feed.hasInterests {
                        onboarding
                    }
                    if let message = store.actionMessage {
                        NoticeBanner(
                            icon: "checkmark.circle",
                            tint: PIHColor.positive,
                            message: message,
                            onDismiss: { store.clearActionMessage() }
                        )
                    }
                    if let error = store.actionErrorMessage {
                        NoticeBanner(
                            icon: "exclamationmark.triangle",
                            tint: PIHColor.warning,
                            message: error,
                            onDismiss: nil
                        )
                    }

                    mustReadSection(feed, proxy: proxy)
                    recommendedSection(feed)
                    eventsSection(feed)
                    emergingSection(feed)
                    leadsSection(feed)

                    if isFilterEmpty(feed) {
                        filterEmptyState
                    }

                    collapsibleSection(
                        id: "watch",
                        title: "观察与低优先级",
                        subtitle: "默认折叠；内容不会被删除",
                        items: collapsedItems(feed, from: feed.sections.watch)
                    )
                    collapsibleSection(
                        id: "others",
                        title: "其他信息",
                        subtitle: "未进入首选的其余推荐结果",
                        items: collapsedItems(feed, from: feed.sections.others)
                    )

                    footer(feed)
                }
                .padding(.horizontal, PIHSpacing.page)
                .padding(.vertical, 24)
                .frame(maxWidth: 1120, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .top)
            }
        }
    }

    // MARK: - Intro & interest navigation

    private func intro(_ feed: PersonalFeedDTO) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text("今天值得关注什么？")
                    .font(.system(size: 22, weight: .semibold))
                Text("根据你的兴趣画像，从真实采集的文章与事件中筛选值得阅读的信息。")
                    .font(PIHFont.body)
                    .foregroundStyle(.secondary)
            }
            interestNavigation(feed)
        }
    }

    private func interestNavigation(_ feed: PersonalFeedDTO) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                let all = allItems(feed)
                InterestChip(
                    title: "全部",
                    count: all.count,
                    isSelected: selectedInterest == nil
                ) {
                    select(nil)
                }
                ForEach(interestNames(feed), id: \.self) { name in
                    InterestChip(
                        title: name,
                        count: all.filter { $0.matchedInterests.contains(name) }.count,
                        isSelected: selectedInterest == name
                    ) {
                        select(name)
                    }
                }
                Button {
                    showProfile = true
                } label: {
                    Label("编辑兴趣", systemImage: "slider.horizontal.3")
                        .font(PIHFont.caption)
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(!model.isDataReady)
                .help("打开兴趣画像管理")
            }
            .padding(.vertical, 1)
        }
    }

    private func interestNames(_ feed: PersonalFeedDTO) -> [String] {
        let order = ["core", "extended", "general"]
        let configured = store.interests
            .filter { $0.enabled && order.contains($0.level) }
            .sorted { lhs, rhs in
                (order.firstIndex(of: lhs.level) ?? 9) < (order.firstIndex(of: rhs.level) ?? 9)
            }
            .map(\.name)
        if !configured.isEmpty { return configured }

        var seen: [String] = []
        for name in allItems(feed).flatMap(\.matchedInterests) where !seen.contains(name) {
            seen.append(name)
        }
        return seen
    }

    private func select(_ name: String?) {
        if reduceMotion {
            selectedInterest = name
        } else {
            withAnimation(.easeInOut(duration: 0.16)) { selectedInterest = name }
        }
    }

    // MARK: - Overview

    private func overview(_ feed: PersonalFeedDTO) -> some View {
        let primary = primaryItems(feed)
        return PIHCard(padding: 16, spacing: 10) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .center, spacing: 18) {
                    metricsRow(feed, primaryCount: primary.count)
                    Spacer(minLength: 8)
                    budgetControl(feed)
                }
                VStack(alignment: .leading, spacing: 12) {
                    metricsRow(feed, primaryCount: primary.count)
                    budgetControl(feed)
                }
            }
            Text(secondaryLine(feed))
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
                .lineLimit(1)
        }
    }

    private func metricsRow(_ feed: PersonalFeedDTO, primaryCount: Int) -> some View {
        HStack(alignment: .center, spacing: 18) {
            overviewMetric(
                "今日精选",
                "\(primaryCount) 条",
                "进入首选的推荐"
            )
            metricDivider
            overviewMetric(
                "今日必读",
                "\(filtered(feed.sections.mustRead).count) 条",
                "达到必读阈值"
            )
            metricDivider
            overviewMetric(
                "预计阅读",
                "\(estimatedMinutes(feed, count: primaryCount)) 分钟",
                feed.budget.dailyMinutes != nil && selectedInterest == nil
                    ? "按你的阅读时长预算"
                    : "按每条约 4 分钟估算"
            )
        }
    }

    private func overviewMetric(_ title: String, _ value: String, _ caption: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.system(size: 20, weight: .semibold))
                .monospacedDigit()
                .lineLimit(1)
            Text(caption)
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
                .lineLimit(1)
        }
    }

    private var metricDivider: some View {
        Rectangle()
            .fill(PIHColor.hairline)
            .frame(width: 1, height: 38)
    }

    private func budgetControl(_ feed: PersonalFeedDTO) -> some View {
        ReadingBudgetControl(
            currentItems: feed.budget.items,
            isExplicit: feed.budget.dailyItemLimit != nil,
            isBusy: store.isRefreshing || store.isGeneratingDigest
        ) { value in
            Task { _ = await store.updateProfile(ProfileUpdatePayload(dailyItemLimit: value)) }
        }
    }

    private func secondaryLine(_ feed: PersonalFeedDTO) -> String {
        let metrics = feed.metrics
        return "今日新增 \(metrics.todayArticles) 篇文章 · 推荐候选 \(metrics.recommendedTotal) 条 · 进入推荐的事件 \(metrics.eventCount) 个 · 独立文章 \(metrics.standaloneCount) 篇"
    }

    private func estimatedMinutes(_ feed: PersonalFeedDTO, count: Int) -> Int {
        if let minutes = feed.budget.dailyMinutes, selectedInterest == nil {
            return minutes
        }
        return count * 4
    }

    // MARK: - Onboarding

    private var onboarding: some View {
        PIHCard {
            HStack(alignment: .top, spacing: 16) {
                Image(systemName: "wand.and.stars")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(.tint)
                    .frame(width: 42, height: 42)
                    .background(Circle().fill(PIHColor.accentSoft))
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 6) {
                    Text("先建立你的兴趣画像")
                        .font(PIHFont.sectionTitle)
                    Text("添加 1–3 个核心关注（例如人工智能、半导体、储能），再补充关键词和关注实体。系统会用真实文章与事件计算推荐，并在每条结果旁给出理由。")
                        .font(PIHFont.body)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                VStack(spacing: 8) {
                    Button("配置兴趣画像") { showProfile = true }
                        .buttonStyle(.borderedProminent)
                    Button("稍后再说") {
                        Task { await store.completeOnboarding() }
                    }
                    .buttonStyle(.plain)
                    .font(PIHFont.caption)
                }
            }
        }
    }

    // MARK: - Sections

    private func mustReadSection(
        _ feed: PersonalFeedDTO, proxy: ScrollViewProxy
    ) -> some View {
        let items = filtered(feed.sections.mustRead)
        return VStack(alignment: .leading, spacing: 12) {
            SectionHeader("今日必读", subtitle: "达到必读阈值的内容；分数只是推荐优先级")
            if let first = items.first {
                featuredCard(first)
                ForEach(items.dropFirst()) { item in
                    row(item)
                }
            } else {
                mustReadEmpty(feed, proxy: proxy)
            }
        }
        .id("must-read")
    }

    private func mustReadEmpty(
        _ feed: PersonalFeedDTO, proxy: ScrollViewProxy
    ) -> some View {
        PIHCard {
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: "checkmark.seal")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(PIHColor.positive)
                    .frame(width: 38, height: 38)
                    .background(Circle().fill(PIHColor.positive.opacity(0.10)))
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 6) {
                    Text(
                        selectedInterest.map { "「\($0)」下暂时没有达到必读标准的内容。" }
                            ?? "今天暂时没有达到必读标准的内容。"
                    )
                    .font(PIHFont.subsectionTitle)
                    Text("可以浏览其他推荐，或调整兴趣偏好，让系统更了解你关注的方向。")
                        .font(PIHFont.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 8) {
                        Button("浏览推荐") {
                            proxy.scrollTo("recommended", anchor: .top)
                        }
                        .disabled(filtered(feed.sections.coreInterest).isEmpty)
                        Button("调整兴趣偏好") { showProfile = true }
                        if !filtered(feed.sections.eventHighlights).isEmpty {
                            Button("查看重点事件") {
                                proxy.scrollTo("events", anchor: .top)
                            }
                        }
                        Button("查看今日精选") {
                            showDigest = true
                            Task { await store.loadTodayDigest() }
                        }
                    }
                    .controlSize(.small)
                }
                Spacer(minLength: 0)
            }
        }
    }

    @ViewBuilder
    private func recommendedSection(_ feed: PersonalFeedDTO) -> some View {
        let items = filtered(feed.sections.coreInterest)
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader("为你推荐", subtitle: "命中核心兴趣的更新")
                ForEach(items) { item in
                    row(item)
                }
            }
            .id("recommended")
        } else {
            Color.clear.frame(height: 0).id("recommended")
        }
    }

    @ViewBuilder
    private func eventsSection(_ feed: PersonalFeedDTO) -> some View {
        let items = filtered(feed.sections.eventHighlights)
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader(
                    "事件动态",
                    subtitle: "多篇报道聚合的事件；独立来源数只统计可确认的来源"
                )
                ForEach(items) { item in
                    eventCard(item)
                }
            }
            .id("events")
        }
    }

    @ViewBuilder
    private func emergingSection(_ feed: PersonalFeedDTO) -> some View {
        let topics = feed.sections.emerging
        if selectedInterest == nil && !topics.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader(
                    "新兴主题",
                    subtitle: "来自真实文章关键词的环比变化；不是凭单日数量臆测的趋势"
                )
                PIHCard {
                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 220), spacing: 10)],
                        spacing: 10
                    ) {
                        ForEach(topics) { topic in
                            VStack(alignment: .leading, spacing: 4) {
                                HStack(spacing: 6) {
                                    Text(topic.title)
                                        .font(PIHFont.bodyMedium)
                                        .lineLimit(1)
                                    Spacer(minLength: 0)
                                    if topic.delta > 0 {
                                        Text("+\(topic.delta)")
                                            .font(PIHFont.meta)
                                            .foregroundStyle(PIHColor.warning)
                                    }
                                }
                                Text("今日 \(topic.count) 次 · 此前 \(topic.previous) 次")
                                    .font(PIHFont.meta)
                                    .foregroundStyle(.secondary)
                                if !topic.sources.isEmpty {
                                    Text(topic.sources.prefix(3).joined(separator: " / "))
                                        .font(PIHFont.meta)
                                        .foregroundStyle(.tertiary)
                                        .lineLimit(1)
                                }
                            }
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(RoundedRectangle(cornerRadius: PIHRadius.row).fill(PIHColor.accentSoft))
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func leadsSection(_ feed: PersonalFeedDTO) -> some View {
        let items = leadItems(feed)
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader(
                    "独立新闻线索",
                    subtitle: "尚未形成事件、但有独立阅读价值的单篇文章"
                )
                ForEach(items) { item in
                    leadCard(item)
                }
            }
        }
    }

    /// 后端 `leads` 为空时（通常是被阅读预算挤入观察区），从观察/其他区
    /// 提升真实的高分文章作为独立线索；仅按已有的 targetType / eventId /
    /// score 重新分组，不改变分数或推荐等级。被提升的条目不再在折叠区重复出现。
    private func leadItems(_ feed: PersonalFeedDTO) -> [FeedItemDTO] {
        let explicit = filtered(feed.sections.leads)
        if !explicit.isEmpty { return explicit }

        let candidates = filtered(feed.sections.watch) + filtered(feed.sections.others)
        var seen = Set<String>()
        var picked: [FeedItemDTO] = []
        for item in candidates.sorted(by: { $0.score > $1.score }) {
            guard item.targetType == "article",
                  item.eventId == nil,
                  item.score >= 50,
                  seen.insert(item.id).inserted else { continue }
            picked.append(item)
            if picked.count == 6 { break }
        }
        return picked
    }

    private func collapsedItems(_ feed: PersonalFeedDTO, from items: [FeedItemDTO]) -> [FeedItemDTO] {
        let promoted = Set(leadItems(feed).map(\.id))
        return filtered(items).filter { !promoted.contains($0.id) }
    }

    @ViewBuilder
    private func collapsibleSection(
        id: String, title: String, subtitle: String, items: [FeedItemDTO]
    ) -> some View {
        if !items.isEmpty {
            let expanded = expandedSections.contains(id)
            VStack(alignment: .leading, spacing: 12) {
                Button {
                    toggle(id)
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: expanded ? "chevron.down" : "chevron.right")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(.secondary)
                            .accessibilityHidden(true)
                        Text(title).font(PIHFont.sectionTitle)
                        Text("\(items.count)")
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                        Spacer(minLength: 0)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("\(title)，\(items.count) 条，\(expanded ? "已展开" : "已折叠")")

                Text(subtitle)
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)

                if expanded {
                    ForEach(items) { item in
                        row(item)
                    }
                }
            }
        }
    }

    private func toggle(_ id: String) {
        if reduceMotion {
            if expandedSections.contains(id) {
                expandedSections.remove(id)
            } else {
                expandedSections.insert(id)
            }
        } else {
            withAnimation(.easeInOut(duration: 0.16)) {
                if expandedSections.contains(id) {
                    expandedSections.remove(id)
                } else {
                    expandedSections.insert(id)
                }
            }
        }
    }

    private var filterEmptyState: some View {
        PIHCard {
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: "line.3.horizontal.decrease.circle")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 6) {
                    Text("「\(selectedInterest ?? "")」下暂无推荐")
                        .font(PIHFont.subsectionTitle)
                    Text("该兴趣当前没有达到推荐阈值的内容。可以清除筛选查看全部推荐，或调整兴趣关键词。")
                        .font(PIHFont.caption)
                        .foregroundStyle(.secondary)
                    HStack(spacing: 8) {
                        Button("查看全部") { select(nil) }
                        Button("调整兴趣偏好") { showProfile = true }
                    }
                    .controlSize(.small)
                }
                Spacer(minLength: 0)
            }
        }
    }

    private func footer(_ feed: PersonalFeedDTO) -> some View {
        HStack(spacing: 10) {
            Text("算法 \(feed.algorithmVersion)")
            Text("·")
            Text("生成于 \(PIHDateFormat.display(feed.generatedAt, empty: "未知"))")
            if let limit = feed.budget.dailyItemLimit {
                Text("· 每日 \(limit) 条")
            }
            if let minutes = feed.budget.dailyMinutes {
                Text("· 每日 \(minutes) 分钟")
            }
            Spacer(minLength: 0)
            Text("分数代表推荐优先级，不代表事实真实性")
        }
        .font(PIHFont.meta)
        .foregroundStyle(.tertiary)
        .padding(.top, 4)
    }

    // MARK: - Cards

    private func featuredCard(_ item: FeedItemDTO) -> some View {
        FeaturedRecommendationCard(
            item: item,
            activeFeedback: feedback(item),
            isSubmitting: isSubmitting(item),
            onOpen: { open(item) },
            onLater: { markLater(item) },
            onFeedback: { value in submit(item, value) },
            onRevoke: { revoke(item) }
        )
    }

    private func row(_ item: FeedItemDTO) -> some View {
        RecommendationRow(
            item: item,
            activeFeedback: feedback(item),
            isSubmitting: isSubmitting(item),
            onOpen: { open(item) },
            onLater: { markLater(item) },
            onFeedback: { value in submit(item, value) },
            onRevoke: { revoke(item) }
        )
    }

    private func eventCard(_ item: FeedItemDTO) -> some View {
        EventRecommendationCard(
            item: item,
            activeFeedback: feedback(item),
            isSubmitting: isSubmitting(item),
            onOpen: { open(item) },
            onLater: { markLater(item) },
            onFeedback: { value in submit(item, value) },
            onRevoke: { revoke(item) }
        )
    }

    private func leadCard(_ item: FeedItemDTO) -> some View {
        ArticleLeadCard(
            item: item,
            activeFeedback: feedback(item),
            isSubmitting: isSubmitting(item),
            onOpen: { open(item) },
            onLater: { markLater(item) },
            onFeedback: { value in submit(item, value) },
            onRevoke: { revoke(item) }
        )
    }

    // MARK: - Actions

    private func feedback(_ item: FeedItemDTO) -> String? {
        store.feedbackByTarget["\(item.targetType):\(item.targetId)"]
    }

    private func isSubmitting(_ item: FeedItemDTO) -> Bool {
        store.pendingFeedbackTarget == "\(item.targetType):\(item.targetId)"
    }

    private func submit(_ item: FeedItemDTO, _ value: String) {
        Task {
            await store.submitFeedback(
                targetType: item.targetType,
                targetId: item.targetId,
                feedback: value
            )
        }
    }

    private func revoke(_ item: FeedItemDTO) {
        Task {
            await store.revokeFeedback(
                targetType: item.targetType,
                targetId: item.targetId
            )
        }
    }

    private func markLater(_ item: FeedItemDTO) {
        guard item.targetType == "article" else { return }
        Task { await store.markArticleLater(targetId: item.targetId) }
    }

    private func open(_ item: FeedItemDTO) {
        switch item.targetType {
        case "event":
            onOpenEvent(item.targetId)
        default:
            onOpenArticle(item.targetId)
        }
    }

    // MARK: - Derived data (real values only)

    private func allItems(_ feed: PersonalFeedDTO) -> [FeedItemDTO] {
        let sections = feed.sections
        return sections.mustRead
            + sections.eventHighlights
            + sections.coreInterest
            + sections.leads
            + sections.watch
            + sections.others
    }

    private func filtered(_ items: [FeedItemDTO]) -> [FeedItemDTO] {
        guard let selectedInterest else { return items }
        return items.filter { $0.matchedInterests.contains(selectedInterest) }
    }

    private func primaryItems(_ feed: PersonalFeedDTO) -> [FeedItemDTO] {
        let sections = feed.sections
        var seen = Set<String>()
        var result: [FeedItemDTO] = []
        for item in filtered(sections.mustRead)
            + filtered(sections.eventHighlights)
            + filtered(sections.coreInterest)
            + filtered(sections.leads) {
            if seen.insert(item.id).inserted {
                result.append(item)
            }
        }
        return result
    }

    private func isFilterEmpty(_ feed: PersonalFeedDTO) -> Bool {
        guard selectedInterest != nil else { return false }
        return primaryItems(feed).isEmpty
            && leadItems(feed).isEmpty
            && filtered(feed.sections.watch).isEmpty
            && filtered(feed.sections.others).isEmpty
    }
}

// MARK: - Copy helpers

enum PersonalizationCopy {
    static func reason(_ code: String) -> String? {
        switch code {
        case "CORE_INTEREST_MATCH": return "命中核心兴趣"
        case "INTEREST_MATCH": return "匹配关注主题"
        case "MULTI_INTEREST_MATCH": return "同时匹配多个兴趣"
        case "TRACKED_ENTITY": return "涉及你关注的实体"
        case "TRUSTED_SOURCE_HABIT": return "来自你关注的信息源"
        case "HIGH_EVENT_IMPORTANCE": return "事件整体重要性较高"
        case "NEW_INFORMATION": return "包含较新的信息"
        case "FRESH": return "刚刚发布"
        case "TRUSTED_SOURCE": return "来源可靠性评分较高"
        case "MAJOR_EVENT_FALLBACK": return "重大事件兜底（不完全依赖兴趣）"
        case "MAJOR_EVENT": return "重要事件"
        case "FEEDBACK_INTERESTED": return "你标记过感兴趣"
        case "FEEDBACK_IMPORTANT": return "你标记过非常重要"
        case "FEEDBACK_NOT_INTERESTED": return "你标记过不感兴趣"
        case "FEEDBACK_SOURCE_DISLIKED": return "你不喜欢该来源"
        case "FEEDBACK_DUPLICATE": return "你标记过重复内容"
        case "FEEDBACK_LATER": return "你标记了稍后处理"
        default: return nil
        }
    }

    static func reasonText(_ item: FeedItemDTO) -> String {
        let mapped = item.reasonCodes.compactMap(reason)
        if mapped.isEmpty {
            return "推荐理由：由兴趣匹配、事件重要性、新颖性、来源与时效综合计算。"
        }
        return "推荐理由：" + mapped.prefix(4).joined(separator: "；")
    }

    static func warning(_ code: String) -> String? {
        switch code {
        case "EVENT_IMPORTANCE_UNKNOWN": return "重要性未知，按中性 50 分处理"
        case "SOURCE_QUALITY_UNKNOWN": return "来源质量未评估，按中性 50 分处理"
        case "NO_INTERESTS_CONFIGURED": return "尚未配置兴趣，按中性匹配处理"
        case "KEYWORD_ONLY_MATCH": return "仅关键词命中，未获得高置信匹配"
        case "EXCLUDED_KEYWORD": return "命中排除关键词，相关兴趣未计入"
        case "MULTIPLE_WEAK_MATCHES": return "多个弱匹配"
        case "LOWERED_BY_FEEDBACK": return "已按你的反馈降权"
        case "DUPLICATE_SUPPRESSED": return "因重复反馈降低新颖性"
        default: return nil
        }
    }

    static func warningText(_ codes: [String]) -> String {
        let mapped = codes.compactMap(warning)
        guard !mapped.isEmpty else { return "" }
        return "说明：" + mapped.prefix(3).joined(separator: "；")
    }
}
