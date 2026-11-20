import Foundation

/// Phase 7.2 自动化管道 API。全部为真实 Sidecar 端点，不缓存、不伪造。
extension APIClient {
    private struct TaskEnvelope: Decodable { let task: PipelineTaskDTO }
    private struct RunEnvelope: Decodable { let run: PipelineRunDTO }

    func fetchPipelineOverview() async throws -> PipelineOverviewDTO {
        try await perform("GET", path: "/api/v1/pipeline/overview", as: PipelineOverviewDTO.self)
    }

    func fetchPipelineSettings() async throws -> PipelineSettingsDTO {
        try await perform("GET", path: "/api/v1/pipeline/settings", as: PipelineSettingsDTO.self)
    }

    func updatePipelineSettings(_ update: PipelineSettingsUpdate) async throws -> PipelineSettingsDTO {
        let body = try JSONEncoder().encode(update)
        return try await perform(
            "PATCH", path: "/api/v1/pipeline/settings", body: body, as: PipelineSettingsDTO.self
        )
    }

    func pipelineControl(action: String) async throws -> PipelineSettingsDTO {
        let body = try JSONSerialization.data(withJSONObject: ["action": action])
        return try await perform(
            "POST", path: "/api/v1/pipeline/control", body: body, as: PipelineSettingsDTO.self
        )
    }

    func fetchPipelineTasks(query: [URLQueryItem]) async throws -> PipelineTaskPageDTO {
        try await perform(
            "GET", path: "/api/v1/pipeline/tasks", query: query, as: PipelineTaskPageDTO.self
        )
    }

    func fetchPipelineTask(id: String) async throws -> PipelineTaskDTO {
        let envelope: TaskEnvelope = try await perform(
            "GET", path: "/api/v1/pipeline/tasks/\(id)", as: TaskEnvelope.self
        )
        return envelope.task
    }

    func fetchPipelineLogs(id: String, query: [URLQueryItem]) async throws -> PipelineLogPageDTO {
        try await perform(
            "GET",
            path: "/api/v1/pipeline/tasks/\(id)/logs",
            query: query,
            as: PipelineLogPageDTO.self
        )
    }

    func retryPipelineTask(id: String) async throws -> PipelineTaskDTO {
        let envelope: TaskEnvelope = try await perform(
            "POST", path: "/api/v1/pipeline/tasks/\(id)/retry", as: TaskEnvelope.self
        )
        return envelope.task
    }

    func cancelPipelineTask(id: String) async throws -> PipelineTaskDTO {
        let envelope: TaskEnvelope = try await perform(
            "POST", path: "/api/v1/pipeline/tasks/\(id)/cancel", as: TaskEnvelope.self
        )
        return envelope.task
    }

    func fetchPipelineBackfillPreview() async throws -> PipelineBackfillPreviewDTO {
        try await perform(
            "GET", path: "/api/v1/pipeline/backfill/preview", as: PipelineBackfillPreviewDTO.self
        )
    }

    func createPipelineBackfill(limit: Int) async throws -> PipelineBackfillResultDTO {
        let body = try JSONSerialization.data(withJSONObject: ["limit": limit])
        return try await perform(
            "POST", path: "/api/v1/pipeline/backfill", body: body,
            as: PipelineBackfillResultDTO.self
        )
    }

    func fetchPipelineRuns(query: [URLQueryItem]) async throws -> PipelineRunPageDTO {
        try await perform(
            "GET", path: "/api/v1/pipeline/runs", query: query, as: PipelineRunPageDTO.self
        )
    }

    func cancelPipelineRun(id: String) async throws -> PipelineRunDTO {
        let envelope: RunEnvelope = try await perform(
            "POST", path: "/api/v1/pipeline/runs/\(id)/cancel", as: RunEnvelope.self
        )
        return envelope.run
    }
}
