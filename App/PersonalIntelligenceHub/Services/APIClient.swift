import Foundation

/// 业务 API 的结构化错误。`message` 来自服务端固定文案，可直接展示。
struct APIRequestError: Error, Sendable {
    struct Field: Sendable, Equatable {
        let field: String
        let reason: String
        let message: String
    }

    let code: String
    let message: String
    let status: Int
    let requestID: String?
    let fields: [Field]
}

private struct APIErrorEnvelope: Decodable {
    struct Body: Decodable {
        struct Detail: Decodable {
            let field: String
            let reason: String
            let message: String
        }

        let code: String
        let message: String
        let details: [Detail]?
    }

    let error: Body
}

/// 仅用于 /health 的 HTTP 客户端。Token 只存在于内存与请求头。
final class APIClient: @unchecked Sendable {
    let port: Int
    private let token: String
    private let expectedVersion: String
    private let session: URLSession
    private let dataSession: URLSession

    init(port: Int, token: String, expectedVersion: String) {
        self.port = port
        self.token = token
        self.expectedVersion = expectedVersion

        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = PIHConstants.healthTimeout
        configuration.timeoutIntervalForResource = PIHConstants.healthTimeout
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        configuration.waitsForConnectivity = false
        configuration.httpMaximumConnectionsPerHost = 1
        self.session = URLSession(configuration: configuration)

        let dataConfiguration = URLSessionConfiguration.ephemeral
        dataConfiguration.timeoutIntervalForRequest = PIHConstants.apiTimeout
        dataConfiguration.timeoutIntervalForResource = PIHConstants.apiTimeout
        dataConfiguration.requestCachePolicy = .reloadIgnoringLocalCacheData
        dataConfiguration.urlCache = nil
        dataConfiguration.waitsForConnectivity = false
        dataConfiguration.httpMaximumConnectionsPerHost = 4
        self.dataSession = URLSession(configuration: dataConfiguration)
    }

    deinit {
        session.invalidateAndCancel()
        dataSession.invalidateAndCancel()
    }

    func fetchHealth() async throws -> HealthCheckOutcome {
        guard let url = URL(string: "http://127.0.0.1:\(port)/health") else {
            throw HealthCheckError.contractViolation(reason: "无法构造 /health URL", requestID: nil)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = PIHConstants.healthTimeout
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw HealthCheckError.transport(reason: Self.describe(error))
        }

        guard let http = response as? HTTPURLResponse else {
            throw HealthCheckError.contractViolation(reason: "响应不是 HTTP 响应", requestID: nil)
        }
        let requestID = http.value(forHTTPHeaderField: "X-Request-ID")

        switch http.statusCode {
        case 200:
            break
        case 401:
            let envelope = try? JSONDecoder().decode(HealthErrorEnvelope.self, from: data)
            throw HealthCheckError.unauthorized(message: envelope?.error.message, requestID: requestID)
        default:
            let envelope = try? JSONDecoder().decode(HealthErrorEnvelope.self, from: data)
            let code = envelope?.error.code ?? "unknown"
            throw HealthCheckError.contractViolation(
                reason: "HTTP \(http.statusCode)（错误码 \(code)）",
                requestID: requestID
            )
        }

        let decoded: HealthResponse
        do {
            decoded = try JSONDecoder().decode(HealthResponse.self, from: data)
        } catch {
            throw HealthCheckError.contractViolation(
                reason: "健康响应 JSON 解析失败：\(Self.describe(error))",
                requestID: requestID
            )
        }

        guard decoded.service == PIHConstants.serviceName else {
            throw HealthCheckError.contractViolation(
                reason: "health.service=\(decoded.service) 与契约不一致",
                requestID: requestID
            )
        }
        guard decoded.version == expectedVersion else {
            throw HealthCheckError.contractViolation(
                reason: "health.version=\(decoded.version) 与握手版本 \(expectedVersion) 不一致",
                requestID: requestID
            )
        }
        guard decoded.status == "ok" || decoded.status == "degraded" else {
            throw HealthCheckError.contractViolation(
                reason: "health.status=\(decoded.status) 非法",
                requestID: requestID
            )
        }
        guard decoded.database.status == "ok" || decoded.database.status == "error" else {
            throw HealthCheckError.contractViolation(
                reason: "database.status=\(decoded.database.status) 非法",
                requestID: requestID
            )
        }

        return HealthCheckOutcome(health: decoded, requestID: requestID, receivedAt: Date())
    }

    static func describe(_ error: Error) -> String {
        let nsError = error as NSError
        return "\(nsError.localizedDescription)（\(nsError.domain) \(nsError.code)）"
    }

    // MARK: - Business request plumbing (Phase 1)

    private func makeRequest(
        method: String,
        path: String,
        query: [URLQueryItem],
        body: Data?
    ) throws -> URLRequest {
        var components = URLComponents()
        components.scheme = "http"
        components.host = "127.0.0.1"
        components.port = port
        components.path = path
        if !query.isEmpty {
            components.queryItems = query
        }
        guard let url = components.url else {
            throw APIRequestError(
                code: "invalid_url",
                message: "无法构造请求地址",
                status: 0,
                requestID: nil,
                fields: []
            )
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = PIHConstants.apiTimeout
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.httpBody = body
            request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        }
        return request
    }

    private func send(
        method: String,
        path: String,
        query: [URLQueryItem],
        body: Data?,
        allowEmpty: Bool
    ) async throws -> (Data, String?) {
        let request = try makeRequest(method: method, path: path, query: query, body: body)
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await dataSession.data(for: request)
        } catch {
            // 页面切换或 SwiftUI 任务取消不应伪装成网络故障。
            if error is CancellationError { throw error }
            if let urlError = error as? URLError, urlError.code == .cancelled { throw error }
            throw APIRequestError(
                code: "transport",
                message: "无法连接本地服务：\(Self.describe(error))",
                status: 0,
                requestID: nil,
                fields: []
            )
        }
        guard let http = response as? HTTPURLResponse else {
            throw APIRequestError(
                code: "invalid_response",
                message: "响应不是 HTTP 响应",
                status: 0,
                requestID: nil,
                fields: []
            )
        }
        let requestID = http.value(forHTTPHeaderField: "X-Request-ID")
        if (200..<300).contains(http.statusCode) {
            if http.statusCode == 204 && !allowEmpty {
                return (Data(), requestID)
            }
            return (data, requestID)
        }

        let envelope = try? JSONDecoder().decode(APIErrorEnvelope.self, from: data)
        let fields = (envelope?.error.details ?? []).map {
            APIRequestError.Field(field: $0.field, reason: $0.reason, message: $0.message)
        }
        throw APIRequestError(
            code: envelope?.error.code ?? "http_\(http.statusCode)",
            message: envelope?.error.message ?? "请求失败（HTTP \(http.statusCode)）",
            status: http.statusCode,
            requestID: requestID,
            fields: fields
        )
    }

    func perform<T: Decodable>(
        _ method: String,
        path: String,
        query: [URLQueryItem] = [],
        body: Data? = nil,
        as type: T.Type
    ) async throws -> T {
        let (data, requestID) = try await send(
            method: method,
            path: path,
            query: query,
            body: body,
            allowEmpty: false
        )
        do {
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIRequestError(
                code: "decode_failed",
                message: "响应解析失败：\(Self.describe(error))",
                status: 0,
                requestID: requestID,
                fields: []
            )
        }
    }

    func performNoContent(
        _ method: String,
        path: String,
        body: Data? = nil
    ) async throws {
        _ = try await send(
            method: method,
            path: path,
            query: [],
            body: body,
            allowEmpty: true
        )
    }
}
