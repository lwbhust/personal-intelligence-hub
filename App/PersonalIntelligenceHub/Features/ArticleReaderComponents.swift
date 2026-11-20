import AppKit
import SwiftUI

// MARK: - 阅读字号
//
// Phase 7.7：阅读字号由用户选择并持久化（AppStorage），只影响阅读器内部，
// 不改变全局设计系统的字号梯度。

enum ReaderTextSize: String, CaseIterable, Identifiable {
    case small
    case medium
    case large

    static let storageKey = "pih.reader.text-size"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .small: return "小"
        case .medium: return "中"
        case .large: return "大"
        }
    }

    /// 文章标题 26–30 pt
    var titleFont: Font {
        switch self {
        case .small: return .system(size: 26, weight: .bold)
        case .medium: return .system(size: 28, weight: .bold)
        case .large: return .system(size: 30, weight: .bold)
        }
    }

    /// 模块标题 18–19 pt
    var sectionTitleFont: Font {
        switch self {
        case .small: return .system(size: 18, weight: .semibold)
        case .medium: return .system(size: 18, weight: .semibold)
        case .large: return .system(size: 19, weight: .semibold)
        }
    }

    /// 摘要 16–18 pt
    var summaryFont: Font { .system(size: summarySize) }

    var summarySize: CGFloat {
        switch self {
        case .small: return 16
        case .medium: return 17
        case .large: return 18
        }
    }

    var summaryLineSpacing: CGFloat {
        switch self {
        case .small: return 4
        case .medium: return 6
        case .large: return 8
        }
    }

    var summaryParagraphSpacing: CGFloat {
        switch self {
        case .small: return 10
        case .medium: return 14
        case .large: return 18
        }
    }

    /// 正文 17–19 pt
    var bodyFont: Font { .system(size: bodySize) }

    var bodySize: CGFloat {
        switch self {
        case .small: return 17
        case .medium: return 18
        case .large: return 19
        }
    }

    /// 行间距偏紧凑，段落间距更宽松 → 段/行视觉节奏分明
    var bodyLineSpacing: CGFloat {
        switch self {
        case .small: return 6
        case .medium: return 8
        case .large: return 10
        }
    }

    var bodyParagraphSpacing: CGFloat {
        switch self {
        case .small: return 16
        case .medium: return 22
        case .large: return 28
        }
    }
}

// MARK: - 阅读宽度

/// 根据详情面板实际宽度计算阅读区边距与最大行宽，避免窄窗口下列过窄。
struct ReaderLayout: Equatable {
    let width: CGFloat

    /// 左右边距 20–44 pt
    var horizontalPadding: CGFloat {
        if width < 520 { return 20 }
        if width < 760 { return 32 }
        return 44
    }

    /// 阅读内容最大宽度 760–820 pt
    var contentWidth: CGFloat {
        let available = width - horizontalPadding * 2
        return min(820, max(280, available))
    }
}

// MARK: - 文本处理
//
// 只做排版层面的整理：识别低价值摘要、去掉与摘要重复的正文前缀、
// 在真实句子边界插入段落。绝不虚构、截断或改写原文语义。

enum ArticleReaderText {
    /// 常见「查看原文」占位摘要，整段等于这些内容时视为无摘要。
    private static let placeholderSummaries: Set<String> = [
        "点击查看原文", "点击阅读原文", "查看原文", "阅读原文", "查看全文",
        "查看更多", "更多内容", "全文", "readmore", "readthefullstory",
        "continuereading", "viewarticle", "vieworiginal",
    ]

    private static let abbreviations: Set<String> = [
        "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc",
        "e.g", "i.e", "u.s", "u.k", "fig", "no", "inc", "ltd", "co", "corp",
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    ]

