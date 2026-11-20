import XCTest
@testable import PersonalIntelligenceHub

final class AIModelsTests: XCTestCase {
    private func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    func testDecodesAIStatus() throws {
        let json = """
        {
          "enabled": true,
          "provider_kind": "ollama-local",
          "base_url": "http://127.0.0.1:11434",
          "available": false,
          "version": null,
          "error_code": "model_unavailable",
          "default_model": "qwen3.5:4b-mlx",
          "enabled_models": ["qwen3.5:4b-mlx"],
          "installed_models": [],
          "cloud_models_blocked": 4,
          "concurrency": 1,
          "queue_depth": 0,
          "running_run_id": null,
          "embedding": {"enabled": false, "reason": "embedding_model_not_configured"},
          "checked_at": "2026-11-16T10:00:00.000Z"
        }
        """
        let status = try decoder().decode(AIStatusDTO.self, from: Data(json.utf8))
        XCTAssertTrue(status.enabled)
        XCTAssertFalse(status.available)
        XCTAssertEqual(status.baseUrl, "http://127.0.0.1:11434")
        XCTAssertEqual(status.enabledModels, ["qwen3.5:4b-mlx"])
        XCTAssertEqual(status.cloudModelsBlocked, 4)
        XCTAssertEqual(status.embedding.reason, "embedding_model_not_configured")
    }

    func testDecodesRunWithItems() throws {
        let json = """
        {
          "id": "run-1",
          "trigger_type": "manual",
          "scope": "unanalyzed",
          "status": "partially_succeeded",
          "requested_count": 2,
          "processed_count": 2,
          "succeeded_count": 1,
          "failed_count": 1,
          "skipped_count": 0,
          "model_name": "qwen3.5:4b-mlx",
          "error_message": null,
          "cancel_requested": false,
          "pause_requested": false,
          "started_at": "2026-11-16T10:00:00.000Z",
          "finished_at": "2026-11-16T10:00:10.000Z",
          "duration_ms": 10000,
          "created_at": "2026-11-16T10:00:00.000Z",
          "updated_at": "2026-11-16T10:00:10.000Z",
          "items": [
            {
              "id": "item-1",
              "run_id": "run-1",
              "article_id": "article-1",
              "article_title": "测试文章",
              "status": "succeeded",
              "attempts": 1,
              "error_code": null,
              "error_message": null,
              "started_at": null,
              "finished_at": null,
              "duration_ms": 1200
            },
            {
              "id": "item-2",
              "run_id": "run-1",
              "article_id": "article-2",
              "article_title": null,
              "status": "failed",
              "attempts": 3,
              "error_code": "schema_invalid",
              "error_message": "结构校验失败",
              "started_at": null,
              "finished_at": null,
              "duration_ms": 300
            }
          ]
        }
        """
        let run = try decoder().decode(AIRunDTO.self, from: Data(json.utf8))
        XCTAssertEqual(run.status, "partially_succeeded")
        XCTAssertEqual(run.items.count, 2)
        XCTAssertEqual(run.items[1].errorCode, "schema_invalid")
        XCTAssertEqual(AIRunStatus(rawValue: run.status)?.isActive, false)
        XCTAssertEqual(aiRunStatusLabel("paused"), "已暂停")
        XCTAssertEqual(aiItemStatusLabel("skipped"), "跳过")
        XCTAssertEqual(aiErrorLabel("cloud_model_blocked"), "云端模型已阻断")
    }

    func testDecodesAnalysisWithParams() throws {
        let json = """
        {
          "article_id": "article-1",
          "items": [
            {
              "id": "analysis-1",
              "analysis_type": "article_analysis",
              "category": "科技",
              "summary": "摘要",
              "keywords": ["本地模型", "结构化", "安全"],
              "entities": [{"name": "Ollama", "type": "product"}],
              "confidence": 0.9,
              "model_name": "qwen3.5:4b-mlx",
              "model_digest": "abc",
              "prompt_version": "article-analysis-v1",
              "params": {"num_ctx": 4096, "temperature": 0.1, "num_predict": 512},
              "input_chars": 1234,
              "duration_ms": 2300,
              "content_hash": "abc",
              "created_at": "2026-11-16T10:00:00.000Z"
            }
          ]
        }
        """
        let response = try decoder().decode(ArticleAnalysisDTO.self, from: Data(json.utf8))
        XCTAssertEqual(response.items.count, 1)
        let item = response.items[0]
        XCTAssertEqual(item.category, "科技")
        XCTAssertEqual(item.entities.first?.name, "Ollama")
        XCTAssertEqual(item.params["num_ctx"]?.display, "4096")
        XCTAssertEqual(item.params["temperature"]?.display, "0.1")
    }

    func testAIAnalysisMovedOutOfPrimaryNavigation() {
        XCTAssertFalse(AppSection.allCases.map(\.title).contains("AI 分析"))
        XCTAssertTrue(AppSection.allCases.contains(.settings))
        XCTAssertEqual(AppSection.settings.title, "设置")
    }
}
