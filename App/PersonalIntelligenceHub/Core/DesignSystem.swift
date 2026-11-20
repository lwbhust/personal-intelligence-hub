import AppKit
import SwiftUI

// MARK: - Design tokens (Phase 7.0)
//
// 统一字号、间距、圆角与表面色。所有页面的主标题、卡片、辅助信息都应从
// 这里取值，避免各页面出现 10–13 pt 的碎片化字号与不一致的卡片样式。

@MainActor
enum PIHFont {
    /// 页面主标题 28 pt
    static let pageTitle = Font.system(size: 28, weight: .semibold)
    /// 页面副标题 15 pt
    static let pageSubtitle = Font.system(size: 15)
    /// 一级标题 21 pt
    static let sectionTitle = Font.system(size: 21, weight: .semibold)
    /// 二级标题 17 pt
    static let subsectionTitle = Font.system(size: 17, weight: .semibold)
    /// 卡片标题 16 pt
    static let cardTitle = Font.system(size: 16, weight: .semibold)
    /// 正文 15 pt
    static let body = Font.system(size: 15)
    static let bodyMedium = Font.system(size: 15, weight: .medium)
    static let bodySemibold = Font.system(size: 15, weight: .semibold)
    /// 阅读正文 17 pt
    static let readingBody = Font.system(size: 17)
    /// 阅读页主标题 30 pt
    static let readingTitle = Font.system(size: 30, weight: .bold)
    /// 辅助信息 13 pt
    static let caption = Font.system(size: 13)
    static let captionMedium = Font.system(size: 13, weight: .medium)
    /// 次要元数据 12 pt（仅用于时间、ID 等真正次要的信息）
    static let meta = Font.system(size: 12)
    static let metaMono = Font.system(size: 12, design: .monospaced)
    static let mono = Font.system(size: 13, design: .monospaced)
    /// 指标数字
    static let metric = Font.system(size: 34, weight: .bold, design: .rounded)
    static let metricCompact = Font.system(size: 26, weight: .bold, design: .rounded)

    // MARK: - 侧边栏（Phase 7.8 补充）
    static let sideBarSectionTitle = Font.system(size: 15, weight: .bold)
    static let sideBarSubtitle = Font.system(size: 10, weight: .semibold)
    static let sideBarLabel = Font.system(size: 14, weight: .medium)
    static let sideBarLabelRegular = Font.system(size: 14, weight: .regular)
    static let statusBarLabel = Font.system(size: 11, weight: .semibold)

    // MARK: - 图标（Phase 7.8 补充）
    static let iconSmall = Font.system(size: 11, weight: .medium)
    static let iconMedium = Font.system(size: 14, weight: .medium)
    static let iconLarge = Font.system(size: 22, weight: .semibold)
    static let iconXL = Font.system(size: 30, weight: .regular)

    // MARK: - 变体（Phase 7.8 补充）
    static let metaMedium = Font.system(size: 12, weight: .medium)
    static let captionSemibold = Font.system(size: 13, weight: .semibold)
    static let bannerIconSemibold = Font.system(size: 14, weight: .semibold)

    // MARK: - 驾驶舱（Phase 7.8 补充）
    static let dashboardMetricLarge = Font.system(size: 22, weight: .bold, design: .rounded)
}

@MainActor
enum PIHSpacing {
    /// 页面左右边距
    static let page: CGFloat = 28
    /// 页面区块之间
    static let section: CGFloat = 26
    /// 卡片内边距
    static let card: CGFloat = 20
    /// 卡片之间
    static let cardGap: CGFloat = 18
    /// 列表行间距
    static let row: CGFloat = 12
    /// 控件间距
    static let control: CGFloat = 12
    /// 纵向紧凑间距
    static let tight: CGFloat = 6
}

@MainActor
enum PIHRadius {
    static let card: CGFloat = 14
    static let control: CGFloat = 9
    static let row: CGFloat = 10
}

@MainActor
enum PIHColor {
    /// 页面底色
    static let canvas = Color(nsColor: .windowBackgroundColor)
    /// 卡片表面
    static let surface = Color(nsColor: .controlBackgroundColor)
    /// 更亮的输入/代码表面
    static let elevatedSurface = Color(nsColor: .textBackgroundColor)
    /// 柔和分割线
    static let hairline = Color(nsColor: .separatorColor).opacity(0.55)
    /// 选中态底色
    static let selection = Color.accentColor.opacity(0.14)
    /// 悬停态底色
    static let hover = Color.primary.opacity(0.06)
    /// 强调色柔和底色
    static let accentSoft = Color.accentColor.opacity(0.10)

