import SwiftUI

// MARK: - 推荐等级与目标类型
//
// Phase 7.3.2：情报流组件。所有文字、数量、分数与理由都直接来自
// `/api/v1/personalization/feed`，组件本身不推断、不补零、不造数据。

/// 推荐等级标签。等级代表推荐优先级，不代表事实真实性。
struct LevelPill: View {
    let level: RecommendationLevel

    private var tint: Color {
        switch level {
        case .mustRead: return PIHColor.danger
        case .recommended: return PIHColor.warning
        case .watch: return PIHColor.info
        case .low, .notRecommended: return PIHColor.neutral
        }
    }

    var body: some View {
        Text(level.title)
            .font(PIHFont.meta.weight(.semibold))
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .foregroundStyle(tint)
            .background(Capsule().fill(tint.opacity(0.12)))
            .accessibilityLabel("推荐等级：\(level.title)")
    }
}

/// 事件 / 独立新闻线索的明确区分，避免把单篇文章展示成多源事件。
struct FeedTargetBadge: View {
    let item: FeedItemDTO

    var body: some View {
        if item.targetType == "event" {
            tag("事件", tint: PIHColor.info)
        } else if item.eventId == nil {
            tag("独立新闻线索", tint: PIHColor.neutral)
        } else {
            tag("文章", tint: PIHColor.neutral)
        }
    }

    private func tag(_ text: String, tint: Color) -> some View {
        Text(text)
            .font(PIHFont.meta.weight(.medium))
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .foregroundStyle(tint)
            .background(Capsule().fill(tint.opacity(0.10)))
    }
}

// MARK: - 兴趣标签

/// 兴趣导航胶囊。显示真实数量；选中态使用强调色，未选中保持中性。
struct InterestChip: View {
    let title: String
    var count: Int? = nil
    let isSelected: Bool
    let action: () -> Void

    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 5) {
                Text(title)
                    .font(PIHFont.caption.weight(.medium))
                if let count {
                    Text("\(count)")
                        .font(PIHFont.meta)
                        .foregroundStyle(isSelected ? Color.white.opacity(0.85) : Color.secondary)
                }
            }
            .padding(.horizontal, 11)
            .padding(.vertical, 6)
            .foregroundStyle(isSelected ? Color.white : Color.primary)
            .background(
                Capsule().fill(
                    isSelected
                        ? Color.accentColor
                        : (hovering ? PIHColor.hover : PIHColor.surface)
                )
            )
            .overlay(
                Capsule().strokeBorder(
                    isSelected ? Color.clear : PIHColor.hairline,
                    lineWidth: 1
                )
            )
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .accessibilityAddTraits(isSelected ? [.isSelected] : [])
    }
}

/// 推荐卡片中的兴趣与实体标签。
struct InterestTagRow: View {
    let item: FeedItemDTO
    var limit: Int = 4

    var body: some View {
        if !item.matchedInterests.isEmpty || !item.matchedEntities.isEmpty {
            HStack(spacing: 6) {
                ForEach(Array(item.matchedInterests.prefix(limit)), id: \.self) { name in
                    Text(name)
                        .font(PIHFont.meta)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 3)
                        .background(Capsule().fill(PIHColor.accentSoft))
                }
                if !item.matchedEntities.isEmpty {
                    Text("实体：" + item.matchedEntities.prefix(3).joined(separator: "、"))
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
        }
    }
}

// MARK: - 元数据

/// 事件显示关联文章数与独立来源数；文章显示来源名。数量为 0 时不展示。
struct FeedMetaLine: View {
    let item: FeedItemDTO

    var body: some View {
        HStack(spacing: 6) {
            if item.targetType == "event" {
                Text("关联 \(item.articleCount) 篇文章")
                if item.sourceCount > 0 {
                    separator
                    Text("\(item.sourceCount) 个独立来源")
                }
            } else {
                Text(item.sourceName ?? "来源未知")
            }
            separator
            Text(PIHDateFormat.display(item.publishedAt, empty: "发布时间未知"))
            if let category = item.category, !category.isEmpty {
                separator
                Text(category)
            }
            Spacer(minLength: 0)
        }
        .font(PIHFont.meta)
        .foregroundStyle(.secondary)
        .lineLimit(1)
    }

    private var separator: some View {
        Text("·").foregroundStyle(.tertiary)
    }
}

/// 真实推荐理由（来自后端 reason_codes）。数据缺失说明收在评分依据里，
/// 避免每条卡片重复同一段免责声明。
struct RecommendationReasonLine: View {
    let item: FeedItemDTO

    var body: some View {
        Text(PersonalizationCopy.reasonText(item))
            .font(PIHFont.caption)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}

// MARK: - 评分依据

/// 轻量评分依据 Popover：五维分数、权重与未知项说明。
struct ScoreBreakdownPopover: View {
    let item: FeedItemDTO