    /// 去掉不可见的排版字符，保留原文可读内容。
    static func displayText(_ raw: String) -> String {
        raw
            .replacingOccurrences(of: "\u{00A0}", with: " ")
            .replacingOccurrences(of: "**", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// 可用于展示的摘要；无有效摘要时返回 nil（界面不显示空模块）。
    static func meaningfulSummary(_ raw: String?, title: String) -> String? {
        guard let text = trimmedOrNil(raw) else { return nil }
        let cleaned = displayText(text)
        guard !isPlaceholder(cleaned) else { return nil }
        guard !isURLOnly(cleaned) else { return nil }
        if normalizedKey(cleaned) == normalizedKey(title) { return nil }
        return cleaned
    }

    /// 去掉与摘要重叠的正文前缀；正文与摘要完全一致或本身无内容时返回 nil。
    static func bodyRemainder(body: String?, summary: String?) -> String? {
        guard let rawBody = trimmedOrNil(body) else { return nil }
        let displayBody = displayText(rawBody)
        guard !isPlaceholder(displayBody), !isURLOnly(displayBody) else { return nil }

        guard let rawSummary = trimmedOrNil(summary) else { return displayBody }
        let key = normalizedKey(displayText(rawSummary))
        let bodyKey = normalizedKey(displayBody)

        if bodyKey == key { return nil }
        guard !key.isEmpty, bodyKey.hasPrefix(key) else { return displayBody }
        guard var splitIndex = indexAfterConsuming(key.count, in: rawBody) else { return displayBody }
        // 摘要末尾的句号/空格不属于正文，跳过它们再取剩余内容。
        while splitIndex < rawBody.endIndex {
            let scalar = rawBody.unicodeScalars[splitIndex]
            let isSeparator = CharacterSet.whitespacesAndNewlines.contains(scalar)
                || CharacterSet.punctuationCharacters.contains(scalar)
            guard isSeparator else { break }
            splitIndex = rawBody.unicodeScalars.index(after: splitIndex)
        }
        let remainder = displayText(String(rawBody[splitIndex...]))
        guard !remainder.isEmpty, !isPlaceholder(remainder) else { return nil }
        return remainder
    }

    /// 将原文拆分为展示用的段落列表。
    ///
    /// 策略（Phase 7.8）：
    /// - 原文有连续空行（`\n\n`）时，空行作为一等段落边界保留作者意图；
    /// - 原文没有空行时（部分抓取源只保留单 `\n` 或连 `\n` 都没有），
    ///   回退到"≥ 60 字或句子结尾"的启发式规则；
    /// - 超长段落再按 targetParagraphLength + 句子边界继续拆分。
    static func paragraphs(from raw: String, targetParagraphLength: Int = 180) -> [String] {
        let normalized = raw
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .replacingOccurrences(of: "\u{00A0}", with: " ")
            .replacingOccurrences(of: "**", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return [] }

        let hasBlankLineSeparator = normalized.contains("\n\n")
        let blocks: [String]

        if hasBlankLineSeparator {
            // 有明确空行 → 以空行为主拆分。
            let rawParagraphs = splitByBlankLines(normalized)
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
            blocks = rawParagraphs.map { block in
                let lines = block.components(separatedBy: "\n")
                    .map { $0.trimmingCharacters(in: .whitespaces) }
                    .filter { !$0.isEmpty }
                guard !lines.isEmpty else { return "" }
                if lines.count == 1 { return lines[0] }
                // 段落内部的单 \n：短行连续出现合并为一行；完整句子行保留换行。
                var merged: [String] = []
                var shortBuffer: [String] = []
                for line in lines {
                    if line.count < 30 && !endsWithSentenceTerminal(line) {
                        shortBuffer.append(line)
                    } else {
                        if !shortBuffer.isEmpty {
                            merged.append(shortBuffer.joined(separator: " · "))
                            shortBuffer.removeAll()
                        }
                        merged.append(line)
                    }
                }
                if !shortBuffer.isEmpty {
                    merged.append(shortBuffer.joined(separator: " · "))
                }
                return merged.joined(separator: "\n")
            }.filter { !$0.isEmpty }
        } else {
            // 没有空行 → 回退：单 \n 或纯长文本，用启发式规则拆。
            let lines = normalized
                .components(separatedBy: "\n")
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
            var collected: [String] = []
            var pending: [String] = []
            for line in lines {
                if line.count >= 60 || endsWithSentenceTerminal(line) {
                    if !pending.isEmpty {
                        collected.append(pending.joined(separator: " "))
                        pending.removeAll()
                    }
                    collected.append(line)
                } else {
                    pending.append(line)
                }
            }
            if !pending.isEmpty {
                collected.append(pending.joined(separator: " · "))
            }
            blocks = collected
        }

        // 超长段落按句子边界进一步拆分。
        var result: [String] = []
        for block in blocks {
            // 块内可能还留有 \n（保留的换行），先展开成独立块再切分
            let subLines = block.components(separatedBy: "\n").filter { !$0.isEmpty }
            for sub in subLines {
                if sub.count <= targetParagraphLength {
                    result.append(sub)
                } else {
                    result.append(contentsOf: groupedSentences(sub, targetLength: targetParagraphLength))
                }
            }
        }
        return result
    }

    // MARK: - Private

    /// 按两个或以上连续换行拆分字符串，保留单个 `\n` 在段内。
    private static func splitByBlankLines(_ text: String) -> [String] {
        var result: [String] = []
        var buffer = ""
        var consecutiveNewlines = 0
        for char in text {
            if char == "\n" {
                if consecutiveNewlines >= 1 {
                    // 已经至少有一个 \n，再来一个 → 段落分隔点
                    result.append(buffer)
                    buffer = ""
                    consecutiveNewlines += 1
                } else {
                    buffer.append(char)
                    consecutiveNewlines = 1
                }
            } else {
                consecutiveNewlines = 0
                buffer.append(char)
            }
        }
        if !buffer.isEmpty {
            result.append(buffer)
        }
        return result
    }

    private static func trimmedOrNil(_ raw: String?) -> String? {
        guard let raw else { return nil }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    /// 占位文本、过短片段、纯链接都不应作为摘要或正文展示。
    private static func isPlaceholder(_ text: String) -> Bool {
        let key = normalizedKey(text)
        if key.isEmpty { return true }
        if key.count < 12 { return true }
        if placeholderSummaries.contains(key) { return true }
        return false
    }

    private static func isURLOnly(_ text: String) -> Bool {
        let key = text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return key.hasPrefix("http://") || key.hasPrefix("https://")
    }

    /// 行尾是否为完整句子的终止标点（可带收尾引号/括号）。
    private static func endsWithSentenceTerminal(_ line: String) -> Bool {
        var characters = Array(line.trimmingCharacters(in: .whitespaces))
        while let last = characters.last, "”’\"'）)】」』》〉".contains(last) {
            characters.removeLast()
        }
        guard let last = characters.last else { return false }
        return "。！？；.!?;".contains(last)
    }

    /// 去空白、去标点、小写，用于比较摘要与正文是否重复。
    private static func normalizedKey(_ text: String) -> String {
        let lowered = text.lowercased()
        var result = ""
        result.reserveCapacity(lowered.count)
        for scalar in lowered.unicodeScalars {
            if CharacterSet.whitespacesAndNewlines.contains(scalar) { continue }
            if CharacterSet.punctuationCharacters.contains(scalar) { continue }
            result.unicodeScalars.append(scalar)
        }
        return result
    }

    /// 在原始文本中前进到「已消费 keyCount 个有效字符」之后的位置。
    private static func indexAfterConsuming(_ keyCount: Int, in text: String) -> String.Index? {
        guard keyCount > 0 else { return text.startIndex }
        var consumed = 0
        var index = text.unicodeScalars.startIndex
        while index < text.unicodeScalars.endIndex {
            let scalar = text.unicodeScalars[index]
            let isCountable = !CharacterSet.whitespacesAndNewlines.contains(scalar)
                && !CharacterSet.punctuationCharacters.contains(scalar)
            if isCountable {
                consumed += 1
                if consumed == keyCount {
                    return text.unicodeScalars.index(after: index)
                }
            }
            index = text.unicodeScalars.index(after: index)
        }
        return nil
    }

    private static func groupedSentences(_ text: String, targetLength: Int) -> [String] {
        let sentences = splitSentences(text)
        guard sentences.count > 1 else { return sentences }

        var paragraphs: [String] = []
        var current = ""
        for sentence in sentences {
            current += sentence
            let trimmed = current.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.count >= targetLength {
                paragraphs.append(trimmed)
                current = ""
            }
        }
        let tail = current.trimmingCharacters(in: .whitespacesAndNewlines)
        if !tail.isEmpty {
            if let last = paragraphs.last, tail.count < 48 {
                paragraphs[paragraphs.count - 1] = join(last, tail)
            } else {
                paragraphs.append(tail)
            }
        }
        return paragraphs
    }

    private static func join(_ left: String, _ right: String) -> String {
        guard let l = left.last, let f = right.first else { return left + right }
        if l.isWhitespace || f.isWhitespace { return left + right }
        if l.isASCII, f.isASCII, l.isLetter || l.isNumber, f.isLetter || f.isNumber {
            return left + " " + right
        }
        return left + right
    }

    private static func splitSentences(_ text: String) -> [String] {
        var result: [String] = []
        var start = text.startIndex
        var index = text.startIndex

        while index < text.endIndex {
            let character = text[index]
            var isBoundary = false
            if "。！？；".contains(character) {
                isBoundary = true
            } else if "!?;".contains(character) {
                isBoundary = true
            } else if character == "." {
                isBoundary = asciiPeriodEndsSentence(text, at: index)
            }

            if isBoundary {
                var end = text.index(after: index)
                while end < text.endIndex, "”’\"'）)】」』》〉".contains(text[end]) {
                    end = text.index(after: end)
                }
                result.append(String(text[start..<end]))
                start = end
                index = end
                continue
            }
            index = text.index(after: index)
        }

        if start < text.endIndex {
            result.append(String(text[start...]))
        }
        return result.filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    private static func asciiPeriodEndsSentence(_ text: String, at index: String.Index) -> Bool {
        guard let word = wordBefore(text, at: index)?.lowercased(), word.count > 1 else { return false }
        if abbreviations.contains(word) { return false }

        var next = text.index(after: index)
        guard next < text.endIndex, text[next].isWhitespace else { return false }
        while next < text.endIndex, text[next].isWhitespace {
            next = text.index(after: next)
        }
        guard next < text.endIndex else { return false }
        let character = text[next]
        return character.isUppercase || isCJK(character) || "“\"「『".contains(character)
    }

    private static func wordBefore(_ text: String, at index: String.Index) -> String? {
        var cursor = index
        var characters: [Character] = []
        while cursor > text.startIndex {
            let previous = text.index(before: cursor)
            let character = text[previous]
            guard character.isLetter || character.isNumber else { break }
            characters.append(character)
            cursor = previous
        }
        guard !characters.isEmpty else { return nil }
        return String(characters.reversed())
    }

    private static func isCJK(_ character: Character) -> Bool {
        guard let scalar = character.unicodeScalars.first else { return false }
        return (0x4E00...0x9FFF).contains(scalar.value)
            || (0x3000...0x303F).contains(scalar.value)
            || (0xFF00...0xFFEF).contains(scalar.value)
    }
}

// MARK: - Chip 流式布局

/// 关键词/实体标签的自动换行布局，避免横向溢出。
struct ReaderFlowLayout: Layout {
    var horizontalSpacing: CGFloat = 8
    var verticalSpacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var rowWidth: CGFloat = 0
        var rowHeight: CGFloat = 0
        var totalHeight: CGFloat = 0
        var widestRow: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            let needed = rowWidth == 0 ? size.width : rowWidth + horizontalSpacing + size.width
            if needed > maxWidth, rowWidth > 0 {
                widestRow = max(widestRow, rowWidth)
                totalHeight += rowHeight + verticalSpacing
                rowWidth = size.width
                rowHeight = size.height
            } else {
                rowWidth = needed
                rowHeight = max(rowHeight, size.height)
            }
        }
        widestRow = max(widestRow, rowWidth)
        totalHeight += rowHeight
        return CGSize(width: min(widestRow, maxWidth), height: totalHeight)
    }

    func placeSubviews(
        in bounds: CGRect,
        proposal: ProposedViewSize,
        subviews: Subviews,
        cache: inout ()
    ) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0
        var rowStart = true

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if !rowStart, x + size.width > bounds.maxX {
                x = bounds.minX
                y += rowHeight + verticalSpacing
                rowHeight = 0
                rowStart = true
            }
            subview.place(
                at: CGPoint(x: x, y: y),
                anchor: .topLeading,
                proposal: ProposedViewSize(width: size.width, height: size.height)
            )
            x += size.width + horizontalSpacing
            rowHeight = max(rowHeight, size.height)
            rowStart = false
        }
    }
}

