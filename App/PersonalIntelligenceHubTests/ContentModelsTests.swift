import XCTest
@testable import PersonalIntelligenceHub

/// Phase 2 文章/采集任务读模型与展示规则测试。
/// 重点覆盖：可空字段、items 缺失容错、未知状态值、ISO8601 回退。
final class ContentModelsTests: XCTestCase {

    private func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    // MARK: - Articles

    func testDecodesArticlePageWithNullsAndUnknownFields() throws {
        let json = """
        {
          "items": [
            {
              "id": "a-1",
              "source_id": "s-1",
              "source_name": "Example Feed",
              "category_id": null,
              "category_name": null,
              "title": "Hello",
              "author": null,
              "summary": "summary",
              "canonical_url": "https://example.com/post",
              "content_state": "summary_only",
              "published_at": null,
              "fetched_at": "2026-11-16T08:00:00.123Z",
              "status": "active",
              "created_at": "2026-11-16T08:00:00.123Z",
              "updated_at": "2026-11-16T08:00:00.123Z",
              "unexpected_future_field": "ignored"
            }
          ],
          "total": 1,
          "limit": 30,
          "offset": 0
        }
        """
        let page = try decoder().decode(ArticlePage.self, from: Data(json.utf8))
        XCTAssertEqual(page.total, 1)
        let article = try XCTUnwrap(page.items.first)
        XCTAssertEqual(article.sourceName, "Example Feed")
        XCTAssertNil(article.categoryId)
        XCTAssertNil(article.author)
        XCTAssertNil(article.publishedAt)
        XCTAssertEqual(article.contentState, "summary_only")
        XCTAssertEqual(ArticleContentState(rawValue: article.contentState), .summaryOnly)
        XCTAssertEqual(
            ArticleContentState(rawValue: article.contentState)?.label,
            "仅摘要"
        )
    }

    func testDecodesArticleDetailIncludingPlainText() throws {
        let json = """
        {
          "id": "a-1",
          "source_id": "s-1",
          "source_name": null,
          "category_id": "c-1",
          "category_name": "Tech",
          "title": "Hello",
          "author": "Alice",
          "summary": null,
          "canonical_url": null,
          "content_state": "full",
          "published_at": "2026-11-16T08:00:00.000Z",
          "fetched_at": "2026-11-16T09:00:00.000Z",
          "status": "archived",
          "created_at": "2026-11-16T09:00:00.000Z",
          "updated_at": "2026-11-16T09:00:00.000Z",
          "external_id": "guid-1",
          "original_url": "https://example.com/post",
          "content_text": "纯文本正文",
          "source_updated_at": null,
          "content_hash": "0123456789abcdef"
        }
        """
        let detail = try decoder().decode(ArticleDetailDTO.self, from: Data(json.utf8))
        XCTAssertEqual(detail.contentText, "纯文本正文")
        XCTAssertEqual(detail.originalUrl, "https://example.com/post")
        XCTAssertNil(detail.sourceName)
        XCTAssertNil(detail.sourceUpdatedAt)
        XCTAssertEqual(detail.contentHash, "0123456789abcdef")
    }

    func testUnknownContentStateKeepsRawValueAndFallsBackToRawLabel() {
        XCTAssertNil(ArticleContentState(rawValue: "video"))
        XCTAssertEqual(ArticleContentState.full.label, "完整正文")
        XCTAssertEqual(ArticleContentState.unavailable.label, "无正文")
    }

    // MARK: - Collection jobs

    func testJobDecodesWhenItemsAreMissing() throws {
        let json = """
        {
          "id": "job-1",
          "trigger_type": "manual",
          "scope": "all_enabled",
          "status": "running",
          "requested_source_count": 2,
          "processed_source_count": 1,
          "succeeded_source_count": 1,
          "failed_source_count": 0,
          "discovered_count": 30,
          "inserted_count": 12,
          "updated_count": 0,
          "duplicate_count": 18,
          "error_count": 0,
          "error_message": null,
          "cancel_requested": false,
          "started_at": "2026-11-16T08:00:00.000Z",
          "finished_at": null,
          "duration_ms": null,
          "created_at": "2026-11-16T08:00:00.000Z",
          "updated_at": "2026-11-16T08:00:00.000Z"
        }
        """
        let job = try decoder().decode(CollectionJobDTO.self, from: Data(json.utf8))
        XCTAssertEqual(job.items, [])
        XCTAssertEqual(job.status, "running")
        XCTAssertEqual(CollectionJobStatus(rawValue: job.status)?.isActive, true)
        XCTAssertNil(job.finishedAt)
        XCTAssertNil(job.durationMs)
        XCTAssertFalse(job.cancelRequested)
    }

