import XCTest
@testable import PersonalIntelligenceHub

/// Phase 7.7 阅读器文本处理测试。
/// 覆盖：占位摘要识别、摘要/正文去重、句子边界分段、字号与阅读宽度。
final class ArticleReaderTextTests: XCTestCase {

    // MARK: - 摘要有效性

    func testPlaceholderSummaryIsRejected() {
        XCTAssertNil(ArticleReaderText.meaningfulSummary("点击查看原文>", title: "某篇文章"))
        XCTAssertNil(ArticleReaderText.meaningfulSummary("阅读原文", title: "某篇文章"))
        XCTAssertNil(ArticleReaderText.meaningfulSummary("  Read more  ", title: "某篇文章"))
        XCTAssertNil(ArticleReaderText.meaningfulSummary("https://example.com/post", title: "某篇文章"))
        XCTAssertNil(ArticleReaderText.meaningfulSummary("", title: "某篇文章"))
        XCTAssertNil(ArticleReaderText.meaningfulSummary(nil, title: "某篇文章"))
    }

    func testSummaryEqualToTitleIsRejected() {
        let title = "腾讯轻量云 LoopForge 云端 Loop 实践"
        XCTAssertNil(ArticleReaderText.meaningfulSummary(title, title: title))
    }

    func testRealSummaryIsKept() {
        let summary = "As Democrats prepare to take control of the Senate, the minority leader faces a leadership challenge."
        XCTAssertEqual(ArticleReaderText.meaningfulSummary(summary, title: "Senate leadership"), summary)
    }

    func testShortFragmentIsRejected() {
        XCTAssertNil(ArticleReaderText.meaningfulSummary("短讯", title: "标题"))
    }

    // MARK: - 正文去重

    func testBodyEqualSummaryIsRemoved() {
        let text = "This is the same abstract text used by the source."
        XCTAssertNil(ArticleReaderText.bodyRemainder(body: text, summary: text))
    }

    func testBodyPrefixOverlappingSummaryIsTrimmed() {
        let summary = "The rover found bright rocks."
        let body = "The rover found bright rocks. The team then analysed the samples for weeks."
        let remainder = ArticleReaderText.bodyRemainder(body: body, summary: summary)
        XCTAssertEqual(remainder, "The team then analysed the samples for weeks.")
    }

    func testBodyWithoutSummaryIsKept() {
        let body = "A full article body that is long enough to be meaningful."
        XCTAssertEqual(ArticleReaderText.bodyRemainder(body: body, summary: nil), body)
    }

    func testPlaceholderBodyIsRejected() {
        XCTAssertNil(ArticleReaderText.bodyRemainder(body: "点击查看原文>", summary: "点击查看原文>"))
        XCTAssertNil(ArticleReaderText.bodyRemainder(body: nil, summary: "summary"))
    }

    func testMarkupIsRemovedForDisplay() {
        let body = "The **Idubi** rocks are bright."
        XCTAssertEqual(
            ArticleReaderText.bodyRemainder(body: body, summary: nil),
            "The Idubi rocks are bright."
        )
    }

    // MARK: - 分段

    func testParagraphsPreserveAllContent() {
        let text = """
        First paragraph with enough text to be meaningful.

        Second paragraph also has content.
        """
        let paragraphs = ArticleReaderText.paragraphs(from: text)
        XCTAssertEqual(paragraphs.count, 2)
        XCTAssertEqual(paragraphs[0], "First paragraph with enough text to be meaningful.")
        XCTAssertEqual(paragraphs[1], "Second paragraph also has content.")
    }

    func testLongEnglishParagraphSplitsAtSentenceBoundary() {
        let sentenceA = "The Perseverance rover has been exploring the Jezero crater for several years."
        let sentenceB = "Its instruments detected bright rocks that may preserve signs of ancient water."
        let sentenceC = "Scientists will continue to study these samples in the coming months."
        let text = "\(sentenceA) \(sentenceB) \(sentenceC)"

        let paragraphs = ArticleReaderText.paragraphs(from: text, targetParagraphLength: 90)
        XCTAssertGreaterThan(paragraphs.count, 1)
        XCTAssertEqual(
            ArticleReaderText.paragraphs(from: paragraphs.joined(separator: " "), targetParagraphLength: 90)
                .joined(separator: " "),
            text
        )
        for paragraph in paragraphs {
            XCTAssertTrue(text.contains(paragraph), "分段不得改写原文：\(paragraph)")
        }
    }

    func testChineseParagraphSplitsAtSentenceBoundary() {
        let text = "直立人是生存年代最长的古人类物种之一。此前华南地区的化石记录长期存在空白。本次发现的化石有望填补这一空白。研究团队将继续开展年代测定工作。"
        let paragraphs = ArticleReaderText.paragraphs(from: text, targetParagraphLength: 24)
        XCTAssertGreaterThan(paragraphs.count, 1)
        XCTAssertEqual(paragraphs.joined(), text)
    }

    func testAbbreviationDoesNotCreateParagraphBreak() {
        let text = "The U.S. Geological Survey published the dataset today."
        let paragraphs = ArticleReaderText.paragraphs(from: text, targetParagraphLength: 20)
        XCTAssertEqual(paragraphs.count, 1)
        XCTAssertEqual(paragraphs.first, text)
    }

    func testEmptyTextProducesNoParagraphs() {
        XCTAssertTrue(ArticleReaderText.paragraphs(from: "   \n\n  ").isEmpty)
    }

    // MARK: - 阅读设置

    func testReaderTextSizeOrdering() {
        XCTAssertLessThan(ReaderTextSize.small.bodySize, ReaderTextSize.medium.bodySize)
        XCTAssertLessThan(ReaderTextSize.medium.bodySize, ReaderTextSize.large.bodySize)
        XCTAssertEqual(ReaderTextSize.allCases.count, 3)
    }

    func testReaderLayoutAdaptsToWidth() {
        let narrow = ReaderLayout(width: 420)
        let wide = ReaderLayout(width: 1200)

        XCTAssertLessThan(narrow.horizontalPadding, wide.horizontalPadding)
        XCTAssertLessThanOrEqual(wide.contentWidth, 820)
        XCTAssertGreaterThan(narrow.contentWidth, 0)
    }
}
