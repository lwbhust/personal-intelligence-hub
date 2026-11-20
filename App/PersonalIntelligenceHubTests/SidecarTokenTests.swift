import XCTest
@testable import PersonalIntelligenceHub

/// 一次性 Sidecar Token 的生成契约：43 字符、base64url 字符集、每次不同、可还原 32 字节。
final class SidecarTokenTests: XCTestCase {

    private let base64URLAlphabet = CharacterSet(
        charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )

    func testGeneratedTokenHasExpectedLength() throws {
        let token = try SidecarToken.generate()
        XCTAssertEqual(token.count, SidecarToken.expectedLength)
        XCTAssertEqual(token.count, 43)
    }

    func testGeneratedTokenUsesOnlyBase64URLCharacters() throws {
        let token = try SidecarToken.generate()
        XCTAssertTrue(
            token.unicodeScalars.allSatisfy { base64URLAlphabet.contains($0) },
            "Token 含 base64url 之外的字符：\(token)"
        )
        XCTAssertFalse(token.contains("+"))
        XCTAssertFalse(token.contains("/"))
        XCTAssertFalse(token.contains("="))
    }

    func testConsecutiveTokensDiffer() throws {
        let first = try SidecarToken.generate()
        let second = try SidecarToken.generate()
        XCTAssertNotEqual(first, second)
    }

    func testGeneratedTokenDecodesToThirtyTwoBytes() throws {
        let token = try SidecarToken.generate()
        let base64 = token
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let padded = base64 + String(repeating: "=", count: (4 - base64.count % 4) % 4)
        let decoded = try XCTUnwrap(Data(base64Encoded: padded))

        XCTAssertEqual(decoded.count, SidecarToken.byteCount)
        XCTAssertEqual(decoded.count, 32)
    }
}