    private var warnings: Set<String> { Set(item.warnings) }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("评分依据")
                    .font(PIHFont.cardTitle)
                Text("计算于 \(PIHDateFormat.display(item.computedAt, empty: "未知"))")
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
            }
            row("兴趣匹配", item.scoreBreakdown.interest, weight: 0.35,
                unknown: warnings.contains("NO_INTERESTS_CONFIGURED") ? "未配置兴趣" : nil)
            row("重要性", item.scoreBreakdown.importance, weight: 0.25,
                unknown: warnings.contains("EVENT_IMPORTANCE_UNKNOWN") ? "未评估" : nil)
            row("信息新颖性", item.scoreBreakdown.novelty, weight: 0.15, unknown: nil)
            row("来源质量", item.scoreBreakdown.sourceQuality, weight: 0.15,
                unknown: warnings.contains("SOURCE_QUALITY_UNKNOWN") ? "未评估" : nil)
            row("时效性", item.scoreBreakdown.recency, weight: 0.10, unknown: nil)
            if !warnings.isEmpty {
                Divider().overlay(PIHColor.hairline)
                Text(PersonalizationCopy.warningText(item.warnings))
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Divider().overlay(PIHColor.hairline)
            Text("推荐分数代表优先级，不代表事实真实性或可信度。")
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .frame(width: 340)
        .background(PIHColor.surface)
    }

    private func row(
        _ title: String, _ value: Double, weight: Double, unknown: String?
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Text(title)
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
                if let unknown {
                    Text(unknown)
                        .font(PIHFont.meta)
                        .foregroundStyle(PIHColor.warning)
                } else {
                    Text(String(format: "%.0f", value))
                        .font(PIHFont.meta)
                        .monospacedDigit()
                }
                Text("权重 \(Int(weight * 100))%")
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
                    .frame(width: 62, alignment: .trailing)
            }
            ProgressView(value: min(100, max(0, value)), total: 100)
                .progressViewStyle(.linear)
        }
    }
}

// MARK: - 反馈

/// 卡片内的轻量反馈菜单，不占据主要空间。
struct FeedbackMenu: View {
    let activeFeedback: String?
    let isSubmitting: Bool
    let onFeedback: (String) -> Void
    let onRevoke: () -> Void

    private let options: [(String, String)] = [
        ("interested", "感兴趣"),
        ("not_interested", "不感兴趣"),
        ("important", "非常重要"),
        ("duplicate", "重复内容"),
        ("source_disliked", "不喜欢来源"),
        ("later", "暂不处理"),
    ]

    var body: some View {
        if isSubmitting {
            ProgressView().controlSize(.small)
        }
        Menu {
            ForEach(options, id: \.0) { value in
                Button(value.1) { onFeedback(value.0) }
            }
            if activeFeedback != nil {
                Divider()
                Button("撤销反馈", systemImage: "arrow.counterclockwise") { onRevoke() }
            }
        } label: {
            Label(
                activeFeedback.map { PersonalizationStore.feedbackLabel($0) } ?? "反馈",
                systemImage: "hand.thumbsup"
            )
            .font(PIHFont.caption)
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help(activeFeedback.map { "已反馈：\(PersonalizationStore.feedbackLabel($0))" } ?? "记录反馈")
    }
}

/// 统一的推荐操作区：阅读、稍后读、评分依据、反馈。
struct RecommendationActions: View {
    let item: FeedItemDTO
    let activeFeedback: String?
    let isSubmitting: Bool
    let onOpen: () -> Void
    let onLater: () -> Void
    let onFeedback: (String) -> Void
    let onRevoke: () -> Void

    @State private var showBreakdown = false

