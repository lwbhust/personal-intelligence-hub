import Foundation

/// AI 分析页状态：真实状态、模型列表与运行记录。
@MainActor
final class AIStore: ObservableObject {
    @Published private(set) var status: AIStatusDTO?
    @Published private(set) var models: [AIModelDTO] = []
    @Published private(set) var runs: [AIRunDTO] = []
    @Published private(set) var selectedRun: AIRunDTO?
    @Published private(set) var isLoading = false
    @Published private(set) var hasLoaded = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var errorCode: String?
    @Published private(set) var actionMessage: String?
    @Published private(set) var isBusy = false

    @Published var runLimit: Int = 20
    @Published var selectedRunID: String?

    private weak var client: APIClient?

    var hasActiveRun: Bool {
        status?.runningRunId != nil
            || runs.contains { AIRunStatus(rawValue: $0.status)?.isActive == true }
    }

    func bind(_ client: APIClient?) {
        if client === self.client { return }
        self.client = client
        if client == nil {
            status = nil
            models = []
            runs = []
            selectedRun = nil
            selectedRunID = nil
            hasLoaded = false
            clearError()
        } else {
            Task { await reload() }
        }
    }

    func reload() async {
        guard let client else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            async let statusTask = client.fetchAIStatus()
            async let modelsTask = client.fetchAIModels()
            async let runsTask = client.fetchAIRuns(limit: 30, offset: 0)
            let (loadedStatus, modelPage, runPage) = try await (statusTask, modelsTask, runsTask)
            status = loadedStatus
            models = modelPage.items
            runs = runPage.items
            hasLoaded = true
            clearError()
            if let selectedRunID {
                await loadRun(id: selectedRunID, quiet: true)
            }
        } catch {
            handle(error)
        }
    }

    func refreshRuns() async {
        guard let client else { return }
        do {
            async let statusTask = client.fetchAIStatus()
            async let runsTask = client.fetchAIRuns(limit: 30, offset: 0)
            let (loadedStatus, runPage) = try await (statusTask, runsTask)
            status = loadedStatus
            runs = runPage.items
            if let selectedRunID {
                await loadRun(id: selectedRunID, quiet: true)
            }
        } catch {
            handle(error)
        }
    }

    func loadRun(id: String, quiet: Bool = false) async {
        guard let client else { return }
        do {
            let detail = try await client.fetchAIRun(id: id)
            if selectedRunID == id {
                selectedRun = detail
            }
        } catch {
            if !quiet { handle(error) }
        }
    }

    func selectRun(_ id: String?) async {
        selectedRunID = id
        selectedRun = nil
        guard let id else { return }
        await loadRun(id: id)
    }

    func createUnanalyzedRun() async {
        guard let client else { return }
        isBusy = true
        actionMessage = nil
        defer { isBusy = false }
        do {
            let run = try await client.createUnanalyzedAIRun(limit: runLimit)
            selectedRunID = run.id
            selectedRun = run
            actionMessage = "已创建分析任务：\(run.requestedCount) 篇文章"
            await reload()
        } catch {
            handle(error)
        }
    }

    func pause(_ run: AIRunDTO) async {
        await control(run) { try await $0.pauseAIRun(id: $1) }
    }

    func resume(_ run: AIRunDTO) async {
        await control(run) { try await $0.resumeAIRun(id: $1) }
    }

    func cancel(_ run: AIRunDTO) async {
        await control(run) { try await $0.cancelAIRun(id: $1) }
    }

    func retry(_ run: AIRunDTO) async {
        await control(run) { try await $0.retryAIRun(id: $1) }
    }

    /// 页面存活期间轮询，仅在存在活动任务时刷新运行状态。
    func autoRefreshLoop() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(2))
            if Task.isCancelled { return }
            if hasActiveRun || selectedRun?.status == "running" {
                await refreshRuns()
            }
        }
    }

    func clearError() {
        errorMessage = nil
        errorCode = nil
    }

    // MARK: - Helpers

    private func control(
        _ run: AIRunDTO,
        _ action: @escaping (APIClient, String) async throws -> AIRunDTO
    ) async {
        guard let client else { return }
        isBusy = true
        actionMessage = nil
        defer { isBusy = false }
        do {
            let updated = try await action(client, run.id)
            selectedRunID = updated.id
            selectedRun = updated
            actionMessage = "任务状态：\(aiRunStatusLabel(updated.status))"
            await reload()
        } catch {
            handle(error)
        }
    }

    private func handle(_ error: Error) {
        if let api = error as? APIRequestError {
            errorMessage = api.message
            errorCode = api.code
        } else {
            errorMessage = error.localizedDescription
            errorCode = nil
        }
    }
}
