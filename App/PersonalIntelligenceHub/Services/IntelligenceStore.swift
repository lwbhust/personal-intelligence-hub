import Foundation

/// Phase 7.1 情报中心状态：真实 Sidecar 数据，无静态内容。
@MainActor
final class IntelligenceStore: ObservableObject {
    @Published private(set) var status: IntelligenceStatusDTO?
    @Published private(set) var reports: [IntelligenceReportDTO] = []
    @Published private(set) var historyTotal = 0
    @Published private(set) var emerging: IntelligenceEmergingDTO?
    @Published private(set) var rankings: [String: [IntelligenceRankingItemDTO]] = [:]

    @Published private(set) var detail: IntelligenceReportDetailDTO?
    @Published private(set) var isLoadingDetail = false
    @Published private(set) var isLoading = false
    @Published private(set) var isGenerating = false
    @Published private(set) var hasLoaded = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var errorRequestID: String?
    @Published private(set) var actionMessage: String?

    private weak var client: APIClient?
    private var pollTask: Task<Void, Never>?
    private let rankingKinds = ["importance", "heat", "emerging", "new"]

    var dailyReport: IntelligenceReportDTO? {
        reports.first { $0.reportType == "daily" && ["succeeded", "degraded"].contains($0.status) }
    }

    var weeklyReport: IntelligenceReportDTO? {
        reports.first { $0.reportType == "weekly" && ["succeeded", "degraded"].contains($0.status) }
    }

    var activeReport: IntelligenceReportDTO? {
        reports.first { $0.status == "pending" || $0.status == "running" }
    }

    var isModelAvailable: Bool { status?.ollamaAvailable == true }

    deinit {
        pollTask?.cancel()
    }

    func bind(_ client: APIClient?) {
        if client === self.client { return }
        self.client = client
        pollTask?.cancel()
        pollTask = nil
        if client == nil {
            status = nil
            reports = []
            historyTotal = 0
            emerging = nil
            rankings = [:]
            detail = nil
            hasLoaded = false
            isGenerating = false
            clearError()
        } else {
            Task { await loadAll() }
        }
    }

    // MARK: - Loading

    func loadAll() async {
        guard let client else { return }
        isLoading = true
        defer { isLoading = false }
        clearError()
        do {
            async let statusTask = client.fetchIntelligenceStatus()
            async let reportsTask = client.fetchIntelligenceReports(limit: 50)
            async let emergingTask = client.fetchIntelligenceEmerging()
            status = try await statusTask
            let page = try await reportsTask
            reports = page.items
            historyTotal = page.total
            emerging = try? await emergingTask
            hasLoaded = true
        } catch {
            handle(error)
            return
        }
        await loadRankings()
        if let active = activeReport {
            startPolling(reportID: active.id)
        }
    }

    func refresh() async {
        await loadAll()
    }

    private func loadRankings() async {
        guard let client else { return }
        var loaded: [String: [IntelligenceRankingItemDTO]] = [:]
        for kind in rankingKinds {
            if let page = try? await client.fetchIntelligenceRankings(kind: kind, window: "7d", limit: 5) {
                loaded[kind] = page.items
            }
        }
        rankings = loaded
    }

    func loadDetailIfNeeded(id: String) async {
        if detail?.report.id == id { return }
        await select(id)
    }

    func select(_ id: String) async {
        guard let client else { return }
        isLoadingDetail = true
        defer { isLoadingDetail = false }
        do {
            let loaded = try await client.fetchIntelligenceReport(id: id)
            detail = loaded
            clearError()
        } catch {
            handle(error)
        }
    }

    func clearDetail() {
        detail = nil
    }

    // MARK: - Generation

    func generate(_ reportType: String, force: Bool = false) async {
        guard let client, !isGenerating else { return }
        isGenerating = true
        actionMessage = nil
        clearError()
        do {
            let response = try await client.generateIntelligenceReport(
                reportType: reportType, force: force
            )
            actionMessage = response.reused
                ? "该周期已有情报，已直接打开"
                : (reportType == "daily" ? "正在生成今日情报…" : "正在生成本周情报…")
            await loadReportsOnly()
            startPolling(reportID: response.report.id)
            if response.report.isTerminal {
                isGenerating = false
                await loadAll()
            }
        } catch {
            isGenerating = false
            handle(error)
        }
    }

    func cancel(_ id: String) async {
        guard let client else { return }
        do {
            _ = try await client.cancelIntelligenceReport(id: id)
            actionMessage = "已请求取消生成"
            pollTask?.cancel()
            pollTask = nil
            isGenerating = false
            await loadAll()
            await select(id)
        } catch {
            handle(error)
        }
    }

    private func loadReportsOnly() async {
        guard let client else { return }
        do {
            let page = try await client.fetchIntelligenceReports(limit: 50)
            reports = page.items
            historyTotal = page.total
        } catch {
            handle(error)
        }
    }

    private func startPolling(reportID: String) {
        pollTask?.cancel()
        isGenerating = true
        pollTask = Task { [weak self] in
            guard let self else { return }
            let deadline = Date().addingTimeInterval(240)
            while !Task.isCancelled {
                guard let client = self.client else { break }
                do {
                    let loaded = try await client.fetchIntelligenceReport(id: reportID)
                    if Task.isCancelled { break }
                    self.detail = loaded
                    if loaded.report.isTerminal {
                        self.isGenerating = false
                        self.actionMessage = loaded.report.status == "succeeded"
                            ? "情报已生成"
                            : (loaded.report.status == "degraded"
                               ? "本地模型不可用，已保存统计版情报"
                               : "情报生成结束：\(loaded.report.status)")
                        await self.loadReportsOnly()
                        self.status = try? await client.fetchIntelligenceStatus()
                        await self.loadRankings()
                        break
                    }
                } catch {
                    if Task.isCancelled { break }
                }
                if Date() > deadline {
                    self.isGenerating = false
                    break
                }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
    }

    // MARK: - Errors

    private func handle(_ error: Error) {
        if error is CancellationError { return }
        if let api = error as? APIRequestError {
            if api.code == "cancelled" { return }
            errorMessage = api.message
            errorRequestID = api.requestID
        } else {
            let nsError = error as NSError
            if nsError.domain == NSURLErrorDomain && nsError.code == -999 { return }
            errorMessage = error.localizedDescription
            errorRequestID = nil
        }
    }

    private func clearError() {
        errorMessage = nil
        errorRequestID = nil
    }

    func dismissMessages() {
        actionMessage = nil
        clearError()
    }
}
