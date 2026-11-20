import Foundation

struct SidecarHandshake: Sendable, Equatable {
    let port: Int
    let pid: Int
    let service: String
    let version: String
}

enum HandshakeError: Error, Sendable, Equatable {
    case emptyLine
    case invalidEncoding
    case lineTooLong(Int)
    case missingPrefix
    case invalidJSON(String)
    case invalidPort(Int)
    case invalidPID(Int)
    case serviceMismatch(String)
    case unsupportedVersion(String)

    var userMessage: String {
        switch self {
        case .emptyLine:
            return "握手协议错误：stdout 首行为空"
        case .invalidEncoding:
            return "握手协议错误：首行不是合法的 UTF-8"
        case .lineTooLong(let length):
            return "握手协议错误：首行长度 \(length) 字节超过 4096 字节上限"
        case .missingPrefix:
            return "握手协议错误：首行前缀不是 \(PIHConstants.handshakePrefix)"
        case .invalidJSON(let reason):
            return "握手协议错误：JSON 解析失败（\(reason)）"
        case .invalidPort(let port):
            return "握手协议错误：port=\(port) 不在 1–65535 范围内"
        case .invalidPID(let pid):
            return "握手协议错误：pid=\(pid) 非法"
        case .serviceMismatch(let service):
            return "握手协议错误：service=\(service)，期望 \(PIHConstants.serviceName)"
        case .unsupportedVersion(let version):
            return "版本不兼容：后端版本 \(version) 的 MAJOR 与 App 支持的 \(PIHConstants.supportedBackendMajor) 不一致"
        }
    }
}

enum HandshakeParser {
    private struct RawHandshake: Decodable {
        let port: Int
        let pid: Int
        let service: String
        let version: String
    }

    static func parse(line: Data) throws -> SidecarHandshake {
        guard !line.isEmpty else { throw HandshakeError.emptyLine }
        guard line.count <= PIHConstants.maxHandshakeLineBytes else {
            throw HandshakeError.lineTooLong(line.count)
        }
        guard let text = String(data: line, encoding: .utf8) else {
            throw HandshakeError.invalidEncoding
        }
        let prefix = PIHConstants.handshakePrefix + " "
        guard text.hasPrefix(prefix) else { throw HandshakeError.missingPrefix }

        let payload = String(text.dropFirst(prefix.count))
        let raw: RawHandshake
        do {
            raw = try JSONDecoder().decode(RawHandshake.self, from: Data(payload.utf8))
        } catch {
            throw HandshakeError.invalidJSON(String(describing: error))
        }

        guard (1...65535).contains(raw.port) else { throw HandshakeError.invalidPort(raw.port) }
        guard raw.pid > 0, raw.pid <= Int(Int32.max) else { throw HandshakeError.invalidPID(raw.pid) }
        guard raw.service == PIHConstants.serviceName else {
            throw HandshakeError.serviceMismatch(raw.service)
        }

        let versionParts = raw.version.split(separator: ".")
        guard versionParts.count == 3,
              let major = Int(versionParts[0]),
              Int(versionParts[1]) != nil,
              Int(versionParts[2]) != nil else {
            throw HandshakeError.unsupportedVersion(raw.version)
        }
        guard major == PIHConstants.supportedBackendMajor else {
            throw HandshakeError.unsupportedVersion(raw.version)
        }

        return SidecarHandshake(
            port: raw.port,
            pid: raw.pid,
            service: raw.service,
            version: raw.version
        )
    }
}