    func testJobDecodesItemsAndUnknownStatuses() throws {
        let json = """
        {
          "id": "job-1",
          "trigger_type": "manual",
          "scope": "single_source",
          "status": "future_status",
          "requested_source_count": 1,
          "processed_source_count": 1,
          "succeeded_source_count": 0,
          "failed_source_count": 1,
          "discovered_count": 5,
          "inserted_count": 0,
          "updated_count": 0,
          "duplicate_count": 0,
          "error_count": 1,
          "error_message": "采集失败（已脱敏）",
          "cancel_requested": true,
          "started_at": "2026-11-16T08:00:00.000Z",
          "finished_at": "2026-11-16T08:00:01.000Z",
          "duration_ms": 1000,
          "created_at": "2026-11-16T08:00:00.000Z",
          "updated_at": "2026-11-16T08:00:01.000Z",
          "items": [
            {
              "id": "item-1",
              "job_id": "job-1",
              "source_id": "s-1",
              "source_name": "Example",
              "status": "skipped",
              "http_status": 503,
              "discovered_count": 0,
              "inserted_count": 0,
              "updated_count": 0,
              "duplicate_count": 0,
              "error_count": 1,
              "error_code": "http_server_error",
              "error_message": "服务器错误",
              "started_at": "2026-11-16T08:00:00.000Z",
              "finished_at": "2026-11-16T08:00:00.500Z",
              "duration_ms": 500
            }
          ]
        }
        """
        let job = try decoder().decode(CollectionJobDTO.self, from: Data(json.utf8))
        XCTAssertEqual(job.status, "future_status")
        XCTAssertNil(CollectionJobStatus(rawValue: job.status))
        XCTAssertEqual(job.items.count, 1)
        let item = try XCTUnwrap(job.items.first)
        XCTAssertEqual(item.httpStatus, 503)
        XCTAssertEqual(item.errorCode, "http_server_error")
        XCTAssertEqual(CollectionJobItemStatus(rawValue: item.status), .skipped)
        XCTAssertEqual(CollectionJobItemStatus.label(for: item.status), "已跳过")
        XCTAssertEqual(CollectionJobStatus.label(for: job.status), "future_status")
    }

    func testCollectResponseDecodesNullItem() throws {
        let json = """
        {
          "job": {
            "id": "job-1",
            "trigger_type": "manual",
            "scope": "single_source",
            "status": "pending",
            "requested_source_count": 1,
            "processed_source_count": 0,
            "succeeded_source_count": 0,
            "failed_source_count": 0,
            "discovered_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "duplicate_count": 0,
            "error_count": 0,
            "error_message": null,
            "cancel_requested": false,
            "started_at": null,
            "finished_at": null,
            "duration_ms": null,
            "created_at": "2026-11-16T08:00:00.000Z",
            "updated_at": "2026-11-16T08:00:00.000Z",
            "items": []
          },
          "item": null
        }
        """
        let response = try decoder().decode(CollectResponseDTO.self, from: Data(json.utf8))
        XCTAssertEqual(response.job.id, "job-1")
        XCTAssertNil(response.item)
    }

    func testJobStatusCapabilities() {
        XCTAssertTrue(CollectionJobStatus.pending.canCancel)
        XCTAssertTrue(CollectionJobStatus.running.canCancel)
        XCTAssertFalse(CollectionJobStatus.succeeded.canCancel)
        XCTAssertTrue(CollectionJobStatus.failed.canRetry)
        XCTAssertTrue(CollectionJobStatus.partiallySucceeded.canRetry)
        XCTAssertTrue(CollectionJobStatus.cancelled.canRetry)
        XCTAssertFalse(CollectionJobStatus.running.canRetry)
    }

    func testAllEnabledSourcesPayloadUsesExplicitNull() throws {
        let data = try CollectionJobRequest.allEnabledSources()
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        XCTAssertEqual(object["trigger_type"] as? String, "manual")
        XCTAssertTrue(object["source_ids"] is NSNull)
    }

    // MARK: - Health

    func testDecodesHealthLogPageWithNulls() throws {
        let json = """
        {
          "items": [
            {
              "checked_at": "2026-11-16T08:00:00.000Z",
              "status": "degraded",
              "http_status": 429,
              "latency_ms": 321,
              "error_code": "http_client_error",
              "error_message": "客户端错误"
            },
            {
              "checked_at": "2026-11-16T07:00:00.000Z",
              "status": "healthy",
              "http_status": null,
              "latency_ms": null,
              "error_code": null,
              "error_message": null
            }
          ],
          "total": 2
        }
        """
        let page = try decoder().decode(SourceHealthLogPage.self, from: Data(json.utf8))
        XCTAssertEqual(page.total, 2)
        XCTAssertEqual(page.items.count, 2)
        XCTAssertEqual(page.items[0].httpStatus, 429)
        XCTAssertEqual(SourceHealthStatus(rawValue: page.items[0].status)?.label, "降级")
        XCTAssertNil(page.items[1].latencyMs)
        XCTAssertEqual(SourceHealthStatus.label(for: page.items[1].status), "健康")
    }

    // MARK: - Time formatting

    func testParsesFractionalAndPlainISO8601() {
        XCTAssertNotNil(PIHDateFormat.date(from: "2026-11-16T08:00:00.123Z"))
        XCTAssertNotNil(PIHDateFormat.date(from: "2026-11-16T08:00:00Z"))
        XCTAssertNil(PIHDateFormat.date(from: "not-a-date"))
        XCTAssertNil(PIHDateFormat.date(from: nil))
    }

