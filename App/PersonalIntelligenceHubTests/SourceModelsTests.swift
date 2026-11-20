import XCTest
@testable import PersonalIntelligenceHub

/// Phase 1 API 读模型与表单草稿的契约测试。
final class SourceModelsTests: XCTestCase {

    private func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    func testDecodesSourcePageWithNestedCategoryAndNulls() throws {
        let json = """
        {
          "items": [
            {
              "id": "0b6f7e4e-1b1a-4b1e-9b0d-1a2b3c4d5e6f",
              "name": "Example",
              "source_type": "rss",
              "url": "https://example.com/feed.xml",
              "homepage_url": null,
              "description": null,
              "language": "en",
              "country": "US",
              "priority": 50,
              "credibility_score": null,
              "fetch_interval_minutes": 30,
              "enabled": true,
              "health_status": "unknown",
              "last_fetch_at": null,
              "last_success_at": null,
              "last_error_at": null,
              "last_error_code": null,
              "last_error_message": null,
              "category": {"id": "cat-1", "name": "Tech"},
              "article_count": 12,
              "created_at": "2026-11-16T08:00:00.000Z",
              "updated_at": "2026-11-16T08:00:00.000Z",
              "unexpected_future_field": "ignored"
            }
          ],
          "total": 1,
          "limit": 20,
          "offset": 0
        }
        """
        let page = try decoder().decode(SourcePage.self, from: Data(json.utf8))
        XCTAssertEqual(page.total, 1)
        XCTAssertEqual(page.items.count, 1)
        let source = page.items[0]
        XCTAssertEqual(source.sourceType, "rss")
        XCTAssertEqual(source.fetchIntervalMinutes, 30)
        XCTAssertTrue(source.enabled)
        XCTAssertEqual(source.category?.name, "Tech")
        XCTAssertEqual(source.articleCount, 12)
        XCTAssertNil(source.credibilityScore)
        XCTAssertNil(source.lastSuccessAt)
    }

    func testDecodesCategoryResponse() throws {
        let json = """
        {
          "id": "cat-1",
          "name": "AI",
          "description": null,
          "sort_order": 10,
          "source_count": 3,
          "created_at": "2026-11-16T08:00:00.000Z",
          "updated_at": "2026-11-16T08:00:00.000Z"
        }
        """
        let category = try decoder().decode(SourceCategoryDTO.self, from: Data(json.utf8))
        XCTAssertEqual(category.name, "AI")
        XCTAssertEqual(category.sortOrder, 10)
        XCTAssertEqual(category.sourceCount, 3)
    }

    func testDraftPayloadUsesExplicitNullsAndNormalisesInput() throws {
        var draft = SourceDraft()
        draft.name = "  Example  "
        draft.url = "https://example.com/feed.xml"
        draft.country = "cn"
        draft.description = "   "
        draft.homepageURL = ""
        draft.categoryID = nil
        draft.credibility = ""

        let data = try draft.payload()
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        XCTAssertEqual(object["name"] as? String, "Example")
        XCTAssertEqual(object["country"] as? String, "CN")
        XCTAssertEqual(object["source_type"] as? String, "rss")
        XCTAssertTrue(object["homepage_url"] is NSNull)
        XCTAssertTrue(object["description"] is NSNull)
        XCTAssertTrue(object["category_id"] is NSNull)
        XCTAssertTrue(object["credibility_score"] is NSNull)
    }

    func testDraftFromSourcePreservesEditableFields() {
        let source = SourceDTO(
            id: "id-1",
            name: "Example",
            sourceType: "atom",
            url: "https://example.com/atom.xml",
            homepageUrl: "https://example.com",
            description: "desc",
            language: "zh-CN",
            country: "CN",
            priority: 42,
            credibilityScore: 70,
            fetchIntervalMinutes: 15,
            maxEntriesPerFetch: 30,
            enabled: false,
            healthStatus: "unknown",
            lastFetchAt: nil,
            lastSuccessAt: nil,
            lastErrorAt: nil,
            lastErrorCode: nil,
            lastErrorMessage: nil,
            category: CategoryRef(id: "cat-1", name: "Tech"),
            articleCount: 7,
            adapterVerification: nil,
            createdAt: "2026-11-16T08:00:00.000Z",
            updatedAt: "2026-11-16T08:00:00.000Z"
        )
        let draft = SourceDraft(source: source)
        XCTAssertTrue(draft.isEditing)
        XCTAssertEqual(draft.sourceID, "id-1")
        XCTAssertEqual(draft.sourceType, .atom)
        XCTAssertEqual(draft.priority, 42)
        XCTAssertEqual(draft.credibility, "70")
        XCTAssertEqual(draft.interval, 15)
        XCTAssertEqual(draft.maxEntries, "30")
        XCTAssertFalse(draft.enabled)
        XCTAssertEqual(draft.categoryID, "cat-1")
    }

    func testSourceTypeLabelsAndFilters() {
        XCTAssertEqual(SourceType.rss.label, "RSS")
        XCTAssertEqual(SourceType.officialAnnouncement.rawValue, "official_announcement")
        XCTAssertEqual(SourceTypeFilter.all.label, "全部类型")
        XCTAssertEqual(EnabledFilter.disabled.label, "已停用")
    }

    func testCategoryDraftPayload() throws {
        var draft = CategoryDraft()
        draft.name = " AI "
        draft.description = "  "
        draft.sortOrder = 5
        let data = try draft.payload()
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        XCTAssertEqual(object["name"] as? String, "AI")
        XCTAssertEqual(object["sort_order"] as? Int, 5)
        XCTAssertTrue(object["description"] is NSNull)
    }
}
