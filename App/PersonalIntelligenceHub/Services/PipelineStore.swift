import Foundation

enum PipelineTab: String, CaseIterable, Identifiable {
    case overview
    case running
    case waiting
    case failed
    case history
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview: return "总览"
        case .running: return "正在处理"
        case .waiting: return "等待处理"
        case .failed: return "失败任务"
        case .history: return "历史记录"
        case .settings: return "自动化设置"
        }
    }
}

enum PipelineTaskScope {
    case running
    case waiting
    case failed

    var queryStatus: String {
        switch self {
        case .running: return "running"
        case .waiting: return "pending,ready,retry_wait"
        case .failed: return "failed"
        }
    }
}

/// 自动化管道状态与操作。所有计数来自真实 API；未知值原样展示。
@MainActor
final class PipelineStore: ObservableObject {
    @Published private(set) var overview: PipelineOverviewDTO?
    @Published private(set) var isLoadingOverview = false
    @Published private(set) var overviewErrorMessage: String?
    @Published private(set) var overviewErrorRequestID: String?

    @Published private(set) var tasks: [PipelineTaskDTO] = []
    @Published private(set) var tasksTotal = 0
    @Published private(set) var isLoadingTasks = false
    @Published private(set) var hasLoadedTasks = false
    @Published private(set) var tasksErrorMessage: String?
    @Published private(set) var tasksErrorRequestID: String?

    @Published var selectedTaskID: String?
    @Published private(set) var detail: PipelineTaskDTO?
    @Published private(set) var logs: [PipelineLogDTO] = []
    @Published private(set) var isLoadingDetail = false
    @Published private(set) var detailErrorMessage: String?

    @Published private(set) var runs: [PipelineRunDTO] = []
    @Published private(set) var runsTotal = 0
    @Published private(set) var isLoadingRuns = false
    @Published private(set) var runsErrorMessage: String?

    @Published private(set) var preview: PipelineBackfillPreviewDTO?
    @Published private(set) var isLoadingPreview = false

    @Published private(set) var isPerformingAction = false
    @Published private(set) var actionErrorMessage: String?
    @Published private(set) var actionErrorRequestID: String?
    @Published private(set) var lastActionMessage: String?

    private weak var client: APIClient?
    private let pageSize = 30

    var canLoadMoreTasks: Bool {
        hasLoadedTasks && tasks.count < tasksTotal
    }

    var hasActiveWork: Bool {
        guard let overview else { return false }
        return overview.counts.running > 0 || overview.counts.pending > 0
    }

    func bind(_ client: APIClient?) {
        if client === self.client { return }
        self.client = client
        if client == nil {
            overview = nil
            tasks = []
            runs = []
            detail = nil
            logs = []
            preview = nil
            selectedTaskID = nil
            hasLoadedTasks = false
        } else {
            Task { await refreshAll() }
        }
    }

    // MARK: - Overview

    func reloadOverview(showSpinner: Bool = true) async {
        guard let client else { return }
        if showSpinner { isLoadingOverview = true }
        defer { if showSpinner { isLoadingOverview = false } }
        do {
            overview = try await client.fetchPipelineOverview()
            clearOverviewError()
        } catch {
            handleOverviewError(error)
        }
    }

    // MARK: - Tasks

    func reloadTasks(scope: PipelineTaskScope, showSpinner: Bool = true) async {
        guard let client else { return }
        if showSpinner { isLoadingTasks = true }
        defer { if showSpinner { isLoadingTasks = false } }
        do {
            let page = try await client.fetchPipelineTasks(query: query(scope: scope, offset: 0))
            tasks = page.items
            tasksTotal = page.total
            hasLoadedTasks = true
            clearTasksError()
        } catch {
            handleTasksError(error)
        }
    }

    func loadMoreTasks(scope: PipelineTaskScope) async {
        guard let client, !isLoadingTasks, tasks.count < tasksTotal else { return }
        isLoadingTasks = true
        defer { isLoadingTasks = false }
        do {
            let page = try await client.fetchPipelineTasks(
                query: query(scope: scope, offset: tasks.count)
            )
            tasks.append(contentsOf: page.items)
            tasksTotal = page.total
            clearTasksError()
        } catch {
            handleTasksError(error)
        }
    }

    func task(_ id: String) -> PipelineTaskDTO? {
        tasks.first { $0.id == id }
    }

    func loadDetail(force: Bool = false) async {
        guard let client, let id = selectedTaskID else {
            detail = nil
            logs = []
            return
        }
        if !force, detail?.id == id { return }
        isLoadingDetail = true
        detailErrorMessage = nil
        defer { isLoadingDetail = false }
        do {
            async let task = client.fetchPipelineTask(id: id)
            async let logPage = client.fetchPipelineLogs(
                id: id,
                query: [
                    URLQueryItem(name: "limit", value: "100"),
                    URLQueryItem(name: "offset", value: "0"),
                ]
            )
            let (loadedTask, loadedLogs) = try await (task, logPage)
            guard selectedTaskID == id else { return }
            detail = loadedTask
            logs = loadedLogs.items
        } catch {
            guard selectedTaskID == id else { return }
            detail = nil
            logs = []
            detailErrorMessage = (error as? APIRequestError)?.message ?? error.localizedDescription
        }
    }

    // MARK: - Runs