// MARK: - 阅读区小标题

private struct ReaderSectionTitle: View {
    let title: String
    var accessory: String? = nil
    var font: Font = .system(size: 18, weight: .semibold)

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(title)
                .font(font)
            if let accessory, !accessory.isEmpty {
                Text(accessory)
                    .font(.system(size: 12))
                    .foregroundStyle(.tertiary)
            }
            Spacer(minLength: 0)
        }
        .accessibilityAddTraits(.isHeader)
    }
}

private struct ReaderChip: View {
    let text: String
    var tint: Color = .secondary

    var body: some View {
        Text(text)
            .font(.system(size: 12, weight: .medium))
            .lineLimit(1)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .foregroundStyle(tint)
            .background(Capsule().fill(tint.opacity(0.10)))
    }
}

// MARK: - 标题区

struct ArticleReaderHeader: View {
    let detail: ArticleDetailDTO
    let textSize: ReaderTextSize

    private var status: ReadingStatus {
        ReadingStatus(rawValue: detail.readingStatus) ?? .unread
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(detail.title)
                .font(textSize.titleFont)
                .foregroundStyle(.primary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)

            metaLine
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var metaLine: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) {
                metaItems
            }
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 8) {
                    sourceName
                    categoryName
                }
                HStack(spacing: 8) {
                    published
                    statusBadge
                    favoriteBadge
                }
            }
        }
    }

    @ViewBuilder
    private var metaItems: some View {
        sourceName
        dot
        categoryName
        if let category = detail.categoryName, !category.isEmpty {
            dot
        }
        published
        if let updated = detail.sourceUpdatedAt, !updated.isEmpty, updated != detail.publishedAt {
            dot
            Text("更新于 \(PIHDateFormat.display(updated))")
                .lineLimit(1)
        }
        statusBadge
        favoriteBadge
    }

    private var sourceName: some View {
        Text(detail.sourceName ?? "未知来源")
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(.primary)
            .lineLimit(1)
    }

    @ViewBuilder
    private var categoryName: some View {
        if let category = detail.categoryName, !category.isEmpty {
            Text(category)
                .lineLimit(1)
        }
    }

    private var published: some View {
        Text(PIHDateFormat.display(detail.publishedAt, empty: "发布时间未知"))
            .monospacedDigit()
            .lineLimit(1)
    }

    private var statusBadge: some View {
        Label(status.label, systemImage: statusIcon)
            .font(.system(size: 12))
            .foregroundStyle(.secondary)
            .lineLimit(1)
            .help("当前阅读状态：\(status.label)")
    }

    @ViewBuilder
    private var favoriteBadge: some View {
        if detail.isFavorite {
            Label("已收藏", systemImage: "star.fill")
                .font(.system(size: 12))
                .foregroundStyle(.yellow)
                .lineLimit(1)
        }
    }

    private var dot: some View {
        Text("·")
            .foregroundStyle(.tertiary)
    }

    private var statusIcon: String {
        switch status {
        case .unread: return "circle"
        case .reading: return "book"
        case .read: return "checkmark.circle"
        case .later: return "bookmark"
        }
    }
}