    var body: some View {
        HStack(spacing: 8) {
            Button(item.targetType == "event" ? "查看事件" : "阅读文章") {
                onOpen()
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)

            if item.targetType == "article" {
                Button {
                    onLater()
                } label: {
                    Label("稍后读", systemImage: "clock")
                        .font(PIHFont.caption)
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .help("加入稍后阅读，并从今日移除")
            }

            Button {
                showBreakdown.toggle()
            } label: {
                Label("评分依据", systemImage: "chart.bar")
                    .font(PIHFont.caption)
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .popover(isPresented: $showBreakdown, arrowEdge: .bottom) {
                ScoreBreakdownPopover(item: item)
            }

            if let activeFeedback {
                Text("已反馈：\(PersonalizationStore.feedbackLabel(activeFeedback))")
                    .font(PIHFont.meta)
                    .foregroundStyle(PIHColor.positive)
            }

            Spacer(minLength: 8)

            Button {
                onFeedback("not_interested")
            } label: {
                Image(systemName: "hand.thumbsdown")
                    .font(PIHFont.caption)
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(isSubmitting || activeFeedback == "not_interested")
            .help("不感兴趣，并从今日移除")
            .accessibilityLabel("不感兴趣")

            FeedbackMenu(
                activeFeedback: activeFeedback,
                isSubmitting: isSubmitting,
                onFeedback: onFeedback,
                onRevoke: onRevoke
            )
        }
    }
}

// MARK: - 卡片悬停

/// 轻柔的卡片悬停描边；不改变布局，不做位移或缩放。
private struct FeedCardHover: ViewModifier {
    @State private var hovering = false

    func body(content: Content) -> some View {
        content
            .overlay(
                RoundedRectangle(cornerRadius: PIHRadius.card, style: .continuous)
                    .strokeBorder(
                        hovering ? Color.accentColor.opacity(0.35) : Color.clear,
                        lineWidth: 1
                    )
            )
            .onHover { hovering = $0 }
    }
}

extension View {
    func feedCardHover() -> some View {
        modifier(FeedCardHover())
    }
}

// MARK: - 卡片

/// 紧凑推荐条目：用于「为你推荐」「独立新闻线索」与折叠分组。
struct RecommendationRow: View {
    let item: FeedItemDTO
    let activeFeedback: String?
    let isSubmitting: Bool
    let onOpen: () -> Void
    let onLater: () -> Void
    let onFeedback: (String) -> Void
    let onRevoke: () -> Void

    var body: some View {
        PIHCard(padding: 16, spacing: 8) {
            header
            Text(item.title ?? "（无标题）")
                .font(PIHFont.cardTitle)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            summary
            InterestTagRow(item: item)
            RecommendationReasonLine(item: item)
            FeedMetaLine(item: item)
            RecommendationActions(
                item: item,
                activeFeedback: activeFeedback,
                isSubmitting: isSubmitting,
                onOpen: onOpen,
                onLater: onLater,
                onFeedback: onFeedback,
                onRevoke: onRevoke
            )
        }
        .feedCardHover()
    }

    private var header: some View {
        HStack(spacing: 8) {
            LevelPill(level: RecommendationLevel(raw: item.level))
            FeedTargetBadge(item: item)
            if item.isFallback {
                StatusPill(text: "重大事件兜底", tint: .purple)
            }
            Spacer(minLength: 0)
            Text("\(Int(item.score.rounded()))")
                .font(.system(size: 16, weight: .semibold))
                .monospacedDigit()
                .foregroundStyle(.secondary)
            Text("分")
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
        }
    }

    @ViewBuilder
    private var summary: some View {
        if let summary = item.summary, !summary.isEmpty {
            Text(summary)
                .font(PIHFont.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// 今日必读主推荐：更大的标题、更完整的摘要，评分退居辅助信息。
struct FeaturedRecommendationCard: View {
    let item: FeedItemDTO
    let activeFeedback: String?
    let isSubmitting: Bool
    let onOpen: () -> Void
    let onLater: () -> Void
    let onFeedback: (String) -> Void
    let onRevoke: () -> Void

    var body: some View {
        PIHCard(padding: 22, spacing: 12) {
            HStack(spacing: 8) {
                LevelPill(level: RecommendationLevel(raw: item.level))
                FeedTargetBadge(item: item)
                if item.isFallback {
                    StatusPill(text: "重大事件兜底", tint: .purple)
                }
                Spacer(minLength: 0)
                Text("\(Int(item.score.rounded()))")
                    .font(.system(size: 18, weight: .semibold))
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                Text("分")
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
            }
            Text(item.title ?? "（无标题）")
                .font(.system(size: 23, weight: .semibold))
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
            if let summary = item.summary, !summary.isEmpty {
                Text(summary)
                    .font(PIHFont.body)
                    .foregroundStyle(.secondary)
                    .lineLimit(4)
                    .fixedSize(horizontal: false, vertical: true)
            }
            InterestTagRow(item: item)
            RecommendationReasonLine(item: item)
            FeedMetaLine(item: item)
            RecommendationActions(
                item: item,
                activeFeedback: activeFeedback,
                isSubmitting: isSubmitting,
                onOpen: onOpen,
                onLater: onLater,
                onFeedback: onFeedback,
                onRevoke: onRevoke
            )
        }
        .overlay(alignment: .leading) {
            RoundedRectangle(cornerRadius: 2, style: .continuous)
                .fill(Color.accentColor)
                .frame(width: 3)
                .padding(.vertical, 20)
                .padding(.leading, 2)
                .accessibilityHidden(true)
        }
        .feedCardHover()
    }
}

/// 事件卡片：突出事件发展与关联规模，而不是像普通文章列表。
struct EventRecommendationCard: View {
    let item: FeedItemDTO
    let activeFeedback: String?
    let isSubmitting: Bool
    let onOpen: () -> Void
    let onLater: () -> Void
    let onFeedback: (String) -> Void
    let onRevoke: () -> Void

    var body: some View {
        PIHCard(padding: 16, spacing: 8) {
            HStack(spacing: 8) {
                LevelPill(level: RecommendationLevel(raw: item.level))
                StatusPill(text: "事件", tint: PIHColor.info)
                if item.isFallback {
                    StatusPill(text: "重大事件兜底", tint: .purple)
                }
                Spacer(minLength: 0)
                Text("重要性 \(Int(item.scoreBreakdown.importance.rounded()))")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                Text("\(Int(item.score.rounded())) 分")
                    .font(PIHFont.meta)
                    .monospacedDigit()
                    .foregroundStyle(.tertiary)
            }
            Text(item.title ?? "（无标题）")
                .font(PIHFont.cardTitle)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            if let summary = item.summary, !summary.isEmpty {
                Text(summary)
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 6) {
                Text("关联 \(item.articleCount) 篇文章")
                if item.sourceCount > 0 {
                    Text("·").foregroundStyle(.tertiary)
                    Text("\(item.sourceCount) 个独立来源")
                }
                if let published = item.publishedAt {
                    Text("·").foregroundStyle(.tertiary)
                    Text("最新 \(PIHDateFormat.display(published, empty: "未知"))")
                }
                Spacer(minLength: 0)
            }
            .font(PIHFont.meta)
            .foregroundStyle(.secondary)
            InterestTagRow(item: item)
            RecommendationReasonLine(item: item)
            RecommendationActions(
                item: item,
                activeFeedback: activeFeedback,
                isSubmitting: isSubmitting,
                onOpen: onOpen,
                onLater: onLater,
                onFeedback: onFeedback,
                onRevoke: onRevoke
            )
        }
        .feedCardHover()
    }
}

/// 单篇独立新闻线索：明确标注类型，避免被误认为多源事件。
struct ArticleLeadCard: View {
    let item: FeedItemDTO
    let activeFeedback: String?
    let isSubmitting: Bool
    let onOpen: () -> Void
    let onLater: () -> Void
    let onFeedback: (String) -> Void
    let onRevoke: () -> Void

    var body: some View {
        RecommendationRow(
            item: item,
            activeFeedback: activeFeedback,
            isSubmitting: isSubmitting,
            onOpen: onOpen,
            onLater: onLater,
            onFeedback: onFeedback,
            onRevoke: onRevoke
        )
    }
}

// MARK: - 阅读预算

/// 今日阅读预算快捷入口。修改后立即刷新真实推荐结果。
struct ReadingBudgetControl: View {
    let currentItems: Int
    var isExplicit: Bool = true
    let isBusy: Bool
    let onSelect: (Int) -> Void

    private let presets = [5, 10, 20]
    @State private var showCustom = false
    @State private var customValue = 20

    var body: some View {
        VStack(alignment: .trailing, spacing: 6) {
            Text(isExplicit ? "今日阅读预算" : "今日阅读预算（默认）")
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
            HStack(spacing: 6) {
                ForEach(presets, id: \.self) { value in
                    Button("\(value) 条") { onSelect(value) }
                        .buttonStyle(.plain)
                        .font(PIHFont.meta.weight(.medium))
                        .foregroundStyle(currentItems == value ? Color.accentColor : Color.secondary)
                        .padding(.horizontal, 9)
                        .padding(.vertical, 4)
                        .background(
                            Capsule().fill(currentItems == value ? PIHColor.accentSoft : Color.clear)
                        )
                        .overlay(
                            Capsule().strokeBorder(
                                currentItems == value
                                    ? Color.accentColor.opacity(0.45)
                                    : PIHColor.hairline,
                                lineWidth: 1
                            )
                        )
                        .disabled(isBusy)
                }
                Button("自定义") {
                    customValue = currentItems
                    showCustom = true
                }
                .buttonStyle(.plain)
                .font(PIHFont.meta.weight(.medium))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 9)
                .padding(.vertical, 4)
                .overlay(Capsule().strokeBorder(PIHColor.hairline, lineWidth: 1))
                .disabled(isBusy)
                .popover(isPresented: $showCustom, arrowEdge: .bottom) {
                    customPopover
                }
            }
        }
    }

    private var customPopover: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("自定义每日阅读预算")
                .font(PIHFont.cardTitle)
            Stepper("每日 \(customValue) 条", value: $customValue, in: 1...100)
            Text("预计阅读约 \(customValue * 4) 分钟（每条约 4 分钟）")
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("应用") {
                    showCustom = false
                    onSelect(customValue)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
            }
        }
        .padding(16)
        .frame(width: 260)
    }
}