    // MARK: 语义色（Phase 7.3.2）
    //
    // 颜色只表达含义，不用于装饰：信息/主题匹配、积极状态、需要注意、
    // 低优先级与真正的警示。页面不再为每个分类分配独立颜色。

    /// 普通信息、主题匹配
    static let info = Color.blue
    /// 积极状态、已达标
    static let positive = Color.green
    /// 需要注意的变化
    static let warning = Color.orange
    /// 真正的警示/风险
    static let danger = Color.red
    /// 辅助信息与低优先级
    static let neutral = Color.secondary
}

// MARK: - Surfaces

/// 统一卡片表面：圆角 14、内边距 20、极轻描边，不使用阴影。
struct PIHCard<Content: View>: View {
    var padding: CGFloat = PIHSpacing.card
    var spacing: CGFloat = PIHSpacing.row
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: spacing, content: content)
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: PIHRadius.card, style: .continuous)
                    .fill(PIHColor.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: PIHRadius.card, style: .continuous)
                    .strokeBorder(PIHColor.hairline, lineWidth: 1)
            )
    }
}

extension View {
    /// 给现有视图套上统一卡片表面。
    func pihCard(padding: CGFloat = PIHSpacing.card, radius: CGFloat = PIHRadius.card) -> some View {
        self
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .fill(PIHColor.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(PIHColor.hairline, lineWidth: 1)
            )
    }

    /// 列表行的悬停/选中反馈。
    func pihRowBackground(isSelected: Bool = false, radius: CGFloat = PIHRadius.row) -> some View {
        modifier(PIHRowBackground(isSelected: isSelected, radius: radius))
    }
}

private struct PIHRowBackground: ViewModifier {
    let isSelected: Bool
    let radius: CGFloat
    @State private var isHovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .fill(isSelected
                          ? PIHColor.selection
                          : (isHovering ? PIHColor.hover : Color.clear))
            )
            .contentShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
            .onHover { hovering in
                guard hovering != isHovering else { return }
                if reduceMotion {
                    isHovering = hovering
                } else {
                    withAnimation(.easeOut(duration: 0.12)) { isHovering = hovering }
                }
            }
    }
}

// MARK: - Headers

/// 页面头部：28 pt 主标题 + 15 pt 副标题 + 右侧操作区。
struct PageHeader<Trailing: View>: View {
    let title: String
    let subtitle: String?
    @ViewBuilder var trailing: () -> Trailing

    init(
        _ title: String,
        subtitle: String? = nil,
        @ViewBuilder trailing: @escaping () -> Trailing
    ) {
        self.title = title
        self.subtitle = subtitle
        self.trailing = trailing
    }

    var body: some View {
        HStack(alignment: .center, spacing: PIHSpacing.control) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(PIHFont.pageTitle)
                    .foregroundStyle(.primary)
                if let subtitle, !subtitle.isEmpty {
                    Text(subtitle)
                        .font(PIHFont.pageSubtitle)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: PIHSpacing.control)
            trailing()
        }
    }
}

extension PageHeader where Trailing == EmptyView {
    init(_ title: String, subtitle: String? = nil) {
        self.init(title, subtitle: subtitle) { EmptyView() }
    }
}

/// 区块标题：21 pt，可带说明与右侧操作。
struct SectionHeader<Trailing: View>: View {
    let title: String
    let subtitle: String?
    @ViewBuilder var trailing: () -> Trailing

    init(
        _ title: String,
        subtitle: String? = nil,
        @ViewBuilder trailing: @escaping () -> Trailing
    ) {
        self.title = title
        self.subtitle = subtitle
        self.trailing = trailing
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: PIHSpacing.control) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(PIHFont.sectionTitle)
                if let subtitle, !subtitle.isEmpty {
                    Text(subtitle)
                        .font(PIHFont.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: PIHSpacing.control)
            trailing()
        }
    }
}

