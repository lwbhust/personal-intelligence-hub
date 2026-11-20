import Foundation

/// Phase 7.1 情报中心访问：全部走真实 Sidecar HTTP。
extension APIClient {
    private struct GenerateBody: Encodable {
        let reportType: String
        let force: Bool
    }

    private func encodeBody<T: Encodable>(_ value: T) throws -> Data {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return try encoder.encode(value)
    }

    func fetchIntelligenceStatus() async throws -> IntelligenceStatusDTO {
        try await perform("GET", path: "/api/v1/intelligence/status", as: IntelligenceStatusDTO.self)
    }

    func fetchIntelligenceReports(
        reportType: String? = nil,
        status: String? = nil,
        limit: Int = 20,
        offset: Int = 0
    ) async throws -> IntelligenceReportPageDTO {
        var query = [
            URLQueryItem(name: "limit", value: String(limit)),
            URLQueryItem(name: "offset", value: String(offset)),
        ]
        if let reportType {
            query.append(URLQueryItem(name: "report_type", value: reportType))
        }
        if let status {
            query.append(URLQueryItem(name: "status", value: status))
        }
        return try await perform(
            "GET", path: "/api/v1/intelligence/reports", query: query,
            as: IntelligenceReportPageDTO.self
        )
    }

    func fetchIntelligenceReport(id: String) async throws -> IntelligenceReportDetailDTO {
        try await perform(
            "GET", path: "/api/v1/intelligence/reports/\(id)",
            as: IntelligenceReportDetailDTO.self
        )
    }

    func generateIntelligenceReport(
        reportType: String, force: Bool = false
    ) async throws -> IntelligenceGenerateResponseDTO {
        let body = try encodeBody(GenerateBody(reportType: reportType, force: force))
        return try await perform(
            "POST", path: "/api/v1/intelligence/reports/generate", body: body,
            as: IntelligenceGenerateResponseDTO.self
        )
    }

    func cancelIntelligenceReport(id: String) async throws -> IntelligenceReportDTO {
        struct Envelope: Decodable { let report: IntelligenceReportDTO }
        let envelope = try await perform(
            "POST", path: "/api/v1/intelligence/reports/\(id)/cancel",
            as: Envelope.self
        )
        return envelope.report
    }

    func fetchIntelligenceEmerging(windowDays: Int = 7) async throws -> IntelligenceEmergingDTO {
        try await perform(
            "GET", path: "/api/v1/intelligence/emerging",
            query: [URLQueryItem(name: "window_days", value: String(windowDays))],
            as: IntelligenceEmergingDTO.self
        )
    }

    func fetchIntelligenceRankings(
        kind: String, window: String = "7d", limit: Int = 5
    ) async throws -> IntelligenceRankingPageDTO {
        try await perform(
            "GET", path: "/api/v1/intelligence/rankings",
            query: [
                URLQueryItem(name: "kind", value: kind),
                URLQueryItem(name: "window", value: window),
                URLQueryItem(name: "limit", value: String(limit)),
            ],
            as: IntelligenceRankingPageDTO.self
        )
    }
}
