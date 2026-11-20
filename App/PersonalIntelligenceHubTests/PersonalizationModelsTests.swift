import XCTest
@testable import PersonalIntelligenceHub

final class PersonalizationModelsTests: XCTestCase {
    private func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    func testFeedPayloadDecodesRealShape() throws {
        let json = """
        {
          "generated_at": "2026-11-18T07:00:00.000Z",
          "algorithm_version": "personal-reco-v1",
          "budget": {"items": 10, "daily_item_limit": 10, "daily_minutes": null,
                     "exploration_ratio": 0.1, "exploration_cap": 1},
          "metrics": {"today_articles": 12, "today_events": 3, "recommended_total": 9,
                      "must_read": 2, "event_count": 4, "standalone_count": 5},
          "sections": {
            "must_read": [{
              "target_type": "event", "target_id": "e1", "title": "AI Agent 平台发布",
              "summary": "多家公司同日发布企业级智能体平台。",
              "source_name": null, "category": "科技", "published_at": "2026-11-18T06:00:00.000Z",
              "event_id": "e1", "article_count": 3, "source_count": 2,
              "is_read": false, "is_favorite": false, "score": 91.5, "level": "must_read",
              "is_fallback": false, "matched_interests": ["人工智能"],
              "matched_entities": ["OpenAI"], "reason_codes": ["CORE_INTEREST_MATCH"],
              "warnings": ["SOURCE_QUALITY_UNKNOWN"],
              "score_breakdown": {"interest": 100, "importance": 70, "novelty": 90,
                                   "source_quality": 50, "recency": 100},
              "has_core_interest": true, "computed_at": "2026-11-18T07:00:00.000Z"
            }],
            "event_highlights": [], "core_interest": [], "leads": [],
            "watch": [], "others": [],
            "emerging": [{
              "target_type": "topic", "target_id": "Agent", "title": "Agent",
              "count": 5, "previous": 1, "delta": 4, "sources": ["TechCrunch"],
              "reason": "近 24 小时出现频率上升"
            }]
          },
          "has_interests": true, "has_core_interest": true, "onboarding_done": false
        }
        """
        let feed = try decoder().decode(PersonalFeedDTO.self, from: Data(json.utf8))
        XCTAssertEqual(feed.algorithmVersion, "personal-reco-v1")
        XCTAssertEqual(feed.budget.items, 10)
        XCTAssertEqual(feed.metrics.todayArticles, 12)
        XCTAssertEqual(feed.sections.mustRead.count, 1)
        let item = try XCTUnwrap(feed.sections.mustRead.first)
        XCTAssertEqual(item.targetType, "event")
        XCTAssertEqual(item.score, 91.5)
        XCTAssertEqual(item.summary, "多家公司同日发布企业级智能体平台。")
        XCTAssertEqual(item.scoreBreakdown.interest, 100)
        XCTAssertEqual(item.matchedInterests, ["人工智能"])
        XCTAssertEqual(RecommendationLevel(raw: item.level), .mustRead)
        XCTAssertEqual(feed.sections.emerging.first?.delta, 4)
    }

    func testInterestAndProfileDecode() throws {
        let json = """
        {
          "profile": {
            "display_name": "我的兴趣", "digest_time": "08:00", "timezone": "Asia/Shanghai",
            "daily_item_limit": null, "daily_minutes": 20, "exploration_ratio": 0.15,
            "auto_adjust_enabled": true, "onboarding_done": false,
            "updated_at": "2026-11-18T00:00:00.000Z"
          },
          "interest_count": 1, "enabled_interest_count": 1,
          "has_core_interest": true, "blocked_source_count": 0
        }
        """
        let response = try decoder().decode(PersonalProfileResponseDTO.self, from: Data(json.utf8))
        XCTAssertEqual(response.profile.digestTime, "08:00")
        XCTAssertNil(response.profile.dailyItemLimit)
        XCTAssertEqual(response.profile.dailyMinutes, 20)
        XCTAssertTrue(response.hasCoreInterest)

        let interestJSON = """
        {
          "id": "i1", "name": "人工智能", "interest_type": "domain", "level": "core",
          "weight": 1.0, "domain_key": "technology", "enabled": true, "notes": null,
          "keywords": ["AI"], "exclusion_keywords": ["融资"],
          "entity_ids": ["en1"], "entity_names": ["OpenAI"],
          "source_ids": [], "source_names": [],
          "created_at": "2026-11-18T00:00:00.000Z", "updated_at": "2026-11-18T00:00:00.000Z"
        }
        """
        let interest = try decoder().decode(InterestDTO.self, from: Data(interestJSON.utf8))
        XCTAssertEqual(interest.level, "core")
        XCTAssertEqual(interest.exclusionKeywords, ["融资"])
        XCTAssertEqual(interest.entityNames, ["OpenAI"])
        XCTAssertEqual(InterestLevel(rawValue: interest.level), .core)
    }

