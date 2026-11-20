import XCTest
@testable import PersonalIntelligenceHub

final class EventModelsTests: XCTestCase {
    private func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    func testPrimaryNavigationHasFiveEntries() {
        XCTAssertEqual(AppSection.allCases.count, 5)
        XCTAssertEqual(AppSection.allCases.map(\.title), ["今日", "阅读", "事件", "洞察", "设置"])
        XCTAssertEqual(AppSection.daily.map(\.rawValue), ["today", "reading", "events", "insights"])
        XCTAssertEqual(AppSection.events.title, "事件")
        XCTAssertTrue(AppSection.allCases.contains(.events))
    }

    func testEventPageDecodesScoreSummary() throws {
        let json = """
        {
          "items": [{
            "id": "11111111-1111-4111-8111-111111111111",
            "title": "星河科技第三季度财报",
            "summary": "营收同比增长两成",
            "category": "科技",
            "status": "active",
            "first_seen_at": "2026-11-17T01:00:00.000Z",
            "last_seen_at": "2026-11-17T02:00:00.000Z",
            "first_published_at": "2026-11-17T01:00:00.000Z",
            "last_published_at": "2026-11-17T02:00:00.000Z",
            "article_count": 3,
            "source_count": 3,
            "is_manual": false,
            "merged_into_event_id": null,
            "algorithm_version": "event-cluster-v1",
            "current_scores": {
              "importance_score": 72.5,
              "heat_score": 66.0,
              "freshness_score": 94.0,
              "coverage_score": 100.0,
              "confidence_score": 85.0,
              "total_score": 78.4,
              "algorithm_version": "event-score-v1",
              "scored_at": "2026-11-17T02:00:00.000Z"
            },
            "top_entities": [{
              "entity_id": "22222222-2222-4222-8222-222222222222",
              "canonical_name": "星河科技",
              "entity_type": "organization",
              "role": "subject",
              "article_count": 3,
              "confidence": 0.9,
              "evidence_article_id": null,
              "evidence_article_title": null
            }]
          }],
          "total": 1,
          "limit": 20,
          "offset": 0
        }
        """
        let page = try decoder().decode(EventPageDTO.self, from: Data(json.utf8))
        XCTAssertEqual(page.total, 1)
        XCTAssertEqual(page.items.first?.articleCount, 3)
        XCTAssertEqual(page.items.first?.currentScores?.totalScore, 78.4)
        XCTAssertEqual(page.items.first?.currentScores?.algorithmVersion, "event-score-v1")
        XCTAssertEqual(page.items.first?.topEntities.first?.canonicalName, "星河科技")
    }

    func testEventDetailDecodesRelationsAndEntities() throws {
        let json = """
        {
          "id": "11111111-1111-4111-8111-111111111111",
          "title": "事件",
          "summary": null,
          "category": "科技",
          "status": "evolving",
          "status_reason": null,
          "first_seen_at": "2026-11-17T01:00:00.000Z",
          "last_seen_at": "2026-11-17T02:00:00.000Z",
          "first_published_at": null,
          "last_published_at": null,
          "occurred_at": null,
          "article_count": 2,
          "source_count": 2,
          "is_manual": true,
          "merged_into_event_id": null,
          "algorithm_version": "event-cluster-v1",
          "created_at": "2026-11-17T01:00:00.000Z",
          "updated_at": "2026-11-17T02:00:00.000Z",
          "current_scores": null,
          "top_entities": [],
          "entities": [{
            "entity_id": "22222222-2222-4222-8222-222222222222",
            "canonical_name": "星河科技",
            "entity_type": "organization",
            "role": "subject",
            "article_count": 2,
            "confidence": 0.9,
            "evidence_article_id": "33333333-3333-4333-8333-333333333333",
            "evidence_article_title": "报道"
          }],
          "relations": [{
            "id": "44444444-4444-4444-8444-444444444444",
            "source_event_id": "11111111-1111-4111-8111-111111111111",
            "target_event_id": "55555555-5555-4555-8555-555555555555",
            "source_event_title": "事件",
            "target_event_title": "另一事件",
            "relation_type": "same_topic",
            "confidence": 0.6,
            "status": "candidate",
            "rationale": "同主题",
            "evidence_articles": [{
              "article_id": "33333333-3333-4333-8333-333333333333",
              "title": "报道"
            }],
            "actor": "algorithm",
            "algorithm_version": "event-relation-v1",
            "created_at": "2026-11-17T01:00:00.000Z",
            "updated_at": "2026-11-17T01:00:00.000Z"
          }]
        }
        """
        let detail = try decoder().decode(EventDetailDTO.self, from: Data(json.utf8))
        XCTAssertEqual(detail.status, "evolving")
        XCTAssertTrue(detail.isManual)
        XCTAssertEqual(detail.entities.first?.role, "subject")
        XCTAssertEqual(detail.relations.first?.relationType, "same_topic")
        XCTAssertEqual(detail.relations.first?.evidenceArticles.first?.title, "报道")
    }

    func testScoreSnapshotDecodesExplanation() throws {
        let json = """
        {
          "id": "66666666-6666-4666-8666-666666666666",
          "event_id": "11111111-1111-4111-8111-111111111111",
          "algorithm_version": "event-score-v1",
          "scored_at": "2026-11-17T02:00:00.000Z",
          "importance_score": 70.0,
          "heat_score": 60.0,
          "freshness_score": 90.0,
          "coverage_score": 100.0,
          "confidence_score": 80.0,
          "total_score": 75.5,
          "is_current": true,
          "inputs": {"article_count": 3, "unique_source_count": 3},
          "explanation": {
            "formula": "0.35*importance + 0.25*heat + 0.15*freshness + 0.15*confidence + 0.10*coverage",
            "weights": {"importance": 0.35},
            "components": [{
              "name": "importance",
              "weight": 0.35,
              "value": 70.0,
              "contribution": 24.5,
              "reason": "类别基础分 70"
            }]
          }
        }
        """
        let snapshot = try decoder().decode(EventScoreSnapshotDTO.self, from: Data(json.utf8))
        XCTAssertEqual(snapshot.totalScore, 75.5)
        XCTAssertTrue(snapshot.isCurrent)
        XCTAssertEqual(snapshot.explanation.components.first?.name, "importance")
        XCTAssertEqual(snapshot.inputs["article_count"], .integer(3))
    }

    func testLabelsAndTimestampFallback() {
        XCTAssertEqual(eventStatusLabel("dormant"), "休眠")
        XCTAssertEqual(eventRelationLabel("caused_by"), "因果")
        XCTAssertEqual(eventTimelineKindLabel("status_change"), "状态变化")
        XCTAssertEqual(displayTimestamp(nil), "—")
        XCTAssertEqual(displayTimestamp("not-a-date"), "not-a-date")
        XCTAssertNotEqual(displayTimestamp("2026-11-17T02:00:00.000Z"), "—")
    }
}
