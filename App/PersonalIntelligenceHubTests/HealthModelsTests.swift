import XCTest
@testable import PersonalIntelligenceHub

/// 健康响应模型的 JSON 解码契约：完整响应、降级响应、可选字段缺失、
/// 必填字段缺失/类型错误，以及错误信封解码。
final class HealthModelsTests: XCTestCase {

    private let decoder = JSONDecoder()

    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try decoder.decode(type, from: Data(json.utf8))
    }

    // MARK: - 完整响应

    func testDecodesHealthyResponse() throws {
        let json = """
        {
          "status": "ok",
          "service": "pih-backend",
          "version": "0.3.0",
          "timestamp": "2026-11-16T07:00:00Z",
          "uptime_seconds": 12.5,
          "database": {
            "status": "ok",
            "schema_version": 1,
            "path_kind": "runtime"
          }
        }
        """

        let health = try decode(HealthResponse.self, json)

        XCTAssertEqual(health.status, "ok")
        XCTAssertEqual(health.service, "pih-backend")
        XCTAssertEqual(health.version, "0.3.0")
        XCTAssertEqual(health.timestamp, "2026-11-16T07:00:00Z")
        XCTAssertEqual(health.uptimeSeconds, 12.5)
        XCTAssertEqual(health.database.status, "ok")
        XCTAssertNil(health.database.code)
        XCTAssertEqual(health.database.schemaVersion, 1)
        XCTAssertEqual(health.database.pathKind, "runtime")
    }

    func testDecodesDegradedResponseWithDatabaseCode() throws {
        let json = """
        {
          "status": "degraded",
          "service": "pih-backend",
          "version": "0.3.0",
          "timestamp": "2026-11-16T07:00:05Z",
          "uptime_seconds": 3,
          "database": {
            "status": "error",
            "code": "DB_CORRUPTED",
            "schema_version": 1
          }
        }
        """

        let health = try decode(HealthResponse.self, json)

        XCTAssertEqual(health.status, "degraded")
        XCTAssertEqual(health.database.status, "error")
        XCTAssertEqual(health.database.code, "DB_CORRUPTED")
        XCTAssertEqual(health.database.schemaVersion, 1)
        XCTAssertNil(health.database.pathKind)
        XCTAssertEqual(health.uptimeSeconds, 3)
    }

    // MARK: - 缺失字段

    func testOptionalDatabaseFieldsDecodeAsNil() throws {
        let json = """
        {
          "status": "ok",
          "service": "pih-backend",
          "version": "0.3.0",
          "timestamp": "2026-11-16T07:00:00Z",
          "uptime_seconds": 1,
          "database": { "status": "ok" }
        }
        """

        let health = try decode(HealthResponse.self, json)

        XCTAssertEqual(health.database.status, "ok")
        XCTAssertNil(health.database.code)
        XCTAssertNil(health.database.schemaVersion)
        XCTAssertNil(health.database.pathKind)
    }

    func testMissingDatabaseKeyFailsDecoding() {
        let json = """
        {
          "status": "ok",
          "service": "pih-backend",
          "version": "0.3.0",
          "timestamp": "2026-11-16T07:00:00Z",
          "uptime_seconds": 1
        }
        """

        XCTAssertThrowsError(try decode(HealthResponse.self, json)) { error in
            guard case DecodingError.keyNotFound(let key, _) = error else {
                return XCTFail("期望 keyNotFound，实际：\(error)")
            }
            XCTAssertEqual(key.stringValue, "database")
        }
    }

    func testMissingDatabaseStatusFailsDecoding() {
        let json = """
        {
          "status": "ok",
          "service": "pih-backend",
          "version": "0.3.0",
          "timestamp": "2026-11-16T07:00:00Z",
          "uptime_seconds": 1,
          "database": { "schema_version": 1 }
        }
        """

        XCTAssertThrowsError(try decode(HealthResponse.self, json)) { error in
            guard case DecodingError.keyNotFound(let key, _) = error else {
                return XCTFail("期望 keyNotFound，实际：\(error)")
            }
            XCTAssertEqual(key.stringValue, "status")
        }
    }

    func testWrongUptimeTypeFailsDecoding() {
        let json = """
        {
          "status": "ok",
          "service": "pih-backend",
          "version": "0.3.0",
          "timestamp": "2026-11-16T07:00:00Z",
          "uptime_seconds": "12.5",
          "database": { "status": "ok" }
        }
        """

        XCTAssertThrowsError(try decode(HealthResponse.self, json)) { error in
            guard case DecodingError.typeMismatch(_, let context) = error else {
                return XCTFail("期望 typeMismatch，实际：\(error)")
            }
            XCTAssertEqual(context.codingPath.last?.stringValue, "uptime_seconds")
        }
    }

    // MARK: - 错误信封

    func testDecodesErrorEnvelope() throws {
        let json = """
        { "error": { "code": "UNAUTHORIZED", "message": "missing or invalid bearer token" } }
        """

        let envelope = try decode(HealthErrorEnvelope.self, json)

        XCTAssertEqual(envelope.error.code, "UNAUTHORIZED")
        XCTAssertEqual(envelope.error.message, "missing or invalid bearer token")
    }

    func testErrorEnvelopeWithoutErrorKeyFailsDecoding() {
        XCTAssertThrowsError(try decode(HealthErrorEnvelope.self, "{}")) { error in
            guard case DecodingError.keyNotFound(let key, _) = error else {
                return XCTFail("期望 keyNotFound，实际：\(error)")
            }
            XCTAssertEqual(key.stringValue, "error")
        }
    }
}
