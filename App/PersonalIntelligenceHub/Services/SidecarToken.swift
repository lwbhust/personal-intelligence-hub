import Foundation
import Security

enum SidecarTokenError: Error, Sendable {
    case randomBytesFailed(OSStatus)
    case unexpectedLength(Int)
}

/// 生成 32 字节高熵随机 Token，编码为去掉 padding 的 base64url（43 字符）。
/// Token 只保存在内存中，绝不写入文件、UserDefaults、argv 或日志。
enum SidecarToken {
    static let byteCount = 32
    static let expectedLength = 43

    static func generate() throws -> String {
        var bytes = [UInt8](repeating: 0, count: byteCount)
        let status = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        guard status == errSecSuccess else {
            throw SidecarTokenError.randomBytesFailed(status)
        }
        let encoded = Data(bytes)
            .base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        guard encoded.count == expectedLength else {
            throw SidecarTokenError.unexpectedLength(encoded.count)
        }
        return encoded
    }
}
