import Foundation

/// stdout 首行（握手）累积器。readabilityHandler 在后台队列写入，主线程轮询读取。
final class HandshakeLineBox: @unchecked Sendable {
    struct Snapshot: Sendable {
        let line: Data?
        let reachedEOF: Bool
        let overflowed: Bool
        let hasPartialLine: Bool
    }

    private let lock = NSLock()
    private let maxBytes: Int
    private var buffer = Data()
    private var storedLine: Data?
    private var eof = false
    private var overflow = false

    init(maxBytes: Int) {
        self.maxBytes = maxBytes
    }

    func append(_ data: Data) {
        lock.lock()
        defer { lock.unlock() }
        guard storedLine == nil, !eof, !overflow else { return }
        buffer.append(data)

        if let newlineIndex = buffer.firstIndex(of: 0x0A) {
            var content = buffer[buffer.startIndex..<newlineIndex]
            if content.last == 0x0D {
                content = content.dropLast()
            }
            storedLine = Data(content)
            buffer.removeAll(keepingCapacity: false)
        } else if buffer.count > maxBytes {
            overflow = true
        }
    }

    func markEOF() {
        lock.lock()
        eof = true
        lock.unlock()
    }

    func snapshot() -> Snapshot {
        lock.lock()
        defer { lock.unlock() }
        return Snapshot(
            line: storedLine,
            reachedEOF: eof,
            overflowed: overflow,
            hasPartialLine: !buffer.isEmpty
        )
    }
}

/// stderr 尾部环形缓冲。写入时即时脱敏 Token，避免任何 UI/日志泄漏。
final class StderrTailBox: @unchecked Sendable {
    private let lock = NSLock()
    private let secret: String
    private let maxLines: Int
    private let maxCharacters: Int
    private var lines: [String] = []
    private var partial = ""

    init(secret: String, maxLines: Int, maxCharacters: Int) {
        self.secret = secret
        self.maxLines = maxLines
        self.maxCharacters = maxCharacters
    }

    func append(_ data: Data) {
        guard !data.isEmpty else { return }
        let text = String(decoding: data, as: UTF8.self)

        lock.lock()
        defer { lock.unlock() }
        partial += text
        while let newlineIndex = partial.firstIndex(of: "\n") {
            let line = String(partial[..<newlineIndex])
            partial = String(partial[partial.index(after: newlineIndex)...])
            recordLocked(line)
        }
        if partial.count > maxCharacters * 2 {
            recordLocked(partial)
            partial = ""
        }
    }

    func snapshot() -> [String] {
        lock.lock()
        defer { lock.unlock() }
        var result = lines
        if !partial.isEmpty {
            var line = redact(partial).trimmingCharacters(in: .whitespacesAndNewlines)
            if !line.isEmpty {
                if line.count > maxCharacters {
                    line = String(line.prefix(maxCharacters)) + "…"
                }
                result.append(line)
            }
        }
        return result
    }

    private func recordLocked(_ raw: String) {
        var line = redact(raw).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !line.isEmpty else { return }
        if line.count > maxCharacters {
            line = String(line.prefix(maxCharacters)) + "…"
        }
        lines.append(line)
        if lines.count > maxLines {
            lines.removeFirst(lines.count - maxLines)
        }
    }

    private func redact(_ line: String) -> String {
        guard !secret.isEmpty else { return line }
        return line.replacingOccurrences(of: secret, with: "<redacted-token>")
    }
}