    func reloadRuns(showSpinner: Bool = true) async {
        guard let client else { return }
        if showSpinner { isLoadingRuns = true }
        defer { if showSpinner { isLoadingRuns = false } }
        do {
            let page = try await client.fetchPipelineRuns(
                query: [
                    URLQueryItem(name: "limit", value: String(pageSize)),
                    URLQueryItem(name: "offset", value: "0"),
                ]
            )
            runs = page.items
            runsTotal = page.total
            runsErrorMessage = nil
        } catch {
            runsErrorMessage = (error as? APIRequestError)?.message ?? error.localizedDescription
        }
    }

    // MARK: - Backfill

    func loadBackfillPreview() async {
        guard let client else { return }
        isLoadingPreview = true
        defer { isLoadingPreview = false }
        do {
            preview = try await client.fetchPipelineBackfillPreview()
        } catch {
            preview = nil
        }
    }

    func createBackfill(limit: Int) async -> Bool {
        guard let client, !isPerformingAction else { return false }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            let result = try await client.createPipelineBackfill(limit: limit)
            clearActionError()
            lastActionMessage = "已创建回填批次，共 \(result.createdTasks) 个任务"
            await refreshAll()
            return true
        } catch {
            handleActionError(error)
            return false
        }
    }

    // MARK: - Commands

    func setAutomation(_ enabled: Bool) async {
        guard let client, !isPerformingAction else { return }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            _ = try await client.updatePipelineSettings(
                PipelineSettingsUpdate(automationEnabled: enabled)
            )
            clearActionError()
            lastActionMessage = enabled ? "自动化已启用" : "自动化已关闭"
            await refreshAll()
        } catch {
            handleActionError(error)
        }
    }

    func setPaused(_ paused: Bool) async {
        guard let client, !isPerformingAction else { return }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            _ = try await client.pipelineControl(action: paused ? "pause" : "resume")
            clearActionError()
            lastActionMessage = paused ? "管道已暂停" : "管道已恢复"
            await refreshAll()
        } catch {
            handleActionError(error)
        }
    }

    func saveSettings(_ update: PipelineSettingsUpdate) async -> Bool {
        guard let client, !isPerformingAction else { return false }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            _ = try await client.updatePipelineSettings(update)
            clearActionError()
            lastActionMessage = "自动化设置已保存"
            await reloadOverview(showSpinner: false)
            return true
        } catch {
            handleActionError(error)
            return false
        }
    }

    func retrySelected() async {
        guard let client, let id = selectedTaskID, !isPerformingAction else { return }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            _ = try await client.retryPipelineTask(id: id)
            clearActionError()
            lastActionMessage = "任务已重新排队"
            await reloadOverview(showSpinner: false)
            await loadDetail(force: true)
        } catch {
            handleActionError(error)
        }
    }

    func cancelSelected() async {
        guard let client, let id = selectedTaskID, !isPerformingAction else { return }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            _ = try await client.cancelPipelineTask(id: id)
            clearActionError()
            lastActionMessage = "任务已取消"
            await reloadOverview(showSpinner: false)
            await loadDetail(force: true)
        } catch {
            handleActionError(error)
        }
    }

    func cancelRun(_ run: PipelineRunDTO) async {
        guard let client, !isPerformingAction else { return }
        isPerformingAction = true
        defer { isPerformingAction = false }
        do {
            _ = try await client.cancelPipelineRun(id: run.id)
            clearActionError()
            await reloadRuns(showSpinner: false)
            await reloadOverview(showSpinner: false)
        } catch {
            handleActionError(error)
        }
    }

    // MARK: - Refresh / polling

    func refreshAll() async {
        await reloadOverview(showSpinner: false)
        await reloadRuns(showSpinner: false)
        await loadBackfillPreview()
    }

    func refreshQuietly(scope: PipelineTaskScope?) async {
        await reloadOverview(showSpinner: false)
        if let scope {
            await reloadTasks(scope: scope, showSpinner: false)
        }
        if selectedTaskID != nil {
            await loadDetail(force: true)
        }
    }

    func pollWhileActive(scope: PipelineTaskScope?) async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(3))
            if Task.isCancelled { return }
            guard client != nil, hasActiveWork else { continue }
            await refreshQuietly(scope: scope)
        }
    }

    // MARK: - Errors

    func clearOverviewError() {
        overviewErrorMessage = nil
        overviewErrorRequestID = nil
    }

    func clearTasksError() {
        tasksErrorMessage = nil
        tasksErrorRequestID = nil
    }

    func clearActionError() {
        actionErrorMessage = nil
        actionErrorRequestID = nil
        lastActionMessage = nil
    }

    private func query(scope: PipelineTaskScope, offset: Int) -> [URLQueryItem] {
        [
            URLQueryItem(name: "status", value: scope.queryStatus),
            URLQueryItem(name: "limit", value: String(pageSize)),
            URLQueryItem(name: "offset", value: String(offset)),
        ]
    }

    private func handleOverviewError(_ error: Error) {
        if let api = error as? APIRequestError {
            overviewErrorMessage = api.message
            overviewErrorRequestID = api.requestID
        } else {
            overviewErrorMessage = error.localizedDescription
            overviewErrorRequestID = nil
        }
    }

    private func handleTasksError(_ error: Error) {
        if let api = error as? APIRequestError {
            tasksErrorMessage = api.message
            tasksErrorRequestID = api.requestID
        } else {
            tasksErrorMessage = error.localizedDescription
            tasksErrorRequestID = nil
        }
    }

    private func handleActionError(_ error: Error) {
        if let api = error as? APIRequestError {
            actionErrorMessage = api.message
            actionErrorRequestID = api.requestID
        } else {
            actionErrorMessage = error.localizedDescription
            actionErrorRequestID = nil
        }
    }
}