// MARK: - 摘要区

struct ArticleSummarySection: View {
    let summary: String
    let textSize: ReaderTextSize

    private var paragraphs: [String] {
        ArticleReaderText.paragraphs(from: summary, targetParagraphLength: 190)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            ReaderSectionTitle(
                title: "摘要",
                accessory: "来自信息源",
                font: textSize.sectionTitleFont
            )

            VStack(alignment: .leading, spacing: textSize.summaryParagraphSpacing) {
                ForEach(Array(paragraphs.enumerated()), id: \.offset) { _, paragraph in
                    Text(paragraph)
                        .font(textSize.summaryFont)
                        .lineSpacing(textSize.summaryLineSpacing)
                        .foregroundStyle(.primary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(PIHColor.surface)
        )
    }
}

// MARK: - 正文区

struct ArticleBodySection: View {
    let bodyText: String?
    let contentState: ArticleContentState?
    let originalURL: URL?
    let textSize: ReaderTextSize
    var isFetchingFullText: Bool = false
    var onOpenOriginal: () -> Void
    var onFetchFullText: (() -> Void)? = nil

    private var paragraphs: [String] {
        guard let bodyText else { return [] }
        return ArticleReaderText.paragraphs(from: bodyText, targetParagraphLength: 260)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            ReaderSectionTitle(
                title: "正文",
                accessory: contentState?.label,
                font: textSize.sectionTitleFont
            )

            if paragraphs.isEmpty {
                emptyState
            } else {
                VStack(alignment: .leading, spacing: textSize.bodyParagraphSpacing) {
                    ForEach(Array(paragraphs.enumerated()), id: \.offset) { _, paragraph in
                        Text(paragraph)
                            .font(textSize.bodyFont)
                            .lineSpacing(textSize.bodyLineSpacing)
                            .foregroundStyle(.primary)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var emptyState: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "doc.text")
                .font(.system(size: 15, weight: .regular))
                .foregroundStyle(.secondary)
                .frame(width: 32, height: 32)
                .background(Circle().fill(Color.secondary.opacity(0.10)))
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 4) {
                Text("暂无可阅读的正文内容")
                    .font(.system(size: 14, weight: .medium))
                Text(emptyExplanation)
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 8)

            if let onFetchFullText, contentState == .summaryOnly {
                Button {
                    onFetchFullText()
                } label: {
                    if isFetchingFullText {
                        ProgressView().controlSize(.small)
                    } else {
                        Label("抓取全文", systemImage: "arrow.down.doc")
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .disabled(isFetchingFullText)
                .help("从原文地址抓取正文，遵守 robots.txt 与请求频率限制")
            }

            if originalURL != nil {
                Button("阅读原文", action: onOpenOriginal)
                    .buttonStyle(.bordered)
                    .controlSize(.small)
            }
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color.secondary.opacity(0.06))
        )
    }

    private var emptyExplanation: String {
        switch contentState {
        case .summaryOnly:
            return "该信息源仅提供摘要。可尝试抓取全文，失败时会继续保留摘要。"
        case .unavailable:
            return "该信息源未提供摘要或正文，请阅读原文查看完整内容。"
        case .full, .none:
            return "服务端未返回可读的正文纯文本，完整内容请阅读原文。"
        }
    }
}

// MARK: - AI 分析区

struct ArticleAIAnalysisSection: View {
    let articleID: String
    let textSize: ReaderTextSize
    @ObservedObject var store: ArticlesStore
    @Binding var isExpanded: Bool

    private var analysis: AIAnalysisDTO? {
        guard store.analysisArticleID == articleID else { return nil }
        return store.analysisItems.first
    }

    private var isLoading: Bool {
        store.isLoadingAnalysis && store.analysisArticleID != articleID
    }

    private var showsLoading: Bool {
        isLoading || (store.isAnalyzing && store.selectedArticleID == articleID)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header

            if isExpanded {
                if let analysis {
                    analysisContent(analysis)
                } else if showsLoading {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text(store.isAnalyzing ? "正在调用本地模型分析本文…" : "正在读取分析结果…")
                            .font(.system(size: 13))
                            .foregroundStyle(.secondary)
                    }
                } else {
                    notAnalyzed
                }

                if let notice = store.analysisNotice, store.selectedArticleID == articleID {
                    Text(notice)
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let message = store.analysisErrorMessage, store.analysisArticleID == articleID {
                    Text(message)
                        .font(.system(size: 12))
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(PIHColor.surface.opacity(0.85))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(PIHColor.hairline, lineWidth: 1)
        )
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "sparkles")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            Text("AI 辅助分析")
                .font(.system(size: 16, weight: .semibold))
            Text("本地模型")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 7)
                .padding(.vertical, 2)
                .background(Capsule().fill(Color.secondary.opacity(0.10)))

            if showsLoading {
                ProgressView().controlSize(.small)
            }

            Spacer(minLength: 8)

            Button {
                withAnimation(.easeInOut(duration: 0.16)) { isExpanded.toggle() }
            } label: {
                Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 22, height: 22)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help(isExpanded ? "收起 AI 分析" : "展开 AI 分析")
            .accessibilityLabel(isExpanded ? "收起 AI 分析" : "展开 AI 分析")
        }
    }

    private var notAnalyzed: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("本文尚未分析")
                    .font(.system(size: 14))
                Text("由本机 Ollama 模型生成，仅作辅助阅读，不构成事实来源。")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            Button {
                Task { await store.analyzeSelectedArticle() }
            } label: {
                Label("分析本文", systemImage: "sparkles")
                    .font(.system(size: 12))
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(store.isAnalyzing)
        }
    }