    func testDigestDecodesSectionsAndItems() throws {
        let json = """
        {
          "id": "d1", "digest_date": "2026-11-18", "timezone": "Asia/Shanghai",
          "status": "succeeded", "ai_status": "skipped",
          "headline": "2026-11-18 今日精选：3 条",
          "overview": "今天共采集 12 篇文章……",
          "digest_version": "digest-v1",
          "generated_at": "2026-11-18T08:00:00.000Z",
          "items": [
            {"id": "it1", "section": "must_not_miss", "rank": 0, "target_type": "event",
             "target_id": "e1", "title": "AI Agent 平台发布", "reason": "匹配兴趣：人工智能",
             "matched_interests": ["人工智能"], "score": 91.5}
          ]
        }
        """
        let digest = try decoder().decode(DailyDigestDTO.self, from: Data(json.utf8))
        XCTAssertEqual(digest.aiStatus, "skipped")
        XCTAssertEqual(digest.items.count, 1)
        XCTAssertEqual(digest.items.first?.section, "must_not_miss")
        XCTAssertEqual(digest.items.first?.targetId, "e1")
    }

    @MainActor
    func testFeedbackResponseDecodes() throws {
        let json = """
        {
          "feedback": {"id": "f1", "target_type": "article", "target_id": "a1",
                       "feedback": "interested", "interest_id": null, "note": null,
                       "created_at": "2026-11-18T07:00:00.000Z", "revoked_at": null},
          "recommendation": {
            "target_type": "article", "target_id": "a1", "title": "标题",
            "source_name": "来源", "category": "科技", "score": 80.0, "level": "recommended",
            "is_fallback": false, "matched_interests": ["人工智能"],
            "matched_entities": [], "reason_codes": ["INTEREST_MATCH"], "warnings": [],
            "score_breakdown": {"interest": 80, "importance": 50, "novelty": 90,
                                 "source_quality": 50, "recency": 100},
            "feedback": null
          }
        }
        """
        let response = try decoder().decode(FeedbackResponseDTO.self, from: Data(json.utf8))
        XCTAssertEqual(response.feedback.feedback, "interested")
        XCTAssertEqual(response.recommendation?.level, "recommended")
        XCTAssertEqual(PersonalizationStore.feedbackLabel("duplicate"), "重复内容")
    }

    func testFeedbackResponseWithoutRecommendationDecodes() throws {
        // Event-member articles have no article-level recommendation.
        let json = """
        {
          "feedback": {"id": "f2", "target_type": "article", "target_id": "a2",
                       "feedback": "not_interested", "interest_id": null, "note": null,
                       "created_at": "2026-11-19T16:00:00.000Z", "revoked_at": null},
          "recommendation": null
        }
        """
        let response = try decoder().decode(FeedbackResponseDTO.self, from: Data(json.utf8))
        XCTAssertEqual(response.feedback.feedback, "not_interested")
        XCTAssertNil(response.recommendation)
    }

    func testRecommendationLevelMappingFallsBack() {
        XCTAssertEqual(RecommendationLevel(raw: "must_read"), .mustRead)
        XCTAssertEqual(RecommendationLevel(raw: "unknown-level"), .low)
    }
}