    func testFallsBackToOriginalStringWhenParseFails() {
        XCTAssertEqual(PIHDateFormat.display("not-a-date"), "not-a-date")
        XCTAssertEqual(PIHDateFormat.displayDetailed("not-a-date"), "not-a-date")
        XCTAssertEqual(PIHDateFormat.display(nil), "—")
    }

    func testDurationDisplay() {
        XCTAssertEqual(PIHDuration.display(nil), "—")
        XCTAssertEqual(PIHDuration.display(250), "250 ms")
        XCTAssertEqual(PIHDuration.display(1500), "1.5 s")
    }

    // MARK: - Version contract

    func testExpectedServiceVersionMatchesPhase2Contract() {
        XCTAssertEqual(PIHConstants.expectedServiceVersion, "0.14.0")
        XCTAssertEqual(PIHConstants.supportedBackendMajor, 0)
    }

    // MARK: - URL safety

    func testSafeWebURLAcceptsOnlyHTTPAndHTTPS() {
        XCTAssertNotNil(ArticleDetailView.safeWebURL("https://example.com/a"))
        XCTAssertNotNil(ArticleDetailView.safeWebURL("HTTP://example.com/a"))
        XCTAssertNil(ArticleDetailView.safeWebURL("file:///etc/passwd"))
        XCTAssertNil(ArticleDetailView.safeWebURL("javascript:alert(1)"))
        XCTAssertNil(ArticleDetailView.safeWebURL("ftp://example.com/a"))
        XCTAssertNil(ArticleDetailView.safeWebURL("https://"))
        XCTAssertNil(ArticleDetailView.safeWebURL(""))
    }

    // MARK: - Phase 8: full-text search payload

    func testDecodesFtsSearchResponseWithGlobalSnakeCaseStrategy() throws {
        let json = """
        {
          "items": [{
            "article_id": "a-1",
            "title": "AI走进大学课堂",
            "summary": "摘要",
            "snippet": "正文片段",
            "rank": 1.5,
            "source_name": "中国新闻网",
            "category_name": "综合科技",
            "published_at": "2026-11-20T00:00:00.000Z",
            "fetched_at": "2026-11-20T00:10:00.000Z",
            "reading_status": "unread",
            "is_favorite": false
          }],
          "total": 1,
          "limit": 30,
          "offset": 0,
          "query": "AI"
        }
        """
        let response = try decoder().decode(FtsSearchResponse.self, from: Data(json.utf8))
        XCTAssertEqual(response.total, 1)
        let item = try XCTUnwrap(response.items.first)
        XCTAssertEqual(item.articleId, "a-1")
        XCTAssertEqual(item.sourceName, "中国新闻网")
        XCTAssertEqual(item.readingStatus, "unread")
        XCTAssertFalse(item.isFavorite)
    }

    func testFtsSnippetStripsMarkup() {
        let item = FtsSearchItem(
            articleId: "a",
            title: "t",
            summary: nil,
            snippet: "before <mark>AI</mark> after",
            rank: 1,
            sourceName: nil,
            categoryName: nil,
            publishedAt: nil,
            fetchedAt: "",
            readingStatus: "unread",
            isFavorite: false
        )
        XCTAssertEqual(item.plainSnippet, "before AI after")
    }

    func testSearchTimeWindowProducesISOTimestamp() throws {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        XCTAssertNil(SearchTimeWindow.all.startTimestamp(now: now))

        let raw = try XCTUnwrap(SearchTimeWindow.week.startTimestamp(now: now))
        XCTAssertTrue(raw.hasSuffix("Z"))
        let parsed = try XCTUnwrap(PIHDateFormat.date(from: raw))
        XCTAssertEqual(
            parsed.timeIntervalSince1970,
            now.timeIntervalSince1970 - 7 * 24 * 3600,
            accuracy: 1
        )
    }

    func testDecodesContentFetchedAtWhenPresent() throws {
        let json = """
        {
          "id": "a-1",
          "source_id": "s-1",
          "source_name": "Example",
          "category_id": null,
          "category_name": null,
          "title": "Hello",
          "author": null,
          "summary": "summary",
          "canonical_url": "https://example.com/post",
          "content_state": "full",
          "published_at": null,
          "fetched_at": "2026-11-16T08:00:00.123Z",
          "status": "active",
          "created_at": "2026-11-16T08:00:00.123Z",
          "updated_at": "2026-11-16T08:00:00.123Z",
          "external_id": null,
          "original_url": "https://example.com/post",
          "content_text": "body",
          "source_updated_at": null,
          "content_hash": "hash",
          "content_fetched_at": "2026-11-20T00:00:00.000Z",
          "reading_status": "unread",
          "is_favorite": false,
          "last_read_at": null,
          "read_count": 0
        }
        """
        let detail = try decoder().decode(ArticleDetailDTO.self, from: Data(json.utf8))
        XCTAssertEqual(detail.contentFetchedAt, "2026-11-20T00:00:00.000Z")
        XCTAssertEqual(detail.contentText, "body")
    }
}