    @ViewBuilder
    private func analysisContent(_ analysis: AIAnalysisDTO) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .center, spacing: 8) {
                ReaderChip(text: analysis.category, tint: .accentColor)
                Text("主题分类")
                    .font(.system(size: 11))
                    .foregroundStyle(.tertiary)
                Spacer(minLength: 0)
            }

            let analysisParagraphs = ArticleReaderText.paragraphs(
                from: analysis.summary,
                targetParagraphLength: 220
            )
            VStack(alignment: .leading, spacing: 12) {
                ForEach(Array(analysisParagraphs.enumerated()), id: \.offset) { _, paragraph in
                    Text(paragraph)
                        .font(.system(size: textSize.summarySize - 1))
                        .lineSpacing(textSize.summaryLineSpacing)
                        .foregroundStyle(.primary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            if !analysis.keywords.isEmpty {
                labeledChips(title: "关键词", items: analysis.keywords, limit: 8)
            }
            if !analysis.entities.isEmpty {
                labeledChips(
                    title: "涉及实体",
                    items: analysis.entities.map { "\($0.name)（\($0.type)）" },
                    limit: 10
                )
            }

            analysisFooter(analysis)
        }
    }

    private func labeledChips(title: String, items: [String], limit: Int) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.secondary)
            ReaderFlowLayout(horizontalSpacing: 6, verticalSpacing: 6) {
                ForEach(Array(items.prefix(limit).enumerated()), id: \.offset) { _, item in
                    ReaderChip(text: item)
                }
                if items.count > limit {
                    ReaderChip(text: "+\(items.count - limit)")
                }
            }
        }
    }

    private func analysisFooter(_ analysis: AIAnalysisDTO) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Divider().overlay(PIHColor.hairline)

            Text(
                "\(analysis.modelName) · \(PIHDateFormat.display(analysis.createdAt))"
                    + " · 置信度 \(String(format: "%.2f", analysis.confidence))"
            )
            .font(.system(size: 12))
            .foregroundStyle(.tertiary)
            .fixedSize(horizontal: false, vertical: true)

            DisclosureGroup {
                Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                    GridRow {
                        Text("模型 / Prompt").foregroundStyle(.secondary)
                        Text("\(analysis.modelName) · \(analysis.promptVersion)")
                            .textSelection(.enabled)
                    }
                    GridRow {
                        Text("校验置信度").foregroundStyle(.secondary)
                        Text(String(format: "%.2f", analysis.confidence))
                    }
                    GridRow {
                        Text("耗时 / 输入").foregroundStyle(.secondary)
                        Text("\(PIHDuration.display(analysis.durationMs)) · \(analysis.inputChars) 字符")
                    }
                    GridRow {
                        Text("分析时间").foregroundStyle(.secondary)
                        Text(PIHDateFormat.display(analysis.createdAt))
                    }
                }
                .font(.system(size: 12))
                .padding(.top, 6)
            } label: {
                Text("分析详情")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }

            Text("以上内容由本地模型生成，仅作辅助阅读，不构成事实来源。")
                .font(.system(size: 11))
                .foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

