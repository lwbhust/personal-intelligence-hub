import SwiftUI

/// 每日精选：编辑式每日情报简报。
///
/// 分区顺序：今日概览 → 今日必读 → 核心兴趣动态 → 重点事件变化 → 新兴主题
/// → 独立新闻线索 → 更多重点（默认折叠）。
/// 条目一律引用真实事件/文章 ID；本版本日报由规则生成（ai_status=skipped）。
struct DailyDigestSheet: View {
    @ObservedObject var store: PersonalizationStore
    var onOpenArticle: ((String) -> Void)? = nil
    var onOpenEvent: ((String) -> Void)? = nil
    @Environment(\.dismiss) private var dismiss

    @State private var expandedHighlights = false
    @State private var expandedEvents: Set<String> = []

    private var digest: DailyDigestDTO? { store.digest }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(PIHColor.hairline)
            content
        }
        .frame(width: 900, height: 720)
        .background(PIHColor.canvas)
        .task {
            if store.digest == nil {
                await store.loadTodayDigest()
            }
        }
    }

    // MARK: - Header

    private var header: some View {
        HStack(spacing: 10) {
            PageHeader("每日精选", subtitle: "编辑式每日情报简报")
            Spacer(minLength: 0)
            if store.isGeneratingDigest {
                ProgressView().controlSize(.small)
            }
            Button {
                Task { await store.loadTodayDigest(force: true) }
            } label: {
                Label("重新生成", systemImage: "arrow.clockwise")
            }
            .disabled(store.isGeneratingDigest)
            Button("完成") { dismiss() }
                .keyboardShortcut(.defaultAction)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 16)
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                if let error = store.actionErrorMessage {
                    NoticeBanner(
                        icon: "exclamationmark.triangle",
                        tint: PIHColor.warning,
                        message: error,
                        onDismiss: nil
                    )
                }
                if let digest {
                    overview(digest)
                    section(
                        key: "must_not_miss", title: "今日必读",
                        subtitle: "按推荐优先级排序，引用真实事件与文章",
                        digest: digest
                    )
                    section(
                        key: "core_interest", title: "核心兴趣动态",
                        subtitle: "命中你设定的核心关注", digest: digest
                    )
                    section(
                        key: "event_changes", title: "重点事件变化",
                        subtitle: "多篇报道聚合的事件进展", digest: digest
                    )
                    section(
                        key: "emerging", title: "新兴主题",
                        subtitle: "来自真实关键词的环比变化", digest: digest
                    )
                    section(
                        key: "leads", title: "独立新闻线索",
                        subtitle: "尚未形成事件的单篇报道", digest: digest
                    )
                    highlightsSection(digest)
                } else if store.isGeneratingDigest {
                    LoadingStateView(message: "正在生成今日精选…")
                } else {
                    emptyState
                }
            }
            .padding(24)
            .frame(maxWidth: 860, alignment: .leading)
        }
    }

    // MARK: - Overview

    private func overview(_ digest: DailyDigestDTO) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(digest.headline ?? "\(digest.digestDate) 每日精选")
                .font(.system(size: 24, weight: .semibold))
                .fixedSize(horizontal: false, vertical: true)
            Text(digest.overview ?? "暂无概览")
                .font(PIHFont.body)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 8) {
                StatusPill(text: digest.digestDate, tint: PIHColor.info)
                StatusPill(
                    text: digest.status == "succeeded" ? "已生成" : digest.status,
                    tint: digest.status == "succeeded" ? PIHColor.positive : PIHColor.warning
                )
                StatusPill(
                    text: "AI：\(digest.aiStatus == "skipped" ? "规则生成" : digest.aiStatus)",
                    tint: PIHColor.neutral
                )
                Text("\(digest.digestVersion) · \(digest.timezone)")
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
                Spacer(minLength: 0)
                if let generatedAt = digest.generatedAt {
                    Text("生成于 \(PIHDateFormat.display(generatedAt, empty: "未知"))")
                        .font(PIHFont.meta)
                        .foregroundStyle(.tertiary)
                }
                if store.digestHistory.count > 1 {
                    Menu {
                        ForEach(store.digestHistory) { item in
                            Button(item.digestDate) {
                                Task { await store.loadDigest(date: item.digestDate) }
                            }
                        }
                    } label: {
                        Label("历史日报", systemImage: "clock.arrow.circlepath")
                            .font(PIHFont.caption)
                    }
                    .menuStyle(.borderlessButton)
                    .fixedSize()
                }
            }
        }
    }

    // MARK: - Sections

    @ViewBuilder
    private func section(
        key: String, title: String, subtitle: String, digest: DailyDigestDTO
    ) -> some View {
        let items = digest.items
            .filter { $0.section == key }
            .sorted { $0.rank < $1.rank }
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                SectionHeader(title, subtitle: "\(items.count) 条 · \(subtitle)")
                PIHCard(padding: 16, spacing: 0) {
                    ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                        digestRow(item, index: index + 1)
                        if index < items.count - 1 {
                            Divider().overlay(PIHColor.hairline)
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func highlightsSection(_ digest: DailyDigestDTO) -> some View {
        let items = digest.items
            .filter { $0.section == "highlights" }
            .sorted { $0.rank < $1.rank }
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Button {
                    withAnimation(.easeInOut(duration: 0.16)) {
                        expandedHighlights.toggle()
                    }
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: expandedHighlights ? "chevron.down" : "chevron.right")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(.secondary)
                            .accessibilityHidden(true)
                        Text("更多重点")
                            .font(PIHFont.subsectionTitle)
                        Text("\(items.count)")
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                        Spacer(minLength: 0)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                if expandedHighlights {
                    PIHCard(padding: 16, spacing: 0) {
                        ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                            digestRow(item, index: index + 1)
                            if index < items.count - 1 {
                                Divider().overlay(PIHColor.hairline)
                            }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func digestRow(_ item: DigestItemDTO, index: Int) -> some View {
        let clickable = item.targetType != "topic" && item.targetId != nil
        VStack(alignment: .leading, spacing: 8) {
            rowContent(item, index: index, showsChevron: clickable)
                .contentShape(Rectangle())
                .onTapGesture {
                    if clickable { open(item) }
                }
                .help(item.targetType == "event" ? "打开事件详情" : "打开文章")
                .accessibilityLabel(
                    "\(item.title)，\(item.targetType == "event" ? "打开事件详情" : "打开文章")"
                )
            if item.targetType == "event", let detail = item.eventDetail {
                eventDetail(detail, itemId: item.id)
            }
        }
    }

    /// 事件级展示：代表文章、其他来源、最新进展与信息增量。
    @ViewBuilder
    private func eventDetail(_ detail: DigestEventDetailDTO, itemId: String) -> some View {
        let expanded = expandedEvents.contains(itemId)
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                StatusPill(text: detail.category, tint: PIHColor.info)
                Text("\(detail.articleCount) 篇报道 · \(detail.sourceCount) 个来源")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                if let importance = detail.importance {
                    Text("重要性 \(Int(importance.rounded()))")
                        .font(PIHFont.meta)
                        .foregroundStyle(.tertiary)
                }
                Spacer(minLength: 0)
                if !detail.otherReports.isEmpty {
                    Button(expanded ? "收起其他来源" : "查看其他来源 (\(detail.otherReports.count))") {
                        withAnimation(.easeInOut(duration: 0.16)) {
                            if expanded {
                                expandedEvents.remove(itemId)
                            } else {
                                expandedEvents.insert(itemId)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                    .font(PIHFont.caption)
                    .foregroundStyle(PIHColor.info)
                }
            }
            if expanded {
                VStack(alignment: .leading, spacing: 5) {
                    if let representative = detail.representative {
                        eventReportRow(
                            title: representative.title,
                            source: representative.sourceName,
                            publishedAt: representative.publishedAt,
                            prefix: "代表文章"
                        ) {
                            dismiss()
                            onOpenArticle?(representative.articleId)
                        }
                    }
                    ForEach(detail.otherReports) { report in
                        eventReportRow(
                            title: report.title,
                            source: report.sourceName,
                            publishedAt: report.publishedAt,
                            prefix: "其他报道"
                        ) {
                            dismiss()
                            onOpenArticle?(report.articleId)
                        }
                    }
                    if let latest = detail.latestProgress, !latest.isRepresentative {
                        eventReportRow(
                            title: latest.title,
                            source: latest.sourceName,
                            publishedAt: latest.publishedAt,
                            prefix: "最新进展"
                        ) {
                            dismiss()
                            onOpenArticle?(latest.articleId)
                        }
                    }
                }
                .padding(.leading, 4)
            }
            Text(
                "信息增量：新增 \(detail.informationIncrement.followUpCount) 篇后续报道 · "
                + "\(detail.informationIncrement.distinctSources) 个独立来源"
                + (detail.firstPublishedAt.map { " · 首发 \(PIHDateFormat.display($0, empty: "未知"))" } ?? "")
            )
            .font(PIHFont.meta)
            .foregroundStyle(.tertiary)
        }
        .padding(.leading, 32)
        .padding(.bottom, 2)
    }

    @ViewBuilder
    private func eventReportRow(
        title: String,
        source: String?,
        publishedAt: String?,
        prefix: String,
        onOpen: @escaping () -> Void
    ) -> some View {
        Button(action: onOpen) {
            HStack(alignment: .top, spacing: 6) {
                Text(prefix)
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
                    .frame(width: 56, alignment: .leading)
                VStack(alignment: .leading, spacing: 1) {
                    Text(title)
                        .font(PIHFont.caption)
                        .foregroundStyle(.primary)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                    HStack(spacing: 6) {
                        if let source {
                            Text(source)
                        }
                        if let publishedAt {
                            Text(PIHDateFormat.display(publishedAt, empty: ""))
                        }
                    }
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                Image(systemName: "arrow.up.right")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(.tertiary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("打开报道原文")
    }

    private func rowContent(
        _ item: DigestItemDTO, index: Int, showsChevron: Bool
    ) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text("\(index)")
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(.tertiary)
                .frame(width: 20, alignment: .trailing)
                .padding(.top, 2)
            VStack(alignment: .leading, spacing: 3) {
                Text(item.title)
                    .font(PIHFont.bodyMedium)
                    .fixedSize(horizontal: false, vertical: true)
                if let reason = item.reason, !reason.isEmpty {
                    Text(reason)
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if !item.matchedInterests.isEmpty {
                    Text("匹配：" + item.matchedInterests.prefix(3).joined(separator: "、"))
                        .font(PIHFont.meta)
                        .foregroundStyle(.tertiary)
                }
            }
            Spacer(minLength: 8)
            if let score = item.score {
                Text("\(Int(score.rounded()))")
                    .font(PIHFont.meta)
                    .monospacedDigit()
                    .foregroundStyle(.tertiary)
                    .padding(.top, 2)
            }
            if showsChevron {
                Image(systemName: "arrow.up.right")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .padding(.top, 2)
                    .accessibilityHidden(true)
            }
        }
        .padding(.vertical, 10)
        .contentShape(Rectangle())
    }

    private var emptyState: some View {
        PIHCard {
            VStack(alignment: .leading, spacing: 10) {
                Text("今天还没有生成日报。")
                    .font(PIHFont.subsectionTitle)
                Text("日报由真实推荐结果规则生成，不会调用模型，也不会伪造条目。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
                Button("立即生成") {
                    Task { await store.loadTodayDigest() }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
            }
        }
    }

    private func open(_ item: DigestItemDTO) {
        guard let id = item.targetId else { return }
        dismiss()
        if item.targetType == "event" {
            onOpenEvent?(id)
        } else {
            onOpenArticle?(id)
        }
    }
}
