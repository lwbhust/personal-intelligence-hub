import XCTest
@testable import PersonalIntelligenceHub

/// 握手首行解析测试：覆盖成功路径、前缀/编码/JSON/字段/端口/PID/版本等失败路径。
/// 断言对象是 HandshakeError 的真实 case，不依赖 userMessage 文案。
final class HandshakeParserTests: XCTestCase {

    private let validPayload = #"{"port":54321,"pid":4242,"service":"pih-backend","version":"0.1.0"}"#

    // MARK: - Helpers

    private func line(_ raw: String) -> Data {
        Data(raw.utf8)
    }

    private func handshakeLine(_ payload: String) -> Data {
        line(PIHConstants.handshakePrefix + " " + payload)
    }

    /// 捕获 HandshakeParser 抛出的 HandshakeError；解析成功或抛出其它错误都记为测试失败。
    @discardableResult
    private func captureError(_ data: Data, file: StaticString = #filePath, line: UInt = #line) -> HandshakeError? {
        do {
            let handshake = try HandshakeParser.parse(line: data)
            XCTFail("期望解析失败，实际成功：\(handshake)", file: file, line: line)
            return nil
        } catch let error as HandshakeError {
            return error
        } catch {
            XCTFail("期望 HandshakeError，实际抛出：\(error)", file: file, line: line)
            return nil
        }
    }

    private func assertInvalidJSON(_ error: HandshakeError?, file: StaticString = #filePath, line: UInt = #line) {
        guard let error else { return }
        guard case .invalidJSON = error else {
            XCTFail("期望 .invalidJSON，实际：\(error)", file: file, line: line)
            return
        }
    }

    // MARK: - 成功路径

    func testParsesValidHandshakeLine() throws {
        let handshake = try HandshakeParser.parse(line: handshakeLine(validPayload))

        XCTAssertEqual(handshake.port, 54321)
        XCTAssertEqual(handshake.pid, 4242)
        XCTAssertEqual(handshake.service, "pih-backend")
        XCTAssertEqual(handshake.version, "0.1.0")
    }

    func testAcceptsUnknownExtraJSONFields() throws {
        let payload = #"{"port":54321,"pid":4242,"service":"pih-backend","version":"0.1.0","extra":"ignored"}"#
        let handshake = try HandshakeParser.parse(line: handshakeLine(payload))

        XCTAssertEqual(handshake.port, 54321)
        XCTAssertEqual(handshake.version, "0.1.0")
    }

    func testAcceptsBoundaryValues() throws {
        let payload = #"{"port":65535,"pid":2147483647,"service":"pih-backend","version":"0.9.99"}"#
        let handshake = try HandshakeParser.parse(line: handshakeLine(payload))

        XCTAssertEqual(handshake.port, 65535)
        XCTAssertEqual(handshake.pid, Int(Int32.max))
    }

    // MARK: - 行级错误

    func testRejectsEmptyLine() {
        XCTAssertEqual(captureError(Data()), .emptyLine)
    }

    func testRejectsLineOverByteLimit() {
        let data = Data(repeating: UInt8(ascii: "a"), count: PIHConstants.maxHandshakeLineBytes + 1)
        XCTAssertEqual(captureError(data), .lineTooLong(PIHConstants.maxHandshakeLineBytes + 1))
    }

    func testRejectsInvalidUTF8() {
        XCTAssertEqual(captureError(Data([0x50, 0xFF, 0xFE])), .invalidEncoding)
    }

    func testRejectsMissingPrefix() {
        XCTAssertEqual(captureError(line("SIDECAR_READY " + validPayload)), .missingPrefix)
    }

    func testRejectsPrefixWithoutSeparator() {
        let data = line(PIHConstants.handshakePrefix + validPayload)
        XCTAssertEqual(captureError(data), .missingPrefix)
    }

    // MARK: - JSON 错误

    func testRejectsMalformedJSON() {
        let data = handshakeLine(#"{"port":54321,"pid":}"#)
        let error = captureError(data)
        assertInvalidJSON(error)
    }

    func testRejectsEmptyPayload() {
        let error = captureError(line(PIHConstants.handshakePrefix + " "))
        assertInvalidJSON(error)
    }

    func testRejectsMissingRequiredField() {
        let payload = #"{"port":54321,"pid":4242,"service":"pih-backend"}"#
        let error = captureError(handshakeLine(payload))
        assertInvalidJSON(error)
    }

    func testRejectsWrongJSONType() {
        let payload = #"{"port":"54321","pid":4242,"service":"pih-backend","version":"0.1.0"}"#
        let error = captureError(handshakeLine(payload))
        assertInvalidJSON(error)
    }

    // MARK: - 字段校验

    func testRejectsPortZero() {
        let payload = #"{"port":0,"pid":4242,"service":"pih-backend","version":"0.1.0"}"#
        XCTAssertEqual(captureError(handshakeLine(payload)), .invalidPort(0))
    }

    func testRejectsPortAboveUpperBound() {
        let payload = #"{"port":65536,"pid":4242,"service":"pih-backend","version":"0.1.0"}"#
        XCTAssertEqual(captureError(handshakeLine(payload)), .invalidPort(65536))
    }

    func testRejectsNegativePort() {
        let payload = #"{"port":-1,"pid":4242,"service":"pih-backend","version":"0.1.0"}"#
        XCTAssertEqual(captureError(handshakeLine(payload)), .invalidPort(-1))
    }

    func testRejectsPIDZero() {
        let payload = #"{"port":54321,"pid":0,"service":"pih-backend","version":"0.1.0"}"#
        XCTAssertEqual(captureError(handshakeLine(payload)), .invalidPID(0))
    }

    func testRejectsNegativePID() {
        let payload = #"{"port":54321,"pid":-42,"service":"pih-backend","version":"0.1.0"}"#
        XCTAssertEqual(captureError(handshakeLine(payload)), .invalidPID(-42))
    }

    func testRejectsPIDAboveInt32Max() {
        let payload = #"{"port":54321,"pid":2147483648,"service":"pih-backend","version":"0.1.0"}"#
        XCTAssertEqual(captureError(handshakeLine(payload)), .invalidPID(2147483648))
    }

    func testRejectsServiceMismatch() {
        let payload = #"{"port":54321,"pid":4242,"service":"other-service","version":"0.1.0"}"#
        XCTAssertEqual(captureError(handshakeLine(payload)), .serviceMismatch("other-service"))
    }

    // MARK: - 版本兼容

    func testRejectsIncompatibleMajorVersion() {
        let payload = #"{"port":54321,"pid":4242,"service":"pih-backend","version":"1.0.0"}"#
        XCTAssertEqual(captureError(handshakeLine(payload)), .unsupportedVersion("1.0.0"))
    }

    func testRejectsNonSemverVersion() {
        let payload = #"{"port":54321,"pid":4242,"service":"pih-backend","version":"0.1"}"#
        XCTAssertEqual(captureError(handshakeLine(payload)), .unsupportedVersion("0.1"))
    }

    func testRejectsNonNumericMinorVersion() {
        let payload = #"{"port":54321,"pid":4242,"service":"pih-backend","version":"0.alpha.0"}"#
        XCTAssertEqual(captureError(handshakeLine(payload)), .unsupportedVersion("0.alpha.0"))
    }

    func testRejectsFourComponentVersion() {
        let payload = #"{"port":54321,"pid":4242,"service":"pih-backend","version":"0.1.0.0"}"#
        XCTAssertEqual(captureError(handshakeLine(payload)), .unsupportedVersion("0.1.0.0"))
    }
}
