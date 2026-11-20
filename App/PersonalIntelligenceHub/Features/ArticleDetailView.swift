import AppKit
import SwiftUI

/// 文章阅读器：只用 SwiftUI `Text` 渲染服务端纯文本，不使用 WebView/HTML。
/// 原文链接必须由用户点击，且仅允许 http/https。
/// Phase 7.7：重排标题、摘要、正文、AI 分析与来源层级，增加固定操作栏与阅读字号。
struct ArticleDetailView: View {
    @ObservedObject var store: ArticlesStore

    @AppStorage(ReaderTextSize.storageKey) private var textSizeRaw = ReaderTextSize.medium.rawValue
    @State private var isAnalysisExpanded = true

    private var textSize: ReaderTextSize {
        ReaderTextSize(rawValue: textSizeRaw) ?? .medium
    }

    var body: some View {
        Group {
            if let articleID = store.selectedArticleID {
                detailBody(articleID: articleID)
            } else {
                EmptyPanel(
                    icon: "doc.text.magnifyingglass",
                    title: "选择一篇文章",
                    message: "从左侧列表选择文章后，这里会加载标题、摘要与正文。",
                    actionTitle: nil,
                    action: nil
                )
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(PIHColor.canvas)
        .overlay(alignment: .topTrailing) { feedbackToast }
        .animation(.easeOut(duration: 0.18), value: store.actionFeedback)
        .accessibilityElement(children: .contain)
        .task(id: store.selectedArticleID) {
            await store.loadDetail()
            await store.loadAnalysis()
        }
    }

    // MARK: - Body

    @ViewBuilder
    private func detailBody(articleID: String) -> some View {
        if let detail = store.detail, detail.id == articleID {
            VStack(spacing: 0) {
                ArticleReaderToolbar(
                    detail: detail,
                    store: store,
                    textSizeRaw: $textSizeRaw
                )
                reader(detail)
            }
        } else if store.isLoadingDetail {
            LoadingStateView(message: "正在加载文章详情…")
        } else if let message = store.detailErrorMessage {
            EmptyPanel(
                icon: "exclamationmark.triangle",
                title: "文章详情加载失败",
                message: message,
                actionTitle: "重试",
                action: { Task { await store.loadDetail(force: true) } }
            )
        } else {
            LoadingStateView(message: "正在准备文章详情…")
        }
    }

    /// 独立垂直滚动，阅读行宽固定，切换文章时整页不横向跳动。
    private func reader(_ detail: ArticleDetailDTO) -> some View {
        GeometryReader { proxy in
            let layout = ReaderLayout(width: proxy.size.width)
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ArticleReaderHeader(detail: detail, textSize: textSize)

                    if let summary = ArticleReaderText.meaningfulSummary(
                        detail.summary,
                        title: detail.title
                    ) {
                        ArticleSummarySection(summary: summary, textSize: textSize)
                            .padding(.top, 26)
                    }

                    ArticleBodySection(
                        bodyText: ArticleReaderText.bodyRemainder(
                            body: detail.contentText,
                            summary: detail.summary
                        ),
                        contentState: ArticleContentState(rawValue: detail.contentState),
                        originalURL: originalURL(detail),
                        textSize: textSize,
                        isFetchingFullText: store.isFetchingContent,
                        onOpenOriginal: { openOriginal(detail) },
                        onFetchFullText: { Task { await store.fetchSelectedContent() } }
                    )
                    .padding(.top, 30)

                    ArticleAIAnalysisSection(
                        articleID: detail.id,
                        textSize: textSize,
                        store: store,
                        isExpanded: $isAnalysisExpanded
                    )
                    .padding(.top, 30)

                    ArticleSourceSection(
                        detail: detail,
                        onOpenOriginal: { openOriginal(detail) }
                    )
                    .padding(.top, 30)
                }
                .frame(maxWidth: layout.contentWidth, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .center)
                .padding(.horizontal, layout.horizontalPadding)
                .padding(.top, 28)
                .padding(.bottom, 56)
            }
            .id(detail.id)
        }
    }

    // MARK: - Feedback

    @ViewBuilder
    private var feedbackToast: some View {
        if let message = store.actionFeedback {
            HStack(spacing: 8) {
                Image(systemName: store.actionFeedbackIsError
                      ? "exclamationmark.circle.fill"
                      : "checkmark.circle.fill")
                    .font(PIHFont.captionSemibold)
                    .foregroundStyle(store.actionFeedbackIsError ? Color.red : Color.green)
                    .accessibilityHidden(true)
                Text(message)
                    .font(PIHFont.caption)
                    .lineLimit(2)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(.regularMaterial, in: Capsule())
            .overlay(Capsule().strokeBorder(PIHColor.hairline, lineWidth: 1))
            .padding(.top, 58)
            .padding(.trailing, 18)
            .transition(.opacity.combined(with: .move(edge: .top)))
            .accessibilityElement(children: .combine)
            .accessibilityLabel(message)
        }
    }

    // MARK: - Helpers

    private func originalURL(_ detail: ArticleDetailDTO) -> URL? {
        guard let raw = detail.originalUrl else { return nil }
        return Self.safeWebURL(raw)
    }

    private func openOriginal(_ detail: ArticleDetailDTO) {
        guard let url = originalURL(detail) else { return }
        NSWorkspace.shared.open(url)
    }

    /// 仅接受带主机名的 http/https URL，防止 `file:`、`javascript:` 等 scheme。
    static func safeWebURL(_ raw: String) -> URL? {
        guard let url = URL(string: raw),
              let scheme = url.scheme?.lowercased(),
              scheme == "http" || scheme == "https",
              let host = url.host,
              !host.isEmpty
        else {
            return nil
        }
        return url
    }
}
