import SwiftUI

/// 「今日」：应用默认首页，回答「今天有哪些信息真正值得我关注」。
///
/// 数据来自 `/api/v1/today/overview`（真实推荐结果、事件与自动化状态）。
/// 页面只做展示与一键操作，推荐排序、评分与过滤全部由后端完成。
struct TodayScreen: View {
    @ObservedObject var model: SidecarViewModel
    @ObservedObject var todayStore: TodayStore
    @ObservedObject var personalization: PersonalizationStore

    let onOpenArticle: (String) -> Void
    let onOpenEvent: (String) -> Void
    let onOpenEvents: () -> Void
    let onOpenReading: () -> Void
    let onOpenSettings: () -> Void
    let onEnableAutomation: () -> Void
    let onResumeAutomation: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider().overlay(PIHColor.hairline)
            content
        }
        .frame(minWidth: 760, minHeight: 560)
        .background(PIHColor.canvas)
        .task(id: model.state) { await todayStore.loadIfNeeded() }
    }

    // MARK: - Toolbar

    private var toolbar: some View {
        PIHPageToolbar {
            HStack(spacing: PIHSpacing.control) {
                PageHeader("今日", subtitle: subtitle)
                Spacer(minLength: 12)
                if let automation = todayStore.overview?.automation {
                    StatusPill(
                        text: automationLabel(automation),
                        tint: automationTint(automation)
                    )
                }
                Button {
                    Task { await reloadAll() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(PIHFont.captionMedium)
                }
                .disabled(todayStore.isLoading || !model.isDataReady)
                .help("刷新今日推荐")
            }
        }
    }

    private var subtitle: String {
        let date = Date().formatted(.dateTime.month().day().weekday())
        guard let overview = todayStore.overview else { return date }
        return "\(date) · 今日新增 \(overview.metrics.todayArticles) 篇 · 值得关注 \(overview.metrics.recommendedTotal) 条"
    }

    private func automationLabel(_ automation: TodayAutomationDTO) -> String {
        if !automation.enabled { return "自动处理已关闭" }
        if automation.paused { return "自动处理已暂停" }
        if automation.failed > 0 { return "自动处理 · \(automation.failed) 个失败" }
        if automation.running > 0 { return "自动处理中" }
        return "自动处理正常"
    }

    private func automationTint(_ automation: TodayAutomationDTO) -> Color {
        if !automation.enabled || automation.paused { return PIHColor.warning }
        if automation.failed > 0 { return PIHColor.danger }
        return PIHColor.positive
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        if !model.isDataReady {
            EmptyPanel(
                icon: "bolt.horizontal.circle",
                title: "本地服务未就绪",
                message: "今日页面需要 Sidecar 运行。当前状态：\(model.state.title)。",
                actionTitle: "启动 Sidecar",
                action: { model.start() }
            )
        } else if todayStore.isLoading && !todayStore.hasLoaded {
            LoadingStateView(message: "正在整理今日情报…")
        } else if let error = todayStore.errorMessage, todayStore.overview == nil {
            EmptyPanel(
                icon: "exclamationmark.triangle",
                title: "今日情报加载失败",
                message: error,
                actionTitle: "重试",
                action: { Task { await todayStore.reload() } }
            )
        } else if let overview = todayStore.overview {
            ScrollView {
                VStack(alignment: .leading, spacing: PIHSpacing.section) {
                    overviewRow(overview)
                    automationBanner(overview.automation)
                    picksSection(overview)
                    eventsSection(overview)
                    todoSection(overview)
                    recentSection(overview)
                }
                .padding(.horizontal, PIHSpacing.page)
                .padding(.vertical, 24)
                .frame(maxWidth: 1080, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .center)
            }
        } else {
            LoadingStateView(message: "正在连接本地推荐服务…")
        }
    }

    private func overviewRow(_ overview: TodayOverviewDTO) -> some View {
        HStack(spacing: PIHSpacing.cardGap) {
            MetricCard(
                title: "今日新增",
                value: "\(overview.metrics.todayArticles)",
                subtitle: "采集入库的文章",
                icon: "tray.and.arrow.down",
                tint: PIHColor.info
            )
            MetricCard(
                title: "值得关注",
                value: "\(overview.metrics.recommendedTotal)",
                subtitle: "未读推荐与事件",
                icon: "sparkles",
                tint: .accentColor
            )
            MetricCard(
                title: "重点事件",
                value: "\(overview.metrics.eventCount)",
                subtitle: "正在发展的跨来源事件",
                icon: "rectangle.3.group",
                tint: PIHColor.warning
            )
            MetricCard(
                title: "待阅读",
                value: "\(overview.metrics.unreadPicks)",
                subtitle: "今日精选与线索",
                icon: "book",
                tint: PIHColor.positive
            )
        }
    }

    @ViewBuilder
    private func automationBanner(_ automation: TodayAutomationDTO) -> some View {
        if !automation.enabled {
            AutomationNotice(
                icon: "bolt.slash",
                title: "自动处理已关闭",
                message: "开启后新文章会自动完成 AI 分析、实体提取、事件聚合与推荐刷新，数据仍只保存在本机。",
                tint: PIHColor.warning,
                actionTitle: "一键启用",
                action: onEnableAutomation
            )
        } else if automation.paused {
            AutomationNotice(
                icon: "pause.circle",
                title: "自动处理已暂停",
                message: "采集仍会继续，但 AI 分析与事件聚合会等待恢复。",
                tint: PIHColor.warning,
                actionTitle: "恢复",
                action: onResumeAutomation
            )
        } else if automation.failed > 0 {
            AutomationNotice(
                icon: "exclamationmark.triangle",
                title: "\(automation.failed) 个自动任务失败",
                message: "失败任务不会阻塞采集。可在设置中查看原因并重试。",
                tint: PIHColor.danger,
                actionTitle: "查看",
                action: onOpenSettings
            )
        }
    }

    @ViewBuilder
    private func picksSection(_ overview: TodayOverviewDTO) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader("今日精选", subtitle: "按兴趣、事件重要性与时效排序")
            if overview.picks.isEmpty {
                EmptyPanel(
                    icon: "sparkles",
                    title: "今天还没有足够的推荐",
                    message: "可以稍后刷新，或到阅读中心查看全部未读文章。",
                    actionTitle: "打开阅读中心",
                    action: onOpenReading
                )
                .pihCard(padding: 20)
            } else {
                ForEach(overview.picks) { item in
                    card(for: item, featured: item.id == overview.picks.first?.id)
                }
            }
        }
    }

    @ViewBuilder
    private func eventsSection(_ overview: TodayOverviewDTO) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader("重点事件", subtitle: "同一事件只出现一次，展开可查看全部报道")
            if overview.events.isEmpty {
                EmptyPanel(
                    icon: overview.metrics.multiReportEvents > 0
                        ? "checkmark.circle" : "rectangle.3.group",
                    title: overview.metrics.multiReportEvents > 0
                        ? "重点事件已包含在今日精选中"
                        : "今天暂无跨来源事件",
                    message: overview.metrics.multiReportEvents > 0
                        ? "同一事件不会重复出现；全部报道可在事件中心查看。"
                        : "事件会在多篇报道指向同一件事时自动形成，不需要手动聚类。",
                    actionTitle: "打开事件中心",
                    action: onOpenEvents
                )
                .pihCard(padding: 20)
            } else {
                ForEach(overview.events) { item in
                    EventRecommendationCard(
                        item: item,
                        activeFeedback: personalization.feedbackByTarget[item.id],
                        isSubmitting: personalization.pendingFeedbackTarget == item.id,
                        onOpen: { open(item) },
                        onLater: { actLater(item) },
                        onFeedback: { feedback in actFeedback(item, feedback) },
                        onRevoke: { actRevoke(item) }
                    )
                }
            }
        }
    }

    @ViewBuilder
    private func todoSection(_ overview: TodayOverviewDTO) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader("待阅读", subtitle: "尚未阅读且值得关注的文章")
            if overview.todo.isEmpty {
                Text("今天的推荐已经读完，或稍后阅读里还有内容。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
                    .pihCard(padding: 16)
            } else {
                ForEach(overview.todo) { item in
                    card(for: item, featured: false)
                }
            }
        }
    }

    @ViewBuilder
    private func recentSection(_ overview: TodayOverviewDTO) -> some View {
        if !overview.recentReads.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                SectionHeader("最近阅读", subtitle: "继续上次读到的内容")
                PIHCard(padding: 8, spacing: 0) {
                    ForEach(overview.recentReads) { item in
                        Button {
                            onOpenArticle(item.id)
                        } label: {
                            HStack(spacing: 10) {
                                Image(systemName: "clock.arrow.circlepath")
                                    .font(PIHFont.caption)
                                    .foregroundStyle(.secondary)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(item.title)
                                        .font(PIHFont.captionMedium)
                                        .lineLimit(1)
                                    Text("\(item.sourceName ?? "未知来源") · \(PIHDateFormat.display(item.lastReadAt ?? item.publishedAt))")
                                        .font(PIHFont.meta)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer(minLength: 0)
                                Image(systemName: "chevron.right")
                                    .font(PIHFont.meta)
                                    .foregroundStyle(.tertiary)
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 9)
                            .pihRowBackground()
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func card(for item: FeedItemDTO, featured: Bool) -> some View {
        if featured {
            FeaturedRecommendationCard(
                item: item,
                activeFeedback: personalization.feedbackByTarget[item.id],
                isSubmitting: personalization.pendingFeedbackTarget == item.id,
                onOpen: { open(item) },
                onLater: { actLater(item) },
                onFeedback: { feedback in actFeedback(item, feedback) },
                onRevoke: { actRevoke(item) }
            )
        } else {
            RecommendationRow(
                item: item,
                activeFeedback: personalization.feedbackByTarget[item.id],
                isSubmitting: personalization.pendingFeedbackTarget == item.id,
                onOpen: { open(item) },
                onLater: { actLater(item) },
                onFeedback: { feedback in actFeedback(item, feedback) },
                onRevoke: { actRevoke(item) }
            )
        }
    }

    // MARK: - Actions

    private func open(_ item: FeedItemDTO) {
        if item.targetType == "event" {
            onOpenEvent(item.targetId)
        } else {
            onOpenArticle(item.targetId)
        }
    }

    private func actLater(_ item: FeedItemDTO) {
        guard item.targetType == "article" else { return }
        Task {
            await personalization.markArticleLater(targetId: item.targetId)
            await todayStore.reload(showSpinner: false)
        }
    }

    private func actFeedback(_ item: FeedItemDTO, _ feedback: String) {
        Task {
            await personalization.submitFeedback(
                targetType: item.targetType,
                targetId: item.targetId,
                feedback: feedback
            )
            await todayStore.reload(showSpinner: false)
        }
    }

    private func actRevoke(_ item: FeedItemDTO) {
        Task {
            await personalization.revokeFeedback(
                targetType: item.targetType,
                targetId: item.targetId
            )
            await todayStore.reload(showSpinner: false)
        }
    }

    private func reloadAll() async {
        async let today: Void = todayStore.reload()
        async let feed: Void = personalization.refresh()
        _ = await (today, feed)
    }
}

/// 首页顶部的自动化状态说明。只在真实状态异常时出现。
private struct AutomationNotice: View {
    let icon: String
    let title: String
    let message: String
    let tint: Color
    let actionTitle: String
    let action: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(PIHFont.bannerIconSemibold)
                .foregroundStyle(tint)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(PIHFont.captionMedium)
                Text(message)
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            Button(actionTitle, action: action)
                .buttonStyle(.bordered)
                .controlSize(.small)
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: PIHRadius.control, style: .continuous)
                .fill(tint.opacity(0.09))
        )
        .overlay(
            RoundedRectangle(cornerRadius: PIHRadius.control, style: .continuous)
                .strokeBorder(tint.opacity(0.22), lineWidth: 1)
        )
    }
}