// MARK: - 来源与元数据

struct ArticleSourceSection: View {
    let detail: ArticleDetailDTO
    var onOpenOriginal: () -> Void

    private var url: URL? {
        guard let raw = detail.originalUrl else { return nil }
        return ArticleDetailView.safeWebURL(raw)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ReaderSectionTitle(title: "来源与原文", font: .system(size: 16, weight: .semibold))

            HStack(alignment: .center, spacing: 8) {
                Label(detail.sourceName ?? "未知来源", systemImage: "globe")
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Spacer(minLength: 8)
                if url != nil {
                    Button {
                        onOpenOriginal()
                    } label: {
                        Label("打开原文", systemImage: "safari")
                            .font(.system(size: 12))
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .accessibilityLabel("在浏览器中打开原文")
                }
            }

            if let raw = detail.originalUrl, !raw.isEmpty {
                if url != nil {
                    Text(raw)
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .textSelection(.enabled)
                        .help(raw)
                } else {
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: "link.badge.plus")
                            .foregroundStyle(.orange)
                            .accessibilityHidden(true)
                        Text("原文链接不是 http/https，已阻止打开：\(raw)")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }

            metadataDisclosure
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var metadataDisclosure: some View {
        DisclosureGroup {
            Grid(alignment: .leading, horizontalSpacing: 20, verticalSpacing: 8) {
                metadataRow("来源", detail.sourceName ?? "—")
                metadataRow("作者", detail.author ?? "—")
                metadataRow("发布时间", PIHDateFormat.display(detail.publishedAt, empty: "来源未提供"))
                metadataRow("采集时间", PIHDateFormat.display(detail.fetchedAt))
                metadataRow("来源更新时间", PIHDateFormat.display(detail.sourceUpdatedAt, empty: "—"))
                metadataRow("内容状态", ArticleContentState(rawValue: detail.contentState)?.label ?? detail.contentState)
                metadataRow("文章状态", detail.status == "archived" ? "已归档" : "有效文章")
                metadataRow("阅读状态", ReadingStatus(rawValue: detail.readingStatus)?.label ?? detail.readingStatus)
                metadataRow("阅读次数", "\(detail.readCount)")
                if let lastRead = detail.lastReadAt, !lastRead.isEmpty {
                    metadataRow("最近阅读", PIHDateFormat.display(lastRead))
                }
            }
            .font(.system(size: 12))
            .padding(.top, 10)
        } label: {
            Text("文章信息")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
        }
    }

    private func metadataRow(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label)
                .foregroundStyle(.secondary)
                .gridColumnAlignment(.leading)
            Text(value)
                .textSelection(.enabled)
                .gridColumnAlignment(.leading)
        }
    }
}

