import Foundation

/// 今日首页状态：真实聚合数据 + 用户操作后的重新拉取。
@MainActor
final class TodayStore: ObservableObject {
    @Published private(set) var overview: TodayOverviewDTO?
    @Published private(set) var isLoading = false
    @Published private(set) var hasLoaded = false
    @Published private(set) var errorMessage: String?

    private weak var client: APIClient?

    func bind(_ client: APIClient?) {
        if client === self.client { return }
        self.client = client
        if client == nil {
            overview = nil
            hasLoaded = false
            errorMessage = nil
        } else {
            Task { await reload() }
        }
    }

    func loadIfNeeded() async {
        guard !hasLoaded else { return }
        await reload()
    }

    func reload(showSpinner: Bool = true) async {
        guard let client else { return }
        if showSpinner { isLoading = true }
        defer { if showSpinner { isLoading = false } }
        do {
            overview = try await client.fetchTodayOverview()
            hasLoaded = true
            errorMessage = nil
        } catch {
            if error is CancellationError { return }
            if let api = error as? APIRequestError {
                errorMessage = api.message
            } else {
                errorMessage = error.localizedDescription
            }
        }
    }
}
