import Foundation

/// 今日首页 API。只读取 Sidecar 聚合结果，不在前端拼接业务数据。
extension APIClient {
    func fetchTodayOverview(picks: Int = 5, todo: Int = 10) async throws -> TodayOverviewDTO {
        try await perform(
            "GET",
            path: "/api/v1/today/overview",
            query: [
                URLQueryItem(name: "picks", value: String(picks)),
                URLQueryItem(name: "todo", value: String(todo)),
            ],
            as: TodayOverviewDTO.self
        )
    }
}