// MARK: - 阅读工具栏

struct ArticleReaderToolbar: View {
    let detail: ArticleDetailDTO
    @ObservedObject var store: ArticlesStore
    @Binding var textSizeRaw: String

    private var url: URL? {
        guard let raw = detail.originalUrl else { return nil }
        return ArticleDetailView.safeWebURL(raw)
    }

    private var status: ReadingStatus {
        ReadingStatus(rawValue: detail.readingStatus) ?? .unread
    }

    var body: some View {
        HStack(spacing: 8) {
            favoriteButton
            statusMenu
            analyzeButton

            Spacer(minLength: 8)

            if url != nil {
                Button {
                    openOriginal()
                } label: {
                    Label("原文", systemImage: "safari")
                        .font(.system(size: 12))
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .help("在浏览器中打开原文")
            }

            textSizeMenu
            moreMenu
        }
        .padding(.horizontal, 16)
        .frame(height: 48)
        .background(PIHColor.canvas)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(PIHColor.hairline)
                .frame(height: 1)
        }
    }

    private var favoriteButton: some View {
        Button {
            Task { await store.toggleSelectedFavorite() }
        } label: {
            Label(
                detail.isFavorite ? "已收藏" : "收藏",
                systemImage: detail.isFavorite ? "star.fill" : "star"
            )
            .font(.system(size: 12))
            .foregroundStyle(detail.isFavorite ? Color.yellow : Color.primary)
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
        .help(detail.isFavorite ? "取消收藏" : "收藏")
    }

    private var statusMenu: some View {
        Menu {
            ForEach([ReadingStatus.unread, .read, .later], id: \.self) { item in
                Button {
                    Task { await store.setSelectedReadingStatus(item) }
                } label: {
                    Label(item.label, systemImage: icon(for: item))
                }
            }
        } label: {
            Label(status.label, systemImage: icon(for: status))
                .font(.system(size: 12))
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help("切换阅读状态")
    }

    private var analyzeButton: some View {
        Button {
            Task { await store.analyzeSelectedArticle() }
        } label: {
            Label("分析", systemImage: "sparkles")
                .font(.system(size: 12))
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
        .disabled(store.isAnalyzing)
        .help("使用本机 Ollama 分析本文")
    }

    private var textSizeMenu: some View {
        Menu {
            Picker("阅读字号", selection: $textSizeRaw) {
                ForEach(ReaderTextSize.allCases) { size in
                    Text(size.label).tag(size.rawValue)
                }
            }
            .pickerStyle(.inline)
        } label: {
            Image(systemName: "textformat.size")
                .font(.system(size: 12))
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help("调整阅读字号")
        .accessibilityLabel("调整阅读字号")
    }

    private var moreMenu: some View {
        Menu {
            Button {
                copy(detail.title, label: "标题")
            } label: {
                Label("复制标题", systemImage: "doc.on.clipboard")
            }

            Button {
                if let raw = detail.originalUrl { copy(raw, label: "原文链接") }
            } label: {
                Label("复制原文链接", systemImage: "link")
            }
            .disabled(detail.originalUrl == nil)

            Divider()

            Menu {
                Button("感兴趣", systemImage: "hand.thumbsup") {
                    Task { await store.submitPersonalFeedback("interested") }
                }
                Button("不感兴趣", systemImage: "hand.thumbsdown") {
                    Task { await store.submitPersonalFeedback("not_interested") }
                }
                Button("非常重要", systemImage: "pin") {
                    Task { await store.submitPersonalFeedback("important") }
                }
                Button("重复内容", systemImage: "doc.on.doc") {
                    Task { await store.submitPersonalFeedback("duplicate") }
                }
                Button("不喜欢来源", systemImage: "nosign") {
                    Task { await store.submitPersonalFeedback("source_disliked") }
                }
                Button("暂不处理", systemImage: "clock") {
                    Task { await store.submitPersonalFeedback("later") }
                }
            } label: {
                Label("兴趣反馈", systemImage: "sparkles")
            }
        } label: {
            Image(systemName: "ellipsis.circle")
                .font(.system(size: 13))
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help("更多操作")
        .accessibilityLabel("更多操作")
    }

    private func icon(for status: ReadingStatus) -> String {
        switch status {
        case .unread: return "circle"
        case .reading: return "book"
        case .read: return "checkmark.circle"
        case .later: return "bookmark"
        }
    }

    private func openOriginal() {
        guard let url else { return }
        NSWorkspace.shared.open(url)
    }

    private func copy(_ text: String, label: String) {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
        store.showActionFeedback("已复制\(label)", isError: false)
    }
}