extension SectionHeader where Trailing == EmptyView {
    init(_ title: String, subtitle: String? = nil) {
        self.init(title, subtitle: subtitle) { EmptyView() }
    }
}

/// 卡片标题行：16 pt 标题 + 图标 + 右侧操作。
struct CardHeader<Trailing: View>: View {
    let title: String
    var icon: String? = nil
    @ViewBuilder var trailing: () -> Trailing

    init(_ title: String, icon: String? = nil, @ViewBuilder trailing: @escaping () -> Trailing) {
        self.title = title
        self.icon = icon
        self.trailing = trailing
    }

    var body: some View {
        HStack(spacing: 8) {
            if let icon {
                Image(systemName: icon)
                    .font(PIHFont.iconMedium)
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
            }
            Text(title)
                .font(PIHFont.cardTitle)
            Spacer(minLength: 8)
            trailing()
        }
    }
}

extension CardHeader where Trailing == EmptyView {
    init(_ title: String, icon: String? = nil) {
        self.init(title, icon: icon) { EmptyView() }
    }
}

// MARK: - Metric card

struct MetricCard: View {
    let title: String
    let value: String
    var subtitle: String? = nil
    let icon: String
    var tint: Color = .accentColor

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(systemName: icon)
                    .font(PIHFont.captionSemibold)
                    .foregroundStyle(tint)
                    .frame(width: 28, height: 28)
                    .background(Circle().fill(tint.opacity(0.12)))
                    .accessibilityHidden(true)
                Text(title)
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
            }
            Text(value)
                .font(PIHFont.metric)
                .monospacedDigit()
                .foregroundStyle(.primary)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            if let subtitle, !subtitle.isEmpty {
                Text(subtitle)
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
        }
        .padding(PIHSpacing.card)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: PIHRadius.card, style: .continuous)
                .fill(PIHColor.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: PIHRadius.card, style: .continuous)
                .strokeBorder(PIHColor.hairline, lineWidth: 1)
        )
    }
}

// MARK: - Loading state

struct LoadingStateView: View {
    let message: String

    var body: some View {
        VStack(spacing: 12) {
            ProgressView()
                .controlSize(.small)
            Text(message)
                .font(PIHFont.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(message)
    }
}

// MARK: - Toolbar container

/// 页面工具栏：统一内边距与底部分割线。
struct PIHPageToolbar<Content: View>: View {
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .padding(.horizontal, PIHSpacing.page)
            .padding(.vertical, 16)
            .background(PIHColor.canvas)
    }
}

// MARK: - Keyword highlight

/// 在标题/摘要中高亮搜索关键词（大小写不敏感）。
struct HighlightedText: View {
    let text: String
    let query: String

    var body: some View {
        Text(attributed)
    }

    private var attributed: AttributedString {
        var result = AttributedString()
        let keyword = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !keyword.isEmpty else { return AttributedString(text) }

        // 纯 ASCII 关键词按词首匹配，避免把 "brain" 中的 "AI" 误当命中。
        let asciiWord = keyword.unicodeScalars.allSatisfy {
            $0.isASCII && (CharacterSet.alphanumerics.contains($0) || $0 == " ")
        }

        var remaining = text[...]
        while let range = remaining.range(
            of: keyword,
            options: [.caseInsensitive, .diacriticInsensitive]
        ) {
            if asciiWord, range.lowerBound > text.startIndex {
                let previous = text[text.index(before: range.lowerBound)]
                if previous.isLetter || previous.isNumber {
                    let next = remaining.index(after: range.lowerBound)
                    result.append(AttributedString(String(remaining[..<next])))
                    remaining = remaining[next...]
                    continue
                }
            }
            result.append(AttributedString(String(remaining[..<range.lowerBound])))
            var highlight = AttributedString(String(remaining[range]))
            highlight.backgroundColor = Color.accentColor.opacity(0.22)
            highlight.foregroundColor = .accentColor
            result.append(highlight)
            remaining = remaining[range.upperBound...]
        }
        result.append(AttributedString(String(remaining)))
        return result
    }
}

// MARK: - Toolbar control style

extension View {
    /// 工具栏中的轻量下拉菜单（筛选/排序）统一外观。
    func pihToolbarMenu() -> some View {
        self
            .menuStyle(.borderlessButton)
            .fixedSize()
    }
}
