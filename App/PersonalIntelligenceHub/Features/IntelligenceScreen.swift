// Phase 7.1 智能情报中心。
// 所有数字来自 SQLite（stats），AI 章节来自本地 Ollama；
// 每条结论都可下钻到事件或原始文章。

import AppKit
import SwiftUI

// MARK: - Tabs

private enum IntelTab: String, CaseIterable, Identifiable {
    case daily
    case events
    case weekly
    case emerging
    case history

    var id: String { rawValue }

    var title: String {
        switch self {
        case .daily: return "今日简报"
        case .events: return "重要事件"
        case .weekly: return "本周总结"
        case .emerging: return "新兴主题"
        case .history: return "历史记录"
        }
    }
}

private struct IntelReportSelection: Identifiable {
    let id: String
}

// MARK: - Screen

struct IntelligenceScreen: View {
    @ObservedObject var model: SidecarViewModel
    let onOpenEvent: (String) -> Void
    let onOpenArticle: (String) -> Void

    @StateObject private var store = IntelligenceStore()
    @State private var tab: IntelTab = .daily
    @State private var sheetSelection: IntelReportSelection?

    var body: some View {
        Group {
            if !model.isDataReady {
                EmptyPanel(
                    icon: "bolt.horizontal.circle",
                    title: "本地服务未就绪",
                    message: "情报中心需要本地 Sidecar 运行。当前状态：\(model.state.title)。",
                    actionTitle: "启动 Sidecar",
                    action: { model.start() }
                )
            } else {
                content
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(PIHColor.canvas)
        .task(id: model.state) {
            guard model.isDataReady, let client = model.apiClientForFeatures else {
                store.bind(nil)
                return
            }
            store.bind(client)
        }
        .task(id: store.dailyReport?.id) {
            if let id = store.dailyReport?.id {
                await store.loadDetailIfNeeded(id: id)
            }
        }
        .task(id: store.weeklyReport?.id) {
            if let id = store.weeklyReport?.id {
                await store.loadDetailIfNeeded(id: id)
            }
        }
        .sheet(item: $sheetSelection) { selection in
            detailSheet(for: selection.id)
        }
    }

    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: PIHSpacing.section) {
                header
                tabPicker
                if let message = store.errorMessage {
                    ErrorBanner(
                        message: message,
                        requestID: store.errorRequestID,
                        onRetry: { Task { await store.refresh() } },
                        onDismiss: { store.dismissMessages() }
                    )
                }
                if let action = store.actionMessage {
                    actionBanner(action)
                }
                if store.isGenerating, let active = store.activeReport {
                    generatingBanner(active)
                }
                tabContent
            }
            .padding(.horizontal, PIHSpacing.page)
            .padding(.vertical, PIHSpacing.page)
            .frame(maxWidth: 1180, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .center)
        }
    }

    // MARK: Header

    private var header: some View {
        PageHeader(
            "情报中心",
            subtitle: "今日发生了什么、哪些最重要、哪些领域正在变化"
        ) {
            HStack(spacing: 10) {
                modelStatusPill
                Button {
                    Task { await store.refresh() }
                } label: {
                    Label("刷新", systemImage: "arrow.clockwise")
                }
                .buttonStyle(.bordered)
                .disabled(store.isLoading)
            }
        }
    }

    private var modelStatusPill: some View {
        let available = store.isModelAvailable
        return HStack(spacing: 6) {
            Circle()
                .fill(available ? Color.green : Color.orange)
                .frame(width: 7, height: 7)
            Text(available ? "本地模型可用" : "本地模型不可用")
                .font(PIHFont.meta.weight(.medium))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(
            Capsule().fill((available ? Color.green : Color.orange).opacity(0.12))
        )
        .help(store.status?.modelName.map { "模型：\($0)" } ?? "未配置本地模型")
        .accessibilityElement(children: .combine)
        .accessibilityLabel(available ? "本地模型可用" : "本地模型不可用")
    }

    private var tabPicker: some View {
        Picker("情报视图", selection: $tab) {
            ForEach(IntelTab.allCases) { item in
                Text(item.title).tag(item)
            }
        }
        .pickerStyle(.segmented)
        .labelsHidden()
        .frame(maxWidth: 560)
    }

    private func actionBanner(_ message: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "info.circle.fill")
                .foregroundStyle(Color.accentColor)
            Text(message)
                .font(PIHFont.caption)
            Spacer(minLength: 0)
            Button {
                store.dismissMessages()
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 10, weight: .semibold))
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: PIHRadius.control, style: .continuous)
                .fill(PIHColor.accentSoft)
        )
    }

    private func generatingBanner(_ report: IntelligenceReportDTO) -> some View {
        HStack(spacing: 12) {
            ProgressView().controlSize(.small)
            VStack(alignment: .leading, spacing: 2) {
                Text(report.reportType == "daily" ? "正在生成今日情报简报…" : "正在生成本周情报总结…")
                    .font(PIHFont.bodyMedium)
                Text("统计部分已完成，正在等待本地模型输出解读")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            Button("取消生成") {
                Task { await store.cancel(report.id) }
            }
            .buttonStyle(.link)
            .font(PIHFont.captionMedium)
        }
        .padding(14)
        .pihCard(padding: 0)
    }

    // MARK: Tab content

    @ViewBuilder
    private var tabContent: some View {
        switch tab {
        case .daily:
            reportTab(
                type: "daily",
                report: store.dailyReport,
                emptyTitle: "今天还没有情报简报",
                emptyMessage: "基于今天的文章、事件与实体生成一份可追溯的情报简报。",
                actionTitle: "生成今日简报"
            )
        case .weekly:
            reportTab(
                type: "weekly",
                report: store.weeklyReport,
                emptyTitle: "本周还没有情报总结",
                emptyMessage: "汇总近 7 天的重要事件、领域变化与持续热点。",
                actionTitle: "生成本周总结"
            )
        case .events:
            IntelRankingsView(
                rankings: store.rankings,
                onOpenEvent: onOpenEvent
            )
        case .emerging:
            IntelEmergingView(emerging: store.emerging)
        case .history:
            IntelHistoryView(
                reports: store.reports,
                total: store.historyTotal,
                onSelect: { id in
                    sheetSelection = IntelReportSelection(id: id)
                    Task { await store.loadDetailIfNeeded(id: id) }
                }
            )
        }
    }

    private func reportTab(
        type: String,
        report: IntelligenceReportDTO?,
        emptyTitle: String,
        emptyMessage: String,
        actionTitle: String
    ) -> some View {
        VStack(alignment: .leading, spacing: PIHSpacing.section) {
            if let report {
                IntelReportReader(
                    report: report,
                    citations: store.detail?.report.id == report.id ? (store.detail?.citations ?? []) : [],
                    onOpenEvent: onOpenEvent,
                    onOpenArticle: onOpenArticle
                )
                HStack(spacing: 10) {
                    Button {
                        Task { await store.generate(type, force: true) }
                    } label: {
                        Label("重新生成", systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.bordered)
                    .disabled(store.isGenerating)
                    .help("重新统计并请求本地模型生成新版本，旧版本保留在历史记录")
                    Text("同一周期只保留一个活跃版本")
                        .font(PIHFont.meta)
                        .foregroundStyle(.tertiary)
                }
            } else if store.isLoading && !store.hasLoaded {
                LoadingStateView(message: "正在读取情报数据…")
                    .frame(height: 280)
            } else {
                EmptyPanel(
                    icon: "sparkles.rectangle.stack",
                    title: emptyTitle,
                    message: emptyMessage,
                    actionTitle: actionTitle,
                    action: { Task { await store.generate(type) } }
                )
            }
        }
    }

    // MARK: Sheet

    @ViewBuilder
    private func detailSheet(for id: String) -> some View {
        ScrollView {
            if let detail = store.detail, detail.report.id == id {
                IntelReportReader(
                    report: detail.report,
                    citations: detail.citations,
                    onOpenEvent: { eventID in
                        sheetSelection = nil
                        onOpenEvent(eventID)
                    },
                    onOpenArticle: { articleID in
                        sheetSelection = nil
                        onOpenArticle(articleID)
                    }
                )
                .padding(PIHSpacing.page)
            } else {
                LoadingStateView(message: "正在读取情报详情…")
                    .frame(height: 360)
            }
        }
        .frame(minWidth: 760, minHeight: 620)
        .background(PIHColor.canvas)
        .task(id: id) { await store.loadDetailIfNeeded(id: id) }
    }
}

// MARK: - Report reader

private struct IntelReportReader: View {
    let report: IntelligenceReportDTO
    let citations: [IntelligenceCitationDTO]
    let onOpenEvent: (String) -> Void
    let onOpenArticle: (String) -> Void

    private let metricColumns = [GridItem(.adaptive(minimum: 180), spacing: PIHSpacing.cardGap)]

    private var eventCitations: [String: [IntelligenceCitationDTO]] {
        Dictionary(grouping: citations.filter { $0.citationType == "event" }, by: \.refId)
    }

    private var articleCitations: [String: [IntelligenceCitationDTO]] {
        Dictionary(grouping: citations.filter { $0.citationType == "article" }, by: \.refId)
    }

    private var evidenceArticles: [IntelligenceEvidenceArticleDTO] {
        report.stats.resolvedKeyEvents.flatMap(\.evidence)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: PIHSpacing.section) {
            heroCard
            statsGrid
            if report.status == "degraded" || report.aiStatus != "used" {
                degradedNotice
            }
            aiSections
            statsSections
            traceabilitySection
            metadataCard
        }
    }

    private var heroCard: some View {
        PIHCard {
            HStack(alignment: .top, spacing: PIHSpacing.control) {
                VStack(alignment: .leading, spacing: 10) {
                    Text(report.headline ?? (report.reportType == "daily" ? "今日情报简报" : "本周情报总结"))
                        .font(PIHFont.sectionTitle)
                        .fixedSize(horizontal: false, vertical: true)
                    if let overview = report.overview, !overview.isEmpty {
                        Text(overview)
                            .font(PIHFont.body)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 8)
                IntelStatusBadge(status: report.status, aiStatus: report.aiStatus)
            }
            Divider()
            HStack(spacing: PIHSpacing.section) {
                meta("数据区间", periodText)
                meta("生成时间", IntelDate.short(report.finishedAt ?? report.createdAt))
                meta("模型", report.modelName ?? "未使用模型")
                meta("引用", "\(report.citationCount) 条")
            }
        }
    }

    private func meta(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
            Text(value)
                .font(PIHFont.captionMedium)
                .lineLimit(1)
        }
    }

    private var periodText: String {
        let start = report.stats.period?.start ?? report.periodStart
        let end = report.stats.period?.end ?? report.periodEnd
        return start == end ? start : "\(start) → \(end)"
    }

    private var statsGrid: some View {
        LazyVGrid(columns: metricColumns, spacing: PIHSpacing.cardGap) {
            MetricCard(
                title: "本期文章",
                value: "\(report.stats.totals?.articles ?? report.articleCount)",
                subtitle: "上一区间 \(report.stats.totals?.previousArticles ?? 0) 篇",
                icon: "newspaper",
                tint: .blue
            )
            MetricCard(
                title: "活动事件",
                value: "\(report.stats.totals?.events ?? report.eventCount)",
                subtitle: "新出现 \(report.stats.totals?.newEvents ?? 0) 个",
                icon: "rectangle.3.group",
                tint: .purple
            )
            MetricCard(
                title: "信息来源",
                value: "\(report.stats.totals?.sources ?? 0)",
                subtitle: "本区间参与报道",
                icon: "dot.radiowaves.left.and.right",
                tint: .teal
            )
            MetricCard(
                title: "未进入事件",
                value: "\(report.stats.totals?.unclusteredArticles ?? 0)",
                subtitle: "篇报道仍待聚合",
                icon: "circle.dashed",
                tint: .orange
            )
        }
    }

    private var degradedNotice: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 3) {
                Text(report.aiStatus == "unavailable" ? "本地模型不可用：本报告仅含数据库统计" : "AI 输出未通过校验：本报告仅含数据库统计")
                    .font(PIHFont.bodyMedium)
                Text(report.errorMessage ?? "统计与事件证据仍然完整可追溯，AI 解读将在模型可用后重新生成。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: PIHRadius.control, style: .continuous)
                .fill(Color.orange.opacity(0.09))
        )
    }

    @ViewBuilder
    private var aiSections: some View {
        if !report.content.resolvedKeyEvents.isEmpty {
            VStack(alignment: .leading, spacing: PIHSpacing.cardGap) {
                SectionHeader("重要事件解读", subtitle: "AI 生成 · 每条均可追溯到事件与文章")
                ForEach(Array(report.content.resolvedKeyEvents.enumerated()), id: \.element.id) { index, item in
                    IntelAISectionCard(
                        index: index + 1,
                        item: item,
                        eventCitation: eventCitations[item.eventId]?.first,
                        articleCitations: item.articleIds.compactMap { articleCitations[$0]?.first },
                        onOpenEvent: onOpenEvent,
                        onOpenArticle: onOpenArticle
                    )
                }
            }
        }
        if !report.content.resolvedTopics.isEmpty {
            PIHCard {
                CardHeader("变化与新兴主题", icon: "chart.line.uptrend.xyaxis")
                ForEach(report.content.resolvedTopics) { topic in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(topic.name)
                            .font(PIHFont.bodyMedium)
                        Text(topic.direction)
                            .font(PIHFont.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        HStack(spacing: 8) {
                            ForEach(topic.evidenceEventIds, id: \.self) { eventID in
                                Button {
                                    onOpenEvent(eventID)
                                } label: {
                                    Label("关联事件", systemImage: "arrow.up.right.square")
                                        .font(PIHFont.meta)
                                }
                                .buttonStyle(.link)
                            }
                        }
                    }
                    .padding(.vertical, 6)
                }
            }
        }
        if !report.content.resolvedUncertainties.isEmpty {
            PIHCard {
                CardHeader("不确定性说明", icon: "questionmark.circle")
                ForEach(report.content.resolvedUncertainties, id: \.self) { item in
                    Text("· \(item)")
                        .font(PIHFont.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    @ViewBuilder
    private var statsSections: some View {
        let categories = report.stats.resolvedCategories.filter { $0.articles > 0 || $0.previous > 0 }
        if !categories.isEmpty || !report.stats.resolvedRising.isEmpty {
            HStack(alignment: .top, spacing: PIHSpacing.cardGap) {
                PIHCard {
                    CardHeader("分类变化", icon: "square.grid.2x2")
                    Text("数据库统计 · 本期与上一区间对比")
                        .font(PIHFont.meta)
                        .foregroundStyle(.tertiary)
                    ForEach(categories.prefix(8)) { item in
                        HStack(spacing: 10) {
                            Text(item.name)
                                .font(PIHFont.caption)
                                .frame(width: 72, alignment: .leading)
                            Text("\(item.articles) 篇")
                                .font(PIHFont.captionMedium)
                                .monospacedDigit()
                            Text(item.previous == 0 ? "新增" : "上期 \(item.previous)")
                                .font(PIHFont.meta)
                                .foregroundStyle(.tertiary)
                            Spacer(minLength: 0)
                            IntelDeltaBadge(delta: item.delta)
                        }
                    }
                }
                .frame(maxWidth: .infinity)

                PIHCard {
                    CardHeader("上升关键词", icon: "arrow.up.right")
                    Text("数据库统计 · 关键词计数对比")
                        .font(PIHFont.meta)
                        .foregroundStyle(.tertiary)
                    if report.stats.resolvedRising.isEmpty {
                        Text("本期没有明显上升的关键词")
                            .font(PIHFont.caption)
                            .foregroundStyle(.secondary)
                    }
                    ForEach(report.stats.resolvedRising.prefix(8)) { item in
                        HStack(spacing: 10) {
                            Text(item.keyword)
                                .font(PIHFont.caption)
                                .lineLimit(1)
                            Text("\(item.count) 次")
                                .font(PIHFont.captionMedium)
                                .monospacedDigit()
                            Text("上期 \(item.previous)")
                                .font(PIHFont.meta)
                                .foregroundStyle(.tertiary)
                            Spacer(minLength: 0)
                            IntelDeltaBadge(delta: item.delta)
                        }
                    }
                }
                .frame(maxWidth: .infinity)
            }
        }
    }

    @ViewBuilder
    private var traceabilitySection: some View {
        if !evidenceArticles.isEmpty {
            PIHCard {
                CardHeader("支撑文章", icon: "link", trailing: {
                    Text("\(Set(evidenceArticles.map(\.articleId)).count) 篇")
                        .font(PIHFont.meta)
                        .foregroundStyle(.tertiary)
                })
                ForEach(evidenceArticles) { item in
                    Button {
                        onOpenArticle(item.articleId)
                    } label: {
                        HStack(alignment: .top, spacing: 10) {
                            Image(systemName: "doc.text")
                                .font(.system(size: 12))
                                .foregroundStyle(.secondary)
                                .padding(.top, 2)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(item.title)
                                    .font(PIHFont.caption)
                                    .foregroundStyle(.primary)
                                    .lineLimit(2)
                                Text(item.sourceName)
                                    .font(PIHFont.meta)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer(minLength: 6)
                            Image(systemName: "chevron.right")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(.tertiary)
                        }
                        .padding(.vertical, 4)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .help("在文章中打开")
                }
            }
        }
    }

    private var metadataCard: some View {
        PIHCard {
            CardHeader("生成信息", icon: "info.circle")
            HStack(spacing: PIHSpacing.section) {
                meta("报告 ID", String(report.id.prefix(8)))
                meta("Prompt", report.promptVersion)
                meta("统计版本", report.statsVersion)
                meta("数据范围", "\(IntelDate.short(report.dataFromAt)) → \(IntelDate.short(report.dataToAt))")
                meta("耗时", report.durationMs.map { "\($0 / 1000).\(($0 % 1000) / 100)s" } ?? "—")
            }
            if let error = report.errorMessage, report.status == "failed" {
                Text(error)
                    .font(PIHFont.meta)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
            }
        }
    }
}

// MARK: - AI event card

private struct IntelAISectionCard: View {
    let index: Int
    let item: IntelligenceKeyEventContentDTO
    let eventCitation: IntelligenceCitationDTO?
    let articleCitations: [IntelligenceCitationDTO]
    let onOpenEvent: (String) -> Void
    let onOpenArticle: (String) -> Void

    var body: some View {
        PIHCard {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text("\(index)")
                    .font(PIHFont.meta.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 18)
                Text(item.title?.isEmpty == false ? item.title! : "关联事件")
                    .font(PIHFont.cardTitle)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 8)
                Button {
                    onOpenEvent(item.eventId)
                } label: {
                    Label("事件详情", systemImage: "arrow.up.right.square")
                        .font(PIHFont.meta)
                }
                .buttonStyle(.link)
                .help(eventCitation?.evidence ?? "在事件中心打开")
            }
            VStack(alignment: .leading, spacing: 8) {
                if !item.development.isEmpty {
                    labelled("新进展", item.development)
                }
                if !item.background.isEmpty {
                    labelled("背景", item.background)
                }
                if !item.impact.isEmpty {
                    labelled("影响", item.impact)
                }
                if !item.importance.isEmpty {
                    labelled("重要性", item.importance)
                }
            }
            if !item.entities.isEmpty {
                HStack(spacing: 6) {
                    ForEach(item.entities, id: \.self) { name in
                        Text(name)
                            .font(PIHFont.meta)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(Capsule().fill(PIHColor.accentSoft))
                    }
                }
            }
            if !articleCitations.isEmpty {
                HStack(spacing: PIHSpacing.control) {
                    ForEach(articleCitations.prefix(3)) { citation in
                        Button {
                            onOpenArticle(citation.refId)
                        } label: {
                            Label(citation.title ?? "支撑文章", systemImage: "doc.text")
                                .font(PIHFont.meta)
                                .lineLimit(1)
                        }
                        .buttonStyle(.link)
                    }
                }
            }
        }
    }

    private func labelled(_ title: String, _ body: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(title)
                .font(PIHFont.meta.weight(.semibold))
                .foregroundStyle(.tertiary)
                .frame(width: 44, alignment: .leading)
            Text(body)
                .font(PIHFont.body)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

// MARK: - Rankings

private struct IntelRankingsView: View {
    let rankings: [String: [IntelligenceRankingItemDTO]]
    let onOpenEvent: (String) -> Void

    private let sections: [(kind: String, title: String, subtitle: String)] = [
        ("importance", "当前最重要事件", "按重要度评分排序"),
        ("heat", "热度最高事件", "按热度评分排序"),
        ("emerging", "热度上升事件", "热度 60% + 新鲜度 40%"),
        ("new", "新出现的事件", "首次出现于近 7 天"),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: PIHSpacing.section) {
            SectionHeader("重要事件排行榜", subtitle: "全部来自 Phase 4 真实评分快照，无前端硬编码")
            ForEach(sections, id: \.kind) { section in
                PIHCard {
                    CardHeader(section.title, icon: icon(for: section.kind)) {
                        Text(section.subtitle)
                            .font(PIHFont.meta)
                            .foregroundStyle(.tertiary)
                    }
                    let items = rankings[section.kind] ?? []
                    if items.isEmpty {
                        Text("暂无已评分事件")
                            .font(PIHFont.caption)
                            .foregroundStyle(.secondary)
                    }
                    ForEach(items) { item in
                        Button {
                            onOpenEvent(item.event.id)
                        } label: {
                            HStack(alignment: .top, spacing: 12) {
                                Text("\(item.rank)")
                                    .font(PIHFont.metricCompact)
                                    .foregroundStyle(item.rank <= 3 ? Color.accentColor : Color.secondary)
                                    .frame(width: 30, alignment: .leading)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(item.event.title)
                                        .font(PIHFont.bodyMedium)
                                        .lineLimit(2)
                                    HStack(spacing: 10) {
                                        Text(item.event.category)
                                            .font(PIHFont.meta)
                                            .foregroundStyle(.secondary)
                                        Text("报道 \(item.event.articleCount)")
                                        Text("来源 \(item.event.sourceCount)")
                                        Text(String(format: "评分 %.1f", item.score))
                                    }
                                    .font(PIHFont.meta)
                                    .foregroundStyle(.tertiary)
                                }
                                Spacer(minLength: 8)
                                if let change = item.scoreChange, abs(change) >= 0.01 {
                                    IntelDeltaBadge(delta: Int(change.rounded()))
                                }
                                Image(systemName: "chevron.right")
                                    .font(.system(size: 10, weight: .semibold))
                                    .foregroundStyle(.tertiary)
                            }
                            .padding(.vertical, 6)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .pihRowBackground()
                    }
                }
            }
        }
    }

    private func icon(for kind: String) -> String {
        switch kind {
        case "importance": return "star"
        case "heat": return "flame"
        case "emerging": return "chart.line.uptrend.xyaxis"
        default: return "sparkle"
        }
    }
}

// MARK: - Emerging

private struct IntelEmergingView: View {
    let emerging: IntelligenceEmergingDTO?

    var body: some View {
        VStack(alignment: .leading, spacing: PIHSpacing.section) {
            SectionHeader(
                "新兴主题发现",
                subtitle: "数据库统计结果，非 AI 推断；窗口为近 7 天"
            )
            if let emerging {
                HStack(alignment: .top, spacing: PIHSpacing.cardGap) {
                    keywordCard(
                        title: "明显增加的主题",
                        icon: "arrow.up.right",
                        items: emerging.resolvedRising
                    )
                    keywordCard(
                        title: "多来源共同关注",
                        icon: "antenna.radiowaves.left.and.right",
                        items: emerging.resolvedCrossSource.map {
                            IntelligenceKeywordStatDTO(
                                keyword: $0.keyword,
                                count: $0.count,
                                previous: 0,
                                delta: $0.count,
                                sources: $0.sources
                            )
                        }
                    )
                }
                HStack(alignment: .top, spacing: PIHSpacing.cardGap) {
                    entityCard(emerging.resolvedNewEntities, emerging.resolvedTopEntities)
                    unclusteredCard(emerging.resolvedUnclustered)
                }
                if !emerging.resolvedNotes.isEmpty {
                    PIHCard {
                        CardHeader("统计口径", icon: "info.circle")
                        ForEach(emerging.resolvedNotes, id: \.self) { note in
                            Text("· \(note)")
                                .font(PIHFont.meta)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            } else {
                LoadingStateView(message: "正在计算新兴主题…")
                    .frame(height: 260)
            }
        }
    }

    private func keywordCard(
        title: String,
        icon: String,
        items: [IntelligenceKeywordStatDTO]
    ) -> some View {
        PIHCard {
            CardHeader(title, icon: icon)
            if items.isEmpty {
                Text("近 7 天没有达到阈值的主题")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            }
            ForEach(items.prefix(8)) { item in
                HStack(spacing: 10) {
                    Text(item.keyword)
                        .font(PIHFont.bodyMedium)
                        .lineLimit(1)
                    Spacer(minLength: 6)
                    Text("\(item.count) 次")
                        .font(PIHFont.captionMedium)
                        .monospacedDigit()
                    Text("\(item.sources.count) 个来源")
                        .font(PIHFont.meta)
                        .foregroundStyle(.tertiary)
                }
                .padding(.vertical, 3)
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func entityCard(
        _ newEntities: [IntelligenceEntityStatDTO],
        _ topEntities: [IntelligenceTopEntityDTO]
    ) -> some View {
        PIHCard {
            CardHeader("新出现的人物 / 组织 / 技术", icon: "person.2")
            if newEntities.isEmpty {
                Text("近 7 天没有新实体达到提及阈值")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            }
            ForEach(newEntities.prefix(8)) { item in
                HStack(spacing: 10) {
                    Text(item.canonicalName)
                        .font(PIHFont.caption)
                        .lineLimit(1)
                    Text(typeLabel(item.entityType))
                        .font(PIHFont.meta)
                        .foregroundStyle(.tertiary)
                    Spacer(minLength: 6)
                    Text("\(item.mentions ?? 0) 篇提及")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                }
                .padding(.vertical, 2)
            }
            if !topEntities.isEmpty {
                Divider().padding(.vertical, 4)
                Text("高频实体（近 7 天提及最多）")
                    .font(PIHFont.meta.weight(.semibold))
                    .foregroundStyle(.secondary)
                ForEach(topEntities.prefix(5)) { item in
                    HStack(spacing: 10) {
                        Text(item.name)
                            .font(PIHFont.caption)
                            .lineLimit(1)
                        Spacer(minLength: 6)
                        Text("\(item.mentions) 篇提及")
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 2)
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func unclusteredCard(_ items: [IntelligenceUnclusteredDTO]) -> some View {
        PIHCard {
            CardHeader("尚未形成事件的观察项", icon: "circle.dashed")
            Text("以下报道尚未进入事件聚合，仅作为观察线索")
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
            if items.isEmpty {
                Text("近 7 天没有未聚合报道")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            }
            ForEach(items.prefix(6)) { item in
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.title)
                        .font(PIHFont.caption)
                        .lineLimit(2)
                    Text("\(item.sourceName) · \(IntelDate.short(item.at))")
                        .font(PIHFont.meta)
                        .foregroundStyle(.tertiary)
                }
                .padding(.vertical, 3)
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func typeLabel(_ type: String) -> String {
        switch type {
        case "person": return "人物"
        case "organization": return "组织"
        case "product": return "产品"
        case "location": return "地点"
        case "event": return "事件"
        default: return "其他"
        }
    }
}

// MARK: - History

private struct IntelHistoryView: View {
    let reports: [IntelligenceReportDTO]
    let total: Int
    let onSelect: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: PIHSpacing.section) {
            SectionHeader("情报历史记录", subtitle: "共 \(total) 份，按生成时间倒序")
            if reports.isEmpty {
                EmptyPanel(
                    icon: "clock",
                    title: "还没有历史情报",
                    message: "生成今日简报或本周总结后，会在这里保留版本记录。",
                    actionTitle: nil,
                    action: nil
                )
            } else {
                PIHCard {
                    ForEach(reports) { report in
                        Button {
                            onSelect(report.id)
                        } label: {
                            HStack(alignment: .top, spacing: 12) {
                                Image(systemName: report.reportType == "daily" ? "sun.max" : "calendar")
                                    .font(.system(size: 13))
                                    .foregroundStyle(.secondary)
                                    .frame(width: 18)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(report.headline ?? (report.reportType == "daily" ? "今日情报简报" : "本周情报总结"))
                                        .font(PIHFont.bodyMedium)
                                        .lineLimit(2)
                                    HStack(spacing: 10) {
                                        Text(report.reportType == "daily" ? "日报" : "周报")
                                        Text(periodText(report))
                                        Text(IntelDate.short(report.createdAt))
                                        Text("引用 \(report.citationCount)")
                                    }
                                    .font(PIHFont.meta)
                                    .foregroundStyle(.tertiary)
                                }
                                Spacer(minLength: 8)
                                IntelStatusBadge(status: report.status, aiStatus: report.aiStatus)
                                Image(systemName: "chevron.right")
                                    .font(.system(size: 10, weight: .semibold))
                                    .foregroundStyle(.tertiary)
                            }
                            .padding(.vertical, 8)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .pihRowBackground()
                        if report.id != reports.last?.id {
                            Divider()
                        }
                    }
                }
            }
        }
    }

    private func periodText(_ report: IntelligenceReportDTO) -> String {
        report.periodStart == report.periodEnd
            ? report.periodStart
            : "\(report.periodStart) → \(report.periodEnd)"
    }
}

// MARK: - Shared bits

private struct IntelStatusBadge: View {
    let status: String
    let aiStatus: String

    var body: some View {
        StatusPill(text: label, tint: tint)
            .help(help)
    }

    private var label: String {
        switch status {
        case "succeeded": return aiStatus == "used" ? "AI 情报" : "已生成"
        case "degraded": return "仅统计"
        case "pending", "running": return "生成中"
        case "failed": return "生成失败"
        case "cancelled": return "已取消"
        case "superseded": return "已被替代"
        default: return status
        }
    }

    private var tint: Color {
        switch status {
        case "succeeded": return .green
        case "degraded": return .orange
        case "pending", "running": return .blue
        case "failed": return .red
        default: return .secondary
        }
    }

    private var help: String {
        switch aiStatus {
        case "used": return "本地模型生成的解读"
        case "unavailable": return "本地模型不可用，仅包含数据库统计"
        case "invalid": return "模型输出未通过结构校验"
        default: return "等待生成"
        }
    }
}

private struct IntelDeltaBadge: View {
    let delta: Int

    var body: some View {
        if delta == 0 {
            Text("持平")
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
        } else {
            let positive = delta > 0
            HStack(spacing: 2) {
                Image(systemName: positive ? "arrow.up" : "arrow.down")
                    .font(.system(size: 9, weight: .bold))
                Text("\(abs(delta))")
                    .font(PIHFont.meta.weight(.semibold))
                    .monospacedDigit()
            }
            .foregroundStyle(positive ? Color.green : Color.secondary)
        }
    }
}

// MARK: - Formatting

@MainActor
private enum IntelDate {
    private static let iso: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let isoNoFraction: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static let display: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "MM-dd HH:mm"
        return formatter
    }()

    static func short(_ value: String?) -> String {
        guard let value, !value.isEmpty else { return "—" }
        if value.count == 10 { return value }
        let date = iso.date(from: value) ?? isoNoFraction.date(from: value)
        guard let date else { return String(value.prefix(16)) }
        return display.string(from: date)
    }
}
