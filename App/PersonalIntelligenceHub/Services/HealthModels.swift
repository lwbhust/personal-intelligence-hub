import Foundation

struct HealthDatabase: Decodable, Sendable {
    let status: String
    let code: String?
    let schemaVersion: Int?
    let pathKind: String?

    enum CodingKeys: String, CodingKey {
        case status
        case code
        case schemaVersion = "schema_version"
        case pathKind = "path_kind"
    }
}

struct HealthBuild: Decodable, Sendable {
    let gitCommit: String?
    let buildTime: String?

    enum CodingKeys: String, CodingKey {
        case gitCommit = "git_commit"
        case buildTime = "build_time"
    }
}

struct HealthResponse: Decodable, Sendable {
    let status: String
    let service: String
    let version: String
    let timestamp: String
    let uptimeSeconds: Double
    let database: HealthDatabase
    let build: HealthBuild?

    enum CodingKeys: String, CodingKey {
        case status
        case service
        case version
        case timestamp
        case uptimeSeconds = "uptime_seconds"
        case database
        case build
    }
}

struct HealthErrorEnvelope: Decodable, Sendable {
    struct Body: Decodable, Sendable {
        let code: String
        let message: String
    }

    let error: Body
}

struct HealthCheckOutcome: Sendable {
    let health: HealthResponse
    let requestID: String?
    let receivedAt: Date
}

enum HealthCheckError: Error, Sendable {
    case unauthorized(message: String?, requestID: String?)
    case contractViolation(reason: String, requestID: String?)
    case transport(reason: String)
}
